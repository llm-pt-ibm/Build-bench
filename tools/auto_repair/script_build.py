"""Build-recipe backend: builds cases that ship a build.sh (any build system:
Bazel, CMake, Cargo, pip...) on this host, with the same contract as the OBS
functions: the upload snapshots the sources and starts the recipe, the check
waits for it and returns the same messages.

Each package gets a stable directory <stage_root>/<package>:
  src/    mirror of the package sources (only changed files are copied, so
          incremental build systems and their caches keep working)
  cache/  build state kept across the builds of a run (BENCH_CACHE_DIR), e.g.
          a Bazel output root; it is cleared when a run starts, so that what
          one run breaks (say, a build.sh that deletes part of it) does not
          reach the next
  shared/ content-addressed caches kept across runs (BENCH_SHARED_CACHE_DIR),
          e.g. Bazel's --disk_cache and --repository_cache or ccache: losing
          an entry only costs time, so they are safe to share
Paths of src/ in the log are rewritten to the package workspace, so the model
can open the files the errors point to; cache/ is readable by the file tools
(dependency sources downloaded by the build live there)."""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time

from tools.auto_repair import container
from tools.auto_repair.acceptance import acceptance_test, failure_message, run_acceptance
from tools.auto_repair.case_type import case_environment
from tools.auto_repair.infra import infra_failure, retry_or_give_up
from tools.auto_repair.local_build import _stop
from tools.auto_repair.log_excerpt import error_excerpt
from tools.auto_repair.paths import env_dir

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUNNER = os.path.join(ROOT, "scripts", "script_worker", "run.sh")
ENVS_DIR = os.path.join(ROOT, "envs")
NOT_SOURCES = {"log_failed.txt", "log_failed_original.txt", "manifest.json", "extracted"}


def _dirs(cfg: dict, package_name: str) -> dict:
    base = os.path.join(cfg["script"]["stage_root"], package_name)
    dirs = {"base": base, "src": os.path.join(base, "src"), "cache": os.path.join(base, "cache"),
            "shared": os.path.join(base, "shared"), "run": os.path.join(base, "run")}
    for name in ("src", "cache", "shared", "run"):
        os.makedirs(dirs[name], exist_ok=True)
    return dirs


def _same(a: os.stat_result, b: os.stat_result) -> bool:
    return a.st_size == b.st_size and int(a.st_mtime) == int(b.st_mtime)


def sync_tree(src: str, dst: str) -> str:
    """Mirror src into dst, copying only new or changed files (by size and
    mtime) and removing what src no longer has. At the top level, the
    benchmark's own files, extracted/ and hidden files are not sources.
    Returns a digest of the mirrored file list."""
    keep, digest = set(), hashlib.md5()
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        if rel == ".":
            dirs[:] = [d for d in dirs if d not in NOT_SOURCES and not d.startswith(".")]
            files = [f for f in files if f not in NOT_SOURCES and not f.startswith(".")]
        dirs.sort()
        target_dir = os.path.normpath(os.path.join(dst, rel))
        if os.path.islink(target_dir) or (os.path.exists(target_dir) and not os.path.isdir(target_dir)):
            os.remove(target_dir)
        os.makedirs(target_dir, exist_ok=True)
        keep.add(os.path.normpath(rel))
        for name in sorted(files) + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
            s, d = os.path.join(root, name), os.path.join(target_dir, name)
            relname = os.path.normpath(os.path.join(rel, name))
            keep.add(relname)
            st = os.lstat(s)
            digest.update(f"{relname}\0{st.st_size}\0{int(st.st_mtime)}\n".encode())
            if os.path.islink(s):
                link = os.readlink(s)
                if not (os.path.islink(d) and os.readlink(d) == link):
                    if os.path.lexists(d):
                        shutil.rmtree(d) if os.path.isdir(d) and not os.path.islink(d) else os.remove(d)
                    os.symlink(link, d)
                continue
            if os.path.lexists(d):
                if os.path.isdir(d) and not os.path.islink(d):
                    shutil.rmtree(d)
                elif _same(st, os.lstat(d)):
                    continue
            shutil.copy2(s, d)
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
    # remove what is not in the sources any more (including build outputs left in src/)
    for root, dirs, files in os.walk(dst, topdown=False):
        rel = os.path.relpath(root, dst)
        for name in files + dirs:
            relname = os.path.normpath(os.path.join(rel, name))
            path = os.path.join(root, name)
            if relname not in keep:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path, ignore_errors=True)
                elif os.path.lexists(path):
                    os.remove(path)
    return digest.hexdigest()


