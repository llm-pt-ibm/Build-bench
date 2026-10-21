"""Inside a build's container (no network): make the framework's proxy, a
Unix socket mounted in (tools/auto_repair/net_proxy.py), a proxy on
127.0.0.1:<port> for the build's tools. Started by run.sh; prints "ready"
when it listens. Python 3.6 (the system Python of RHEL 8 images).
Usage: proxy_forward.py <socket> <port>"""
import os
import select
import socket
import sys
import threading


def pipe(a, b):
    try:
        while True:
            ready, _, _ = select.select([a, b], [], [])
            for s in ready:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        pass
    finally:
        a.close()
        b.close()


def main():
    path, port = sys.argv[1], int(sys.argv[2])
    os.chdir(os.path.dirname(os.path.abspath(path)))   # socket paths are limited to 107 characters
    path = os.path.basename(path)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(128)
    print("ready", flush=True)
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)   # run.sh stops reading
    while True:
        client, _ = listener.accept()
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            upstream.connect(path)
        except OSError:
            client.close()
            upstream.close()
            continue
        threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()


if __name__ == "__main__":
    main()
