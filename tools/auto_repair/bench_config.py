"""The benchmark's config: bench.yaml (or the file BENCH_CONFIG names). The cases,
acceptance tests, results and logs follow from source_arch and target_arch;
BENCH_OUTPUT_ROOT moves the workspaces, results and logs (the tests use it)."""
import os
import sys

import yaml

from tools.auto_repair.paths import expand

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT = os.path.join(REPO, "bench.yaml")
OLD_SECTIONS = {"paths": "cases come from data/<source>_to_<target>/ (or cases_dir), results go to "
                         "result_text_res/<source>_to_<target>/",
                "user": "the OBS project and repository are in obs (project, repository), the account in .env"}
_warned = set()


def path() -> str:
    return os.getenv("BENCH_CONFIG") or DEFAULT


def load(config_path: str = None) -> dict:
    config_path = config_path or path()
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}
    missing = [k for k in ("source_arch", "target_arch") if not cfg.get(k)]
    if missing:
        sys.exit(f"error: {config_path}: {' and '.join(missing)} not set")
    old = [k for k in OLD_SECTIONS if k in cfg]
    if old and config_path not in _warned:
        _warned.add(config_path)
        for k in old:
            print(f"warning: {config_path}: section {k} is no longer read: {OLD_SECTIONS[k]}", file=sys.stderr)
    return cfg


def direction(cfg: dict) -> str:
    return f"{cfg['source_arch']}_to_{cfg['target_arch']}"


def output_root() -> str:
    return os.path.abspath(expand(os.getenv("BENCH_OUTPUT_ROOT") or REPO))


def run_paths(cfg: dict) -> dict:
    """The cases (base_dir), the package workspaces and the result and log
    directories of a loaded config."""
    out, name = output_root(), direction(cfg)
    cases = os.path.join(REPO, expand(cfg["cases_dir"])) if cfg.get("cases_dir") else os.path.join(REPO, "data", name)
    return {"base_dir": cases,
            "temp_work_dir": os.path.join(out, "temp_workspace"),
            "result_dir": os.path.join(out, "result_text_res", name),
            "log_dir": os.path.join(out, "result_log_res", name)}
