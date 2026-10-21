"""Containers for build-recipe cases: build.sh, the acceptance test and
run_command_tool's commands run in a container of the case's build
environment image (Podman by default, Docker as an alternative), so that they
see only what is mounted in, at the same paths as on the host: the package's
build copy, its caches, the build environment (read-only) and the framework's
runner. The host itself (other users' files, earlier runs, the framework,
other builds) is out of their reach; without a container (runtime: none)
build.sh runs on the host with everything the user can read.

Config (build.container), BENCH_CONTAINER_RUNTIME overriding the runtime:
  runtime        podman (default), docker, or none
  build_network  network of build.sh: host (default; builds download their
                 dependencies) or none; tests and commands run with none
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

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENVS_DIR = os.path.join(ROOT, "envs")


def settings(build_cfg: dict) -> dict:
    """The container section of a config's `build`."""
    c = (build_cfg or {}).get("container") or {}
    return {"runtime": (os.getenv("BENCH_CONTAINER_RUNTIME") or c.get("runtime") or "podman").lower(),
            "build_network": c.get("build_network", "host"),
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


def check(cfg: dict, env_name: str):
    """Why containers cannot run for env_name (None when they can)."""
    rt = runtime(cfg)
    if not rt:
        return None
    if not available(rt):
        return (f"{rt} not found: install it, or set build.container.runtime to "
                f"{'docker' if rt == 'podman' else 'podman'} or none in the config")
    if not env_name:
        return ("the case has no build environment (\"environment\" in manifest.json), whose image its "
                "containers run in: give it one (README, Cases), or set build.container.runtime none")
    out = subprocess.run([rt, "image", "exists" if rt == "podman" else "inspect", image(env_name)],
                         capture_output=True, env=runtime_env())
    if out.returncode != 0:
        return f"no image {image(env_name)}: run make setup-env ENV={env_name}"
    return None


def build_image(cfg: dict, env_name: str) -> str:
    """Build env_name's image from envs/<env_name>/Containerfile; returns its id."""
    rt = runtime(cfg)
    context = os.path.join(ENVS_DIR, env_name)
    subprocess.run([rt, "build", "--network", "host", "-t", image(env_name), "-f",
                    os.path.join(context, "Containerfile"), context], check=True, env=runtime_env())
    out = subprocess.run([rt, "image", "inspect", "--format", "{{.Id}}", image(env_name)],
                         capture_output=True, text=True, check=True, env=runtime_env())
    return out.stdout.strip()
