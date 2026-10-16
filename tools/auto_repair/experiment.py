"""Experiments: short shell commands the model runs on the build host, in the
case's build environment, to test a hypothesis without a full build (run one
test of the built software, compile a small program, inspect an artifact).

Only for build-recipe cases. Each command runs in its own sandbox (Linux
namespaces, so the build host must allow unshare and mounts, as the Power9
container does):
  - /root, /tmp, /var/tmp and /dev/shm are hidden: other builds, earlier runs
    and the framework's own files cannot be read;
  - visible again, read-only: the package workspace, the last build's copy
    (BENCH_SRC_DIR), the package's build cache (BENCH_CACHE_DIR), the
    acceptance tests, the build environments and the paths the build host
    needs (script.experiment_paths in the config);
  - writable: a scratch directory kept for the run (BENCH_SCRATCH_DIR, the
    working directory), so that files are only changed with the edit tools;
  - no network, no other processes, no capabilities (the sandbox cannot be
    undone from inside).
"""
import os
import shlex
import signal
import subprocess
import time

from tools.auto_repair.case_type import case_environment

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENVS_DIR = os.path.join(ROOT, "envs")
HIDDEN = ("/root", "/tmp", "/var/tmp", "/dev/shm")
OUTPUT_HEAD, OUTPUT_TAIL = 4000, 16000
MAX_TIMEOUT = 900


def scratch_dir(cfg: dict, package_name: str) -> str:
    return os.path.join(cfg["script"]["stage_root"], package_name, "scratch")


def _sandbox_script(mounts: list, scratch: str, command_file: str, env_script: str, env: dict) -> str:
    """Bash run as root in new mount/net/pid namespaces: hide HIDDEN, mount
    back the (path, writable) pairs of mounts, drop the capabilities and run
    the command in the build environment."""
    q = shlex.quote
    lines = ["set -e", "mkdir -p /run/bench-exp && mount -t tmpfs tmpfs /run/bench-exp"]
    for i, (path, _) in enumerate(mounts):
        lines.append(f"mkdir /run/bench-exp/{i} && mount --bind {q(path)} /run/bench-exp/{i}")
    lines += [f"mount -t tmpfs tmpfs {d}" for d in HIDDEN if os.path.isdir(d)]
    for i, (path, writable) in enumerate(mounts):
        lines.append(f"mkdir -p {q(path)} && mount --move /run/bench-exp/{i} {q(path)}")
        if not writable:
            lines.append(f"mount -o remount,bind,ro {q(path)}")
    lines.append("umount /run/bench-exp")
    exports = " ".join(f"{k}={q(v)}" for k, v in env.items())
    runner = os.path.join(ROOT, "scripts", "script_worker", "run.sh")
    lines.append(f"cd {q(scratch)} && exec setpriv --no-new-privs --inh-caps=-all --bounding-set=-all "
                 f"env {exports} bash {q(runner)} {q(scratch)} {q(env_script)} {q(command_file)}")
    return "\n".join(lines) + "\n"


def run_experiment(package_name: str, workspace: str, command: str, timeout: int, cfg: dict) -> str:
    stage = os.path.join(cfg["script"]["stage_root"], package_name)
    src, cache, scratch = (os.path.join(stage, d) for d in ("src", "cache", "scratch"))
    for d in (src, cache, scratch):
        os.makedirs(d, exist_ok=True)
    timeout = max(1, min(int(timeout), MAX_TIMEOUT))
    command_file = os.path.join(scratch, ".command.sh")
    with open(command_file, "w") as f:
        f.write(command + "\n")
    read_only = [workspace, src, cache, ENVS_DIR, os.path.join(ROOT, "acceptance"),
                 os.path.join(ROOT, "scripts", "script_worker")]
    read_only += [p for p in cfg["script"].get("experiment_paths") or [] if os.path.exists(p)]
    mounts = [(os.path.realpath(p), False) for p in read_only] + [(scratch, True)]
    env = {"BENCH_PACKAGE": package_name, "BENCH_WORKSPACE": workspace, "BENCH_SRC_DIR": src,
           "BENCH_CACHE_DIR": cache, "BENCH_SCRATCH_DIR": scratch, "BENCH_JOBS": str(cfg["script"]["jobs"]),
           "HOME": scratch, "TMPDIR": scratch, "PYTHONDONTWRITEBYTECODE": "1"}
    env_name = case_environment(workspace)
    env_script = os.path.join(ENVS_DIR, f"{env_name}.sh") if env_name else ""
    script = _sandbox_script(mounts, scratch, command_file, env_script, env)
    started = time.time()
    proc = subprocess.Popen(["unshare", "--mount", "--net", "--pid", "--fork", "--mount-proc",
                             "--propagation", "private", "bash", "-c", script],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        status = f"exit status {proc.returncode}"
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        status = f"timed out after {timeout} s (killed)"
    text = out.decode("utf-8", errors="replace").replace(src + "/", workspace.rstrip("/") + "/")
    if len(text) > OUTPUT_HEAD + OUTPUT_TAIL:
        text = text[:OUTPUT_HEAD] + f"\n[... {len(text) - OUTPUT_HEAD - OUTPUT_TAIL} characters cut ...]\n" \
               + text[-OUTPUT_TAIL:]
    return f"Command {status} ({time.time() - started:.0f} s). Output:\n{text}"
