import os
from dotenv import load_dotenv

from tools.auto_repair import bench_config, container
from tools.auto_repair.paths import build_dirs, expand

load_dotenv(".env")
# the openSUSE:Factory port local builds resolve dependencies against, per
# target architecture (build.local.project overrides it)
FACTORY = {"x86_64": "openSUSE:Factory", "i586": "openSUSE:Factory", "ppc64le": "openSUSE:Factory:PowerPC",
           "aarch64": "openSUSE:Factory:ARM", "armv7l": "openSUSE:Factory:ARM",
           "s390x": "openSUSE:Factory:zSystems", "riscv64": "openSUSE:Factory:RISCV"}


def _auto_jobs(gb_per_job: int = 5) -> int:
    """One job per gb_per_job GB of available memory, at most the number of CPUs."""
    try:
        with open("/proc/meminfo") as f:
            kb = next(int(l.split()[1]) for l in f if l.startswith("MemAvailable"))
        return max(1, min(os.cpu_count() or 1, kb // (gb_per_job * 1024 * 1024)))
    except (OSError, StopIteration, ValueError):
        return os.cpu_count() or 1


def load_obs_config() -> dict:
    info = bench_config.load()
    target = info["target_arch"]
    obs = info.get("obs") or {}
    build = info.get("build") or {}
    local = build.get("local") or {}
    script = build.get("script") or {}
    dirs = build_dirs(build)   # BENCH_HOME based unless the config says otherwise
    name = os.getenv("OBS_USER")
    return {
        "api": str(obs.get("api_url") or "https://api.opensuse.org").rstrip("/"),
        "user": name,
        "password": os.getenv("OBS_PASSWORD"),
        "project": str(obs.get("project") or "home:{user}:build-bench").format(user=name),
        # dataset/setup_obs.py names the repository after the target
        "repository": obs.get("repository") or target,
        "arch": target,
        "max_wait_seconds": int(obs.get("max_wait_seconds", 3600)),
        "check_interval": int(obs.get("check_interval", 30)),
        "direction": bench_config.direction(info),
        "acceptance_timeout": int((info.get("acceptance") or {}).get("timeout_seconds", 3600)),
        "backend": (os.getenv("BENCH_BUILD_BACKEND") or build.get("backend", "obs")).lower(),
        "local": {
            "worker_root": dirs["worker_root"],
            "project": local.get("project") or FACTORY.get(target, "openSUSE:Factory"),
            "repository": local.get("repository", "standard"),
            "arch": local.get("arch", target),
            "jobs": int(local.get("jobs", 0)),
        },
        "container": container.settings(build),
        "script": {
            "stage_root": dirs["stage_root"],
            "jobs": int(script.get("jobs", 0)) or _auto_jobs(),
            "experiment_paths": [expand(p) for p in script.get("experiment_paths") or []],
            "experiment_hide": [expand(p) for p in script.get("experiment_hide") or []],
        },
    }
