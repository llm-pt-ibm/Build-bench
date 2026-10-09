"""Local build backend: builds packages with `osc build` in a local worker
(scripts/local_worker) instead of OBS, with the same contract as the OBS
functions: the upload stages the sources and starts a build, the check waits
for it and returns the same messages."""
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time

from tools.auto_repair.log_excerpt import error_excerpt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUILD_SCRIPT = os.path.join(ROOT, "scripts", "local_worker", "build.sh")
NOT_SOURCES = {"log_failed.txt", "log_failed_original.txt", "manifest.json", ".last_upload.json"}
# lines of the build itself, timestamped by obs-build
BUILD_LINE = re.compile(r"^\[\s*\d+s\] ")
# osc reports these before the build starts when dependencies cannot be resolved
UNRESOLVABLE = ("unresolvable", "nothing provides", "have choice for", "conflicts with")


def _build_log(text: str) -> str:
    """The build output only, as in an OBS build log: osc prints the package
    downloads before it and its own hints after it."""
    lines = text.splitlines(keepends=True)
    marks = [i for i, line in enumerate(lines) if BUILD_LINE.match(line)]
    return "".join(lines[marks[0]:marks[-1] + 1]) if marks else text


def _source_files(package_dir: str) -> list:
    return sorted(
        f for f in os.listdir(package_dir)
        if os.path.isfile(os.path.join(package_dir, f)) and f not in NOT_SOURCES and not f.startswith(".")
    )


def _run_dir(cfg: dict, package_name: str) -> str:
    path = os.path.join(cfg["local"]["worker_root"], "runs", package_name)
    os.makedirs(path, exist_ok=True)
    return path


def _stop(state_path: str) -> None:
    """Stop the build started by the previous upload, if it is still running."""
    try:
        with open(state_path) as f:
            pgid = json.load(f)["pgid"]
        os.killpg(pgid, signal.SIGTERM)
        time.sleep(5)
        os.killpg(pgid, signal.SIGKILL)
    except (OSError, ValueError, KeyError):
        pass


def local_upload(package_name: str, package_dir: str, cfg: dict) -> str:
    files = _source_files(package_dir)
    if not any(f.endswith(".spec") for f in files):
        return f"Error: no .spec file in {package_dir}"
    local = cfg["local"]
    run = _run_dir(cfg, package_name)
    state_path = os.path.join(run, "state.json")
    _stop(state_path)

    # copy the sources now, so that later edits do not change the running build
    staged = os.path.join(local["worker_root"], "rootfs", "var", "tmp", "bench-src", package_name)
    shutil.rmtree(staged, ignore_errors=True)
    os.makedirs(staged)
    digest = hashlib.md5()
    for name in files:
        shutil.copy2(os.path.join(package_dir, name), staged)
        with open(os.path.join(package_dir, name), "rb") as f:
            digest.update(name.encode() + b"\0" + hashlib.md5(f.read()).digest())
    srcmd5 = digest.hexdigest()

    log, status = os.path.join(run, "build.log"), os.path.join(run, "status")
    for path in (log, status):
        if os.path.exists(path):
            os.remove(path)
    env = dict(os.environ, OBS_WORKER_ROOT=local["worker_root"], LOCAL_BUILD_PROJECT=local["project"],
               LOCAL_BUILD_REPO=local["repository"], LOCAL_BUILD_ARCH=local["arch"])
    proc = subprocess.Popen(
        ["bash", "-c", f'"$0" --staged "$1" "$2" > "$3" 2>&1; echo $? > "$4"',
         BUILD_SCRIPT, package_name, str(local["jobs"]), log, status],
        env=env, start_new_session=True, stdin=subprocess.DEVNULL)
    with open(state_path, "w") as f:
        json.dump({"pgid": proc.pid, "srcmd5": srcmd5, "time": time.time()}, f)
    with open(os.path.join(package_dir, ".last_upload.json"), "w") as f:
        json.dump({"srcmd5": srcmd5, "time": time.time(), "backend": "local"}, f)
    return (f"Success: {len(files)} files staged for a local build against "
            f"{local['project']}/{local['repository']}/{local['arch']} (srcmd5 {srcmd5[:8]}); build started.")


def local_check(temp_dir: str, package_name: str, cfg: dict) -> str:
    marker = os.path.join(temp_dir, ".last_upload.json")
    if not os.path.exists(marker):
        return "Build check error: no upload found in this directory. Call upload_file_to_obs_tool first."
    with open(marker) as f:
        uploaded = json.load(f)
    run = _run_dir(cfg, package_name)
    state_path = os.path.join(run, "state.json")
    try:
        with open(state_path) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    if state.get("srcmd5") != uploaded.get("srcmd5"):
        return "Build check error: no build was started for the last upload. Call upload_file_to_obs_tool again."

    status_path, log_path = os.path.join(run, "status"), os.path.join(run, "build.log")
    deadline = state["time"] + cfg["max_wait_seconds"]
    while not os.path.exists(status_path) and time.time() < deadline:
        time.sleep(min(cfg["check_interval"], 10))
    if not os.path.exists(status_path):
        _stop(state_path)
        return (f"Build timeout! The build has not been completed within {cfg['max_wait_seconds']} seconds. "
                "Default build failed.")
    time.sleep(1)
    with open(status_path) as f:
        code = f.read().strip()
    with open(log_path, "rb") as f:
        log = f.read()
    text = log.decode("utf-8", errors="replace")
    if code == "0":
        return "Build succeeded! The build has been successfully completed."
    if "----- building " not in text and any(s in text for s in UNRESOLVABLE):
        return f"Build unresolvable! The build can not begin: {error_excerpt(text, max_key_lines=10)}"
    text = _build_log(text)
    path = os.path.join(temp_dir, "log_failed.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return (f"Build failed! The failed log has been updated to: {path}\n"
            f"Key lines of the log:\n{error_excerpt(text)}")
