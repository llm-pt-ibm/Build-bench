"""Containers for build-recipe cases: build.sh, the acceptance test and
run_command_tool's commands run in a container of the case's build
environment image (Podman by default, Docker as an alternative), so that they
see only what is mounted in, at the same paths as on the host: the package's
build copy, its caches, the build environment (read-only) and the framework's
runner. The host itself (other users' files, earlier runs, the framework,
other builds) is out of their reach; without a container (runtime: none)
build.sh runs on the host with everything the user can read.

Config (build.container), BENCH_CONTAINER_RUNTIME overriding the runtime:
  runtime        auto (default: podman if installed, else docker), podman, docker, or none
  build_network  network of build.sh (tests and commands have none):
                 proxy (default): only the hosts its build environment may
                   download from (envs/<env>/allowed_hosts.txt, and
                   allowed_hosts here), through the framework's proxy
                   (tools/auto_repair/net_proxy.py), which logs every
                   connection to the run directory's network.log
                 audit: through the proxy to every host, to make that list
                 host: the host's network; none: no network at all
  allowed_hosts  more hosts for proxy, e.g. a local mirror
  cpus, memory   optional limits (with rootless runtimes they need cgroups v2)
  pids_limit     processes and threads of a container: -1 (default) none
                 beyond the host's, as with Docker (Podman's own default,
                 2048, is too few for parallel test suites: 48 pytest
                 workers with OpenBLAS's threads each)

Images: envs/<environment>/Containerfile, built by make setup-env as
build-bench-<environment>. Rootless Podman maps the user into the container
(files written in the mounts belong to the user); Docker runs the container
as the user (--user uid:gid), and its daemon makes its group root-equivalent."""
import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENVS_DIR = os.path.join(ROOT, "envs")
NET_PROXY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "net_proxy.py")


def settings(build_cfg: dict) -> dict:
    """The container section of a config's `build`."""
    c = (build_cfg or {}).get("container") or {}
    name = (os.getenv("BENCH_CONTAINER_RUNTIME") or c.get("runtime") or "auto").lower()
    if name == "auto":   # podman if it is installed, else docker
        name = "docker" if not available("podman") and available("docker") else "podman"
    return {"runtime": name,
            "build_network": (os.getenv("BENCH_BUILD_NETWORK") or c.get("build_network") or "proxy").lower(),
            "allowed_hosts": list(c.get("allowed_hosts") or []),
            "cpus": c.get("cpus"), "memory": c.get("memory"), "pids_limit": c.get("pids_limit", -1)}


def runtime(cfg: dict):
    """The container runtime of a loaded config (load_obs_config), or None."""
    name = (cfg.get("container") or {}).get("runtime", "none")
    return None if name in ("none", "", None) else name


def available(name: str) -> bool:
    return shutil.which(name) is not None


def image(env_name: str) -> str:
    return f"build-bench-{env_name}"


def runtime_env() -> dict:
    # Go's own DNS resolver fails with some resolvers (e.g. Docker's embedded
    # one when the build host is itself a container); use the system's
    return dict(os.environ, GODEBUG="netdns=cgo")


def command(cfg: dict, name: str, env_name: str, mounts: list, env: dict, workdir: str, argv: list,
            network: str = "none", drop_capabilities: bool = False, tmpfs: list = ()) -> list:
    """The command that runs argv in a container of env_name's image.
    mounts: (path, writable) pairs, mounted at the same paths."""
    rt = runtime(cfg)
    c = cfg.get("container") or {}
    cmd = [rt, "run", "--rm", "--name", name, "--network", network, "--security-opt", "label=disable",
           "-w", workdir, "--pids-limit", str(c.get("pids_limit", -1))]
    if os.geteuid() != 0:
        cmd += ["--userns=keep-id"] if rt == "podman" else ["--user", f"{os.getuid()}:{os.getgid()}"]
    if drop_capabilities:
        cmd += ["--cap-drop=all", "--security-opt", "no-new-privileges"]
    if c.get("cpus"):
        cmd += ["--cpus", str(c["cpus"])]
    if c.get("memory"):
        cmd += ["--memory", str(c["memory"])]
    for path, writable in mounts:
        cmd += ["-v", f"{path}:{path}:{'rw' if writable else 'ro'}"]
    for path in tmpfs:
        # an empty directory over a hidden path (Podman would copy its contents in)
        cmd += ["--mount", f"type=tmpfs,destination={path},ro=true" + (",notmpcopyup" if rt == "podman" else "")]
    for key, value in env.items():
        cmd += ["-e", f"{key}={value}"]
    return cmd + [image(env_name)] + list(argv)


def allowed_hosts_file(env_name: str) -> str:
    return os.path.join(ENVS_DIR, env_name or "", "allowed_hosts.txt")


def allowed_hosts(cfg: dict, env_name: str) -> list:
    """The hosts builds in env_name may download from (build_network proxy)."""
    rules = list((cfg.get("container") or {}).get("allowed_hosts") or [])
    path = allowed_hosts_file(env_name)
    if os.path.isfile(path):
        with open(path) as f:
            rules += [r for r in (line.split("#", 1)[0].strip() for line in f) if r]
    return rules


