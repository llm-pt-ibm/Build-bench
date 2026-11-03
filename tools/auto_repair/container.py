"""Docker containers for build-recipe cases: build.sh, the acceptance test and
run_command_tool's commands always run in Docker, in an image of the case's
build environment (build-bench-<environment>, made by make setup-env), with
only what is mounted in, at the same paths as on the host. The settings are
build.container of bench.yaml."""
import os
import shlex
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENVS_DIR = os.path.join(ROOT, "envs")
NET_PROXY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "net_proxy.py")
RUNTIME = "docker"


def settings(build_cfg: dict) -> dict:
    """The container section of a config's `build`."""
    c = (build_cfg or {}).get("container") or {}
    name = str(c.get("runtime") or RUNTIME).lower()   # of older configs; auto is Docker
    # pids_limit -1: no limit (2048 stopped jaxlib's test suite)
    return {"runtime": RUNTIME if name == "auto" else name,
            "build_network": _network(os.getenv("BENCH_BUILD_NETWORK") or c.get("build_network") or "log"),
            "cpus": c.get("cpus"), "memory": c.get("memory"), "pids_limit": c.get("pids_limit", -1)}


def available() -> bool:
    return shutil.which(RUNTIME) is not None


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
    c = cfg.get("container") or {}
    cmd = [RUNTIME, "run", "--rm", "--name", name, "--network", network, "--security-opt", "label=disable",
           "-w", workdir, "--pids-limit", str(c.get("pids_limit", -1))]
    if os.geteuid() != 0:   # files written in the mounts belong to the user
        cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
    if drop_capabilities:
        cmd += ["--cap-drop=all", "--security-opt", "no-new-privileges"]
    if c.get("cpus"):
        cmd += ["--cpus", str(c["cpus"])]
    if c.get("memory"):
        cmd += ["--memory", str(c["memory"])]
    for path, writable in mounts:
        cmd += ["-v", f"{path}:{path}:{'rw' if writable else 'ro'}"]
    for path in tmpfs:   # an empty directory over a hidden path
        cmd += ["--mount", f"type=tmpfs,destination={path},ro=true"]
    # docker run --user gives a user unknown to the image: Bazel needs USER,
    # and Docker leaves HOME at /
    user = user_name()
    for key, value in dict({"USER": user, "LOGNAME": user, "HOME": "/tmp"}, **env).items():
        cmd += ["-e", f"{key}={value}"]
    return cmd + [image(env_name)] + list(argv)


def user_name() -> str:
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, KeyError):
        return os.getenv("USER") or str(os.getuid())


def _network(name: str) -> str:
    name = name.lower()
    return "log" if name in ("proxy", "audit") else name


def build_network(cfg: dict, env_name: str, run_dir: str) -> dict:
    """How build.sh reaches the network: the container's network, and for log
    the proxy that wraps the container command (it serves on a socket mounted
    in; run.sh makes it the build's http(s)_proxy)."""
    mode = (cfg.get("container") or {}).get("build_network", "log")
    if mode != "log":
        return {"network": mode, "mounts": [], "env": {}, "wrapper": []}
    net_dir = os.path.join(run_dir, "net")
    os.makedirs(net_dir, exist_ok=True)
    sock, log = os.path.join(net_dir, "proxy.sock"), os.path.join(run_dir, "network.log")
    if os.path.exists(log):
        os.remove(log)
    return {"network": "none", "mounts": [(net_dir, False)], "env": {"BENCH_PROXY_SOCKET": sock},
            "wrapper": [sys.executable, NET_PROXY, "--socket", sock, "--log", log, "--"]}


