"""Where the benchmark keeps its state on the build host.

BENCH_HOME (default ~/.local/share/build-bench) holds what is not in the
repository: the build environments of build-recipe cases (envs/<name>, made
by `make setup-env`), the build directories of build-recipe cases (stage/)
and the local osc worker (obs-worker/). A config can place any of them
elsewhere (build.script.stage_root, build.local.worker_root); paths in a
config may use ~ and ${VARIABLES}, BENCH_HOME included.

Nothing here needs root: the default is in the user's home."""
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
    """The prefix of build environment `name` (envs/<name>.sh exports from it)."""
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