def build_network(cfg: dict, env_name: str, run_dir: str) -> dict:
    """How build.sh reaches the network: the container's network, and for
    proxy and audit the proxy that wraps the container command (it serves on
    a socket mounted in; run.sh makes it the build's http(s)_proxy)."""
    mode = (cfg.get("container") or {}).get("build_network", "proxy")
    if mode not in ("proxy", "audit"):
        return {"network": mode, "mounts": [], "env": {}, "wrapper": []}
    net_dir = os.path.join(run_dir, "net")
    os.makedirs(net_dir, exist_ok=True)
    sock, log = os.path.join(net_dir, "proxy.sock"), os.path.join(run_dir, "network.log")
    if os.path.exists(log):
        os.remove(log)
    rules = ["*"] if mode == "audit" else allowed_hosts(cfg, env_name)
    wrapper = [sys.executable, NET_PROXY, "--socket", sock, "--log", log]
    for rule in rules:
        wrapper += ["--allow", rule]
    return {"network": "none", "mounts": [(net_dir, False)], "env": {"BENCH_PROXY_SOCKET": sock},
            "wrapper": wrapper + ["--"]}


def network_log(run_dir: str) -> dict:
    """Hosts the last build reached and was refused (build_network proxy/audit)."""
    reached, refused = set(), set()
    try:
        with open(os.path.join(run_dir, "network.log"), encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4:
                    host = parts[3].split("/", 1)[0]
                    (refused if parts[1] == "blocked" else reached).add(host)
    except OSError:
        pass
    return {"reached": sorted(reached), "refused": sorted(refused)}


def framework_mounts(env_name: str) -> list:
    """What every container of the framework needs: the runner, the
    environment scripts and the build environment, read-only."""
    from tools.auto_repair.paths import env_dir
    mounts = [(os.path.join(ROOT, "scripts", "script_worker"), False), (ENVS_DIR, False)]
    if env_name and os.path.isdir(env_dir(env_name)):
        mounts.append((env_dir(env_name), False))
    return mounts


def remove(cfg: dict, *names: str) -> None:
    """Stop and remove containers (e.g. of a build that is being replaced)."""
    rt = runtime(cfg)
    if rt and names and available(rt):
        grace = ["-t", "5"] if rt == "podman" else []  # docker rm -f kills at once
        subprocess.run([rt, "rm", "-f", *grace, *names], capture_output=True, env=runtime_env())


def remove_matching(cfg: dict, prefix: str) -> None:
    """Stop and remove every container whose name starts with prefix."""
    rt = runtime(cfg)
    if not rt or not available(rt):
        return
    out = subprocess.run([rt, "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True,
                         env=runtime_env())
    names = [n for n in out.stdout.split() if n.startswith(prefix)]
    if names:
        remove(cfg, *names)


def check(cfg: dict, env_name: str, build: bool = True):
    """Why containers cannot run for env_name (None when they can); build:
    for build.sh, whose network may need the environment's allowed hosts."""
    rt = runtime(cfg)
    if not rt:
        return None
    if not available(rt):
        return (f"{rt} not found: install it, or set build.container.runtime to "
                f"{'docker' if rt == 'podman' else 'podman'} or none in the config")
    mode = (cfg.get("container") or {}).get("build_network", "proxy")
    if mode not in ("proxy", "audit", "host", "none"):
        return f"build_network {mode}: use proxy, audit, host or none"
    if not env_name:
        return ("the case has no build environment (\"environment\" in manifest.json), whose image its "
                "containers run in: give it one (README, Cases), or set build.container.runtime none")
    out = subprocess.run([rt, "image", "exists" if rt == "podman" else "inspect", image(env_name)],
                         capture_output=True, env=runtime_env())
    if out.returncode != 0:
        return f"no image {image(env_name)}: run make setup-env ENV={env_name}"
    if build and mode == "proxy" and not allowed_hosts(cfg, env_name):
        return (f"build_network proxy needs the hosts builds may download from: make "
                f"{os.path.relpath(allowed_hosts_file(env_name), ROOT)} from the network.log of a build "
                "with build_network audit")
    return None


def image_id(cfg: dict, env_name: str):
    """The id of env_name's image as the runtime has it now (None without one)."""
    rt = runtime(cfg)
    if not rt or not env_name or not available(rt):
        return None
    out = subprocess.run([rt, "image", "inspect", "--format", "{{.Id}}", image(env_name)],
                         capture_output=True, text=True, env=runtime_env())
    return out.stdout.strip().removeprefix("sha256:") or None if out.returncode == 0 else None


def build_image(cfg: dict, env_name: str, packages_file: str) -> dict:
    """Build env_name's image from envs/<env_name>/Containerfile, write the
    packages it has (rpm or dpkg) to packages_file; returns what env.json
    records of it."""
    import hashlib
    rt = runtime(cfg)
    context = os.path.join(ENVS_DIR, env_name)
    containerfile = os.path.join(context, "Containerfile")
    subprocess.run([rt, "build", "--network", "host", "-t", image(env_name), "-f", containerfile, context],
                   check=True, env=runtime_env())
    listing = subprocess.run(
        [rt, "run", "--rm", "--network", "none", image(env_name), "sh", "-c",
         "rpm -qa --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\\n' 2>/dev/null || "
         "dpkg-query -W -f '${Package}=${Version}\\n'"],
        capture_output=True, text=True, check=True, env=runtime_env()).stdout
    packages = "".join(sorted(listing.splitlines(keepends=True)))
    with open(packages_file, "w") as f:
        f.write(packages)
    with open(containerfile) as f:
        base = next((line.split()[1] for line in f if line.upper().startswith("FROM ")), None)
    return {"name": image(env_name), "id": image_id(cfg, env_name), "runtime": rt, "base": base,
            "packages": len(packages.splitlines()),
            "packages_sha256": hashlib.sha256(packages.encode()).hexdigest()}
