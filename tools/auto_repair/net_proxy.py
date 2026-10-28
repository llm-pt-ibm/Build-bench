"""The network of a build: an HTTP(S) proxy on a Unix socket that lets a
build reach any host and logs every connection, so that each run records
what its builds downloaded from.

The build's container has no network of its own (--network none); the socket
is mounted into it, and scripts/script_worker/proxy_forward.py makes it a
proxy on 127.0.0.1 there (http_proxy/https_proxy), which Bazel, pip, git and
curl use. HTTPS goes through CONNECT, so only the host and port are seen,
not the path.

Log: one line per connection, "<time> <reached|failed> <METHOD> <host:port>[<path>]".

Usage: net_proxy.py --socket S --log L -- command...
serves while the command runs, and exits with its status. Standalone (no
imports from the framework), so it runs with any Python 3."""
import argparse
import os
import select
import socket
import socketserver
import subprocess
import sys
import threading
import time

TIMEOUT = 600          # seconds without traffic before a tunnel is closed


def split_host(hostport: str, default_port: int):
    if hostport.startswith("["):                     # [IPv6]:port
        host, _, rest = hostport[1:].partition("]")
        return host, int(rest[1:]) if rest.startswith(":") else default_port
    host, _, port = hostport.rpartition(":") if ":" in hostport else (hostport, "", "")
    return host, int(port) if port.isdigit() else default_port


def pipe(a: socket.socket, b: socket.socket) -> None:
    """Copy both ways until one side closes."""
    sockets = [a, b]
    while True:
        ready, _, _ = select.select(sockets, [], [], TIMEOUT)
        if not ready:
            return
        for s in ready:
            data = s.recv(65536)
            if not data:
                return
            (b if s is a else a).sendall(data)


class Handler(socketserver.StreamRequestHandler):
    rbufsize = 0       # unbuffered: what follows the headers stays in the socket for pipe()
    log = None
    lock = threading.Lock()

    def record(self, outcome: str, method: str, target: str) -> None:
        with self.lock:
            self.log.write(f"{time.strftime('%H:%M:%S')} {outcome} {method} {target}\n")
            self.log.flush()

    def refuse(self, code: int, reason: str, text: str) -> None:
        body = (text + "\n").encode()
        self.wfile.write(f"HTTP/1.1 {code} {reason}\r\nContent-Type: text/plain\r\n"
                         f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)

    def handle(self) -> None:
        line = self.rfile.readline(65536).decode("latin-1")
        try:
            method, target, version = line.split()
        except ValueError:
            return
        headers = []
        while True:
            h = self.rfile.readline(65536)
            if h in (b"\r\n", b"\n", b""):
                break
            headers.append(h.decode("latin-1"))
        if method.upper() == "CONNECT":
            host, port = split_host(target, 443)
            path = ""
        else:
            if not target.lower().startswith("http://"):
                return self.refuse(400, "Bad Request", "only proxy requests (absolute http:// URLs) are served")
            rest = target[7:]
            hostport, slash, path = rest.partition("/")
            host, port = split_host(hostport, 80)
            path = slash + path
        where = f"{host}:{port}"
        try:
            upstream = socket.create_connection((host, port), timeout=60)
        except OSError as e:
            self.record("failed", method, where + path)
            return self.refuse(502, "Bad Gateway", f"build-bench: cannot reach {where}: {e}")
        self.record("reached", method, where + path)
        with upstream:
            upstream.settimeout(None)
            if method.upper() == "CONNECT":
                self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            else:
                kept = [h for h in headers if not h.lower().startswith(("proxy-", "connection:"))]
                upstream.sendall(f"{method} {path or '/'} {version}\r\n{''.join(kept)}Connection: close\r\n\r\n"
                                 .encode("latin-1"))
            self.wfile.flush()
            pipe(self.connection, upstream)


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--socket", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    Handler.log = open(args.log, "a", encoding="utf-8")
    if os.path.exists(args.socket):
        os.remove(args.socket)
    # bound by its name in its directory: socket paths are limited to 107 characters
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(args.socket)))
    try:
        server = Server(os.path.basename(args.socket), Handler)
        os.chmod(os.path.basename(args.socket), 0o600)
    finally:
        os.chdir(cwd)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if not command:                                   # serve until stopped
        threading.Event().wait()
    try:
        return subprocess.call(command)
    finally:
        server.shutdown()
        server.server_close()
        os.remove(args.socket)


if __name__ == "__main__":
    sys.exit(main())