def network_log(run_dir: str) -> dict:
    """Hosts the last build reached, and those it could not reach (build_network log)."""
    hosts = {"reached": set(), "failed": set()}
    try:
        with open(os.path.join(run_dir, "network.log"), encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[1] in hosts:
                    hosts[parts[1]].add(parts[3].split("/", 1)[0])
    except OSError:
        pass
    return {k: sorted(v) for k, v in hosts.items()}


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
    if names and available():
        subprocess.run([RUNTIME, "rm", "-f", *names], capture_output=True, env=runtime_env())


def remove_matching(cfg: dict, prefix: str) -> None:
    """Stop and remove every container whose name starts with prefix."""
    if not available():
        return
    out = subprocess.run([RUNTIME, "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True,
                         env=runtime_env())
    names = [n for n in out.stdout.split() if n.startswith(prefix)]
    if names:
        remove(cfg, *names)


def check(cfg: dict, env_name: str):
    """Why containers cannot run for env_name (None when they can)."""
    problem = runtime_problem(cfg)
    if problem:
        return problem
    mode = (cfg.get("container") or {}).get("build_network", "log")
    if mode not in ("log", "host", "none"):
        return f"build_network {mode}: use log, host or none"
    if not env_name:
        return ("the case has no build environment (\"environment\" in manifest.json), whose image its "
                "containers run in: give it one (README, Cases)")
    out = subprocess.run([RUNTIME, "image", "inspect", image(env_name)], capture_output=True, env=runtime_env())
    if out.returncode != 0:
        return f"no image {image(env_name)}: run make setup-env ENV={env_name}"
    return None


def runtime_problem(cfg: dict):
    """Why Docker cannot run the containers (None when it can): its daemon
    must answer this user, and the config must not ask for another runtime."""
    name = (cfg.get("container") or {}).get("runtime", RUNTIME)
    if name != RUNTIME:
        return (f"build.container.runtime {name}: builds, acceptance tests and commands always run in "
                "Docker; remove the setting from the config")
    if not available():
        return "docker not found: install Docker and add the user to the docker group (README, Installation)"
    out = subprocess.run([RUNTIME, "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True,
                         env=runtime_env())
    if out.returncode != 0:
        error = (out.stderr.strip().splitlines() or ["no answer"])[-1]
        return f"docker cannot be used: {error} (is its daemon running, and the user in the docker group?)"
    return None


def image_id(cfg: dict, env_name: str):
    """The id of env_name's image as Docker has it now (None without one)."""
    if not env_name or not available():
        return None
    out = subprocess.run([RUNTIME, "image", "inspect", "--format", "{{.Id}}", image(env_name)],
                         capture_output=True, text=True, env=runtime_env())
    return out.stdout.strip().removeprefix("sha256:") or None if out.returncode == 0 else None


def _base_containerfile(env_name: str) -> str:
    path = os.path.join(ENVS_DIR, env_name, "Containerfile")
    return path if os.path.isfile(path) else os.path.join(ENVS_DIR, "Containerfile")


def containerfile(env_name: str, system: list = ()) -> str:
    """The Containerfile of env_name's image: envs/<env_name>/Containerfile or
    the default envs/Containerfile, with the RHEL packages of env.yaml's system."""
    with open(_base_containerfile(env_name)) as f:
        text = f.read()
    if system:
        text += ("\n# system of envs/" + env_name + "/env.yaml\n"
                 "RUN dnf install -y --setopt=install_weak_deps=False --nodocs "
                 + " ".join(shlex.quote(p) for p in system) + " \\\n    && dnf clean all\n")
    return text


def build_image(cfg: dict, env_name: str, packages_file: str, system: list = ()) -> dict:
    """Build env_name's image (containerfile()), write the packages it has (rpm
    or dpkg) to packages_file; returns what env.json records of it."""
    import hashlib
    text = containerfile(env_name, system)
    # the file next to the environment; the context is the base Containerfile's directory
    containerfile_path = os.path.join(os.path.dirname(packages_file), "Containerfile")
    with open(containerfile_path, "w") as f:
        f.write(text)
    context = os.path.dirname(_base_containerfile(env_name))
    subprocess.run([RUNTIME, "build", "--network", "host", "-t", image(env_name), "-f", containerfile_path, context],
                   check=True, env=runtime_env())
    listing = subprocess.run(
        [RUNTIME, "run", "--rm", "--network", "none", image(env_name), "sh", "-c",
         "rpm -qa --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\\n' 2>/dev/null || "
         "dpkg-query -W -f '${Package}=${Version}\\n'"],
        capture_output=True, text=True, check=True, env=runtime_env()).stdout
    packages = "".join(sorted(listing.splitlines(keepends=True)))
    with open(packages_file, "w") as f:
        f.write(packages)
    base = next((line.split()[1] for line in text.splitlines() if line.upper().startswith("FROM ")), None)
    return {"name": image(env_name), "id": image_id(cfg, env_name), "runtime": RUNTIME, "base": base,
            "system": list(system),
            "packages": len(packages.splitlines()),
            "packages_sha256": hashlib.sha256(packages.encode()).hexdigest()}
