"""Experiments: short shell commands the model runs (run_command_tool) to test
a hypothesis without a full build, in a Docker container of the case's build
environment. They see the workspace, the last build's copy, the caches and the
build environment read-only, write only to a scratch directory, and have no
network."""
import os
import signal
import subprocess
import time

from tools.auto_repair import build_env, container
from tools.auto_repair.case_type import case_environment
from tools.auto_repair.paths import env_dir

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENVS_DIR = os.path.join(ROOT, "envs")
OUTPUT_HEAD, OUTPUT_TAIL = 4000, 16000
MAX_TIMEOUT = 900


def scratch_dir(cfg: dict, package_name: str) -> str:
    return os.path.join(cfg["script"]["stage_root"], package_name, "scratch")


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
    env_name = case_environment(workspace)
    if env_name and os.path.isdir(env_dir(env_name)):
        read_only.append(env_dir(env_name))   # the build environment (make setup-env)
    read_only += [p for p in cfg["script"].get("experiment_paths") or [] if os.path.exists(p)]
    mounts = [(os.path.realpath(p), False) for p in read_only] + [(scratch, True)]
    env = {"BENCH_PACKAGE": package_name, "BENCH_WORKSPACE": workspace, "BENCH_SRC_DIR": src,
           "BENCH_CACHE_DIR": cache, "BENCH_SCRATCH_DIR": scratch, "BENCH_JOBS": str(cfg["script"]["jobs"]),
           "HOME": scratch, "TMPDIR": scratch, "PYTHONDONTWRITEBYTECODE": "1",
           "BENCH_ENV_DIR": env_dir(env_name) if env_name else ""}
    env_script = build_env.env_script(env_name) if env_name else ""
    hide = [os.path.realpath(p) for p in cfg["script"].get("experiment_hide") or [] if os.path.isdir(p)]
    runner = os.path.join(ROOT, "scripts", "script_worker", "run.sh")
    problem = container.check(cfg, env_name)
    if problem:
        return f"Error: commands cannot run: {problem}"
    name = f"bench-{package_name}-exp-{os.getpid()}-{int(time.time() * 1000) % 1000000}"
    argv = container.command(cfg, name, env_name, mounts, env, scratch,
                             ["bash", runner, scratch, env_script, command_file],
                             network="none", drop_capabilities=True, tmpfs=hide)
    started = time.time()
    proc = subprocess.Popen(argv, env=container.runtime_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        status = f"exit status {proc.returncode}"
    except subprocess.TimeoutExpired:
        container.remove(cfg, name)
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        status = f"timed out after {timeout} s (killed)"
    text = out.decode("utf-8", errors="replace").replace(src + "/", workspace.rstrip("/") + "/")
    if len(text) > OUTPUT_HEAD + OUTPUT_TAIL:
        text = text[:OUTPUT_HEAD] + f"\n[... {len(text) - OUTPUT_HEAD - OUTPUT_TAIL} characters cut ...]\n" \
               + text[-OUTPUT_TAIL:]
    return f"Command {status} ({time.time() - started:.0f} s). Output:\n{text}"
