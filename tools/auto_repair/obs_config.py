import os
import yaml
from dotenv import load_dotenv

from tools.auto_repair.paths import build_dirs, expand

load_dotenv(".env")


def _auto_jobs(gb_per_job: int = 5) -> int:
    """One job per gb_per_job GB of available memory, at most the number of CPUs."""
    try:
        with open("/proc/meminfo") as f:
            kb = next(int(l.split()[1]) for l in f if l.startswith("MemAvailable"))
        return max(1, min(os.cpu_count() or 1, kb // (gb_per_job * 1024 * 1024)))
    except (OSError, StopIteration, ValueError):
        return os.cpu_count() or 1


def load_obs_config() -> dict:
    with open(os.getenv("BENCH_CONFIG", "config/info.yaml"), "r") as f:
        info = yaml.safe_load(f)
    user = info["user"]
    build = info.get("build") or {}
    local = build.get("local") or {}
    script = build.get("script") or {}
    dirs = build_dirs(build)   # BENCH_HOME based unless the config says otherwise
    name = os.getenv("OBS_USER") or user.get("user_name")
    return {
        "api": user["obs_api_url"].rstrip("/"),
        "user": name,
        "password": os.getenv("OBS_PASSWORD") or user.get("password"),
        "project": user["target_project"].format(user=name),
        "repository": user["repository_name"],
        "arch": user["architecture_name"],
        "max_wait_seconds": int(info.get("obs", {}).get("max_wait_seconds", 3600)),
        "check_interval": int(info.get("obs", {}).get("check_interval", 30)),
        "direction": f"{info.get('source_arch', 'x86_64')}_to_{info.get('target_arch', 'ppc64le')}",
        "acceptance_timeout": int((info.get("acceptance") or {}).get("timeout_seconds", 3600)),
        # "obs" builds on OBS; "local" builds with osc in the local worker
        # (scripts/local_worker), see tools/auto_repair/local_build.py
        "backend": (os.getenv("BENCH_BUILD_BACKEND") or build.get("backend", "obs")).lower(),
        "local": {
            "worker_root": dirs["worker_root"],
            "project": local.get("project", "openSUSE:Factory:PowerPC"),
            "repository": local.get("repository", "standard"),
            "arch": local.get("arch", user["architecture_name"]),
            "jobs": int(local.get("jobs", 0)),
        },
        # build-recipe cases (build.sh), see tools/auto_repair/script_build.py
        "script": {
            "stage_root": dirs["stage_root"],
            "jobs": int(script.get("jobs", 0)) or _auto_jobs(),
            # paths the build environment needs, shown read-only to the
            # sandbox of run_command_tool (tools/auto_repair/experiment.py)
            "experiment_paths": [expand(p) for p in script.get("experiment_paths") or []],
            # directories inside them that stay hidden there
            "experiment_hide": [expand(p) for p in script.get("experiment_hide") or []],
        },
    }
