"""Where the benchmark keeps its state on the build host: BENCH_HOME (default
~/.local/share/build-bench) holds the build environments (envs/), the build
directories of recipe cases (stage/) and the local osc worker (obs-worker/).
Paths in a config may use ~ and ${VARIABLES}."""
import os


def bench_home() -> str:
    return os.path.abspath(os.path.expanduser(os.getenv("BENCH_HOME") or "~/.local/share/build-bench"))


def expand(path: str) -> str:
    """~ and ${VARIABLES} of a config path, BENCH_HOME always defined."""
    if not path:
        return path
    os.environ.setdefault("BENCH_HOME", bench_home())
    return os.path.expanduser(os.path.expandvars(str(path)))


def env_dir(name: str) -> str:
    """The prefix of build environment `name` (made from envs/<name>/env.yaml)."""
    return os.path.join(bench_home(), "envs", name)


def build_dirs(build_cfg: dict) -> dict:
    """worker_root and stage_root from a config's `build` section."""
    build_cfg = build_cfg or {}
    local, script = build_cfg.get("local") or {}, build_cfg.get("script") or {}
    return {
        "worker_root": expand(os.getenv("OBS_WORKER_ROOT") or local.get("worker_root")
                              or os.path.join(bench_home(), "obs-worker")),
        "stage_root": expand(os.getenv("BENCH_STAGE_ROOT") or script.get("stage_root")
                             or os.path.join(bench_home(), "stage")),
    }