def reset_cache(package_name: str, cfg: dict) -> None:
    """Clear the package's per-run build cache (not the shared one), after
    stopping its build and every process that still uses the cache (e.g. a
    Bazel server) or the scratch directory of run_command_tool, with
    everything they started."""
    dirs = _dirs(cfg, package_name)
    _stop(os.path.join(dirs["run"], "state.json"))
    container.remove_matching(cfg, f"bench-{package_name}-")
    cache, scratch = dirs["cache"], os.path.join(dirs["base"], "scratch")
    kill_users(cache)
    kill_users(scratch)
    time.sleep(2)
    shutil.rmtree(cache, ignore_errors=True)
    os.makedirs(cache, exist_ok=True)
    # the scratch directory of run_command_tool belongs to the run as well
    shutil.rmtree(scratch, ignore_errors=True)


def stop_experiments(package_name: str, cfg: dict) -> None:
    """Stop the commands of run_command_tool still running for the package
    (each runs in a container, or a sandbox, and a session of its own)."""
    container.remove_matching(cfg, f"bench-{package_name}-exp")
    kill_users(os.path.join(cfg["script"]["stage_root"], package_name, "scratch"))


def kill_users(path: str) -> None:
    """Kill the processes whose command line mentions path, with everything
    they started, except this process and the ones that started it."""
    users, children, parent = set(), {}, {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmdline = f.read().decode(errors="replace")
            with open(f"/proc/{pid}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(ppid, []).append(int(pid))
        parent[int(pid)] = ppid
        if path in cmdline:
            users.add(int(pid))
    # never this process or the ones that started it (whose command line may
    # mention the path too)
    spared, pid = set(), os.getpid()
    while pid > 1 and pid not in spared:
        spared.add(pid)
        pid = parent.get(pid, 1)
    # the processes that use the path and everything they started
    todo, victims = list(users - spared), set()
    while todo:
        pid = todo.pop()
        if pid not in victims and pid not in spared:
            victims.add(pid)
            todo.extend(children.get(pid, []))
    for pid in victims:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def script_upload(package_name: str, package_dir: str, cfg: dict) -> str:
    if not os.path.isfile(os.path.join(package_dir, "build.sh")):
        return f"Error: no build.sh in {package_dir}"
    env_name = case_environment(package_dir)
    env_script = os.path.join(ENVS_DIR, f"{env_name}.sh") if env_name else ""
    if env_script and not os.path.isfile(env_script):
        return f"Error: build environment '{env_name}' not found ({env_script})"
    problem = container.check(cfg, env_name)
    if problem:
        return f"Error: the build host cannot run the build: {problem}"
    dirs = _dirs(cfg, package_name)
    state_path = os.path.join(dirs["run"], "state.json")
    _stop(state_path)
    name = f"bench-{package_name}-build"
    container.remove(cfg, name)
    srcmd5 = sync_tree(package_dir, dirs["src"])

    log, status = os.path.join(dirs["run"], "build.log"), os.path.join(dirs["run"], "status")
    for path in (log, status):
        if os.path.exists(path):
            os.remove(path)
    bench_env = {"BENCH_CACHE_DIR": dirs["cache"], "BENCH_SHARED_CACHE_DIR": dirs["shared"],
                 "BENCH_JOBS": str(cfg["script"]["jobs"]), "BENCH_PACKAGE": package_name,
                 "BENCH_ENV_DIR": env_dir(env_name) if env_name else ""}
    argv = ["bash", RUNNER, dirs["src"], env_script]
    if container.runtime(cfg):
        # only the build copy, its caches and the build environment are there,
        # and the network through the proxy (or as build_network says)
        net = container.build_network(cfg, env_name, dirs["run"])
        argv = net["wrapper"] + container.command(
            cfg, name, env_name,
            [(dirs["src"], True), (dirs["cache"], True), (dirs["shared"], True)]
            + container.framework_mounts(env_name) + net["mounts"],
            dict(bench_env, **net["env"]), dirs["src"], argv, network=net["network"])
        env = container.runtime_env()
    else:
        env = dict(os.environ, **bench_env)
    proc = subprocess.Popen(
        ["bash", "-c", 'log=$1 status=$2; shift 2; "$@" > "$log" 2>&1; echo $? > "$status"', "build",
         log, status, *argv],
        env=env, start_new_session=True, stdin=subprocess.DEVNULL)
    with open(state_path, "w") as f:
        json.dump({"pgid": proc.pid, "srcmd5": srcmd5, "time": time.time(),
                   "container": name if container.runtime(cfg) else None}, f)
    with open(os.path.join(package_dir, ".last_upload.json"), "w") as f:
        json.dump({"srcmd5": srcmd5, "time": time.time(), "backend": "script"}, f)
    return (f"Success: sources snapshotted for a build on the {cfg['local']['arch']} build host"
            f"{f' (environment {env_name})' if env_name else ''} (srcmd5 {srcmd5[:8]}); build started.")


def script_check(temp_dir: str, package_name: str, cfg: dict, _retry: int = 0) -> str:
    marker = os.path.join(temp_dir, ".last_upload.json")
    if not os.path.exists(marker):
        return "Build check error: no upload found in this directory. Call upload_file_to_obs_tool first."
    with open(marker) as f:
        uploaded = json.load(f)
    dirs = _dirs(cfg, package_name)
    state_path = os.path.join(dirs["run"], "state.json")
    try:
        with open(state_path) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    if state.get("srcmd5") != uploaded.get("srcmd5"):
        return "Build check error: no build was started for the last upload. Call upload_file_to_obs_tool again."

    status_path, log_path = os.path.join(dirs["run"], "status"), os.path.join(dirs["run"], "build.log")
    deadline = state["time"] + cfg["max_wait_seconds"]
    while not os.path.exists(status_path) and time.time() < deadline:
        time.sleep(min(cfg["check_interval"], 10))
    if not os.path.exists(status_path):
        _stop(state_path)
        container.remove(cfg, f"bench-{package_name}-build")
        return (f"Build timeout! The build has not been completed within {cfg['max_wait_seconds']} seconds. "
                "Default build failed.")
    time.sleep(1)
    with open(status_path) as f:
        code = f.read().strip()
    workspace = temp_dir.rstrip("/")

    def to_workspace(text):
        # paths of the build copy -> paths in the package workspace
        return text.replace(dirs["src"] + "/", workspace + "/").replace(dirs["src"], workspace)

    path = os.path.join(temp_dir, "log_failed.txt")
    if code == "0":
        test = acceptance_test(cfg, package_name)
        if not test:
            return "Build succeeded! The build has been successfully completed."
        env_name = case_environment(temp_dir)
        # in a container: the build copy (the test may build in it), the
        # cache, the acceptance tests and the build environment, no network
        in_container = None
        if container.runtime(cfg):
            in_container = {"cfg": cfg, "name": f"bench-{package_name}-test", "env_name": env_name,
                            "mounts": [(dirs["src"], True), (dirs["cache"], True),
                                       (os.path.join(ROOT, "acceptance"), False)]
                                      + container.framework_mounts(env_name)}
        passed, output = run_acceptance(
            test, os.path.join(ENVS_DIR, f"{env_name}.sh") if env_name else "", dirs["src"],
            {"BENCH_PACKAGE": package_name, "BENCH_SRC_DIR": dirs["src"], "BENCH_CACHE_DIR": dirs["cache"],
             "BENCH_JOBS": str(cfg["script"]["jobs"]), "BENCH_ENV_DIR": env_dir(env_name) if env_name else ""},
            cfg["acceptance_timeout"], in_container)
        with open(os.path.join(dirs["run"], "acceptance.log"), "w", encoding="utf-8") as f:
            f.write(output)
        if passed:
            return "Build succeeded! The build has been successfully completed and its acceptance test passed."
        output = to_workspace(output)
        with open(path, "w", encoding="utf-8") as f:
            f.write("=== the build succeeded; output of the acceptance test:\n" + output)
        return failure_message(test, path, error_excerpt(output))
    with open(log_path, "rb") as f:
        text = to_workspace(f.read().decode("utf-8", errors="replace"))
    infra = infra_failure(text)
    if infra:
        message = retry_or_give_up(_retry, infra, lambda: script_upload(package_name, temp_dir, cfg))
        return message or script_check(temp_dir, package_name, cfg, _retry + 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return (f"Build failed! The failed log has been updated to: {path}\n"
            f"Key lines of the log:\n{error_excerpt(text)}" + _refused_note(cfg, temp_dir, dirs["run"]))


def _refused_note(cfg: dict, workspace: str, run_dir: str) -> str:
    """Tell the model when the build was refused a host (build_network proxy)."""
    refused = container.network_log(run_dir)["refused"]
    if not refused:
        return ""
    allowed = container.allowed_hosts(cfg, case_environment(workspace))
    return (f"\nNetwork: builds reach the network only through the build host's proxy, which refused "
            f"{', '.join(refused)}; it allows {', '.join(allowed) or 'no host'}. Use what these hosts "
            "provide (or the build cache) instead.")
