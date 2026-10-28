"""Baseline build of a build-recipe case, without the model: build the case as
it is, in the same workspace path the benchmark uses, and save the failing log
as the case's log_failed.txt (the original failure). It also fills the
persistent build cache, which later builds reuse.
Usage: [BENCH_CONFIG=<config>] python dataset/recipe_baseline.py <case_dir>
       (or: make baseline CASE=<name>)"""
import os
import shutil
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from tools.auto_repair import bench_config  # noqa: E402
from tools.auto_repair.obs_config import load_obs_config  # noqa: E402
from tools.auto_repair.script_build import script_upload, script_check  # noqa: E402


def main(case_dir: str) -> int:
    case_dir = os.path.normpath(case_dir)
    package = os.path.basename(case_dir)
    work = os.path.join(bench_config.run_paths(bench_config.load())["temp_work_dir"], package)
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(case_dir, work, symlinks=True)
    cfg = load_obs_config()
    started = time.time()
    print(script_upload(package, work, cfg), flush=True)
    result = script_check(work, package, cfg)
    print(result.splitlines()[0], f"({(time.time() - started) / 60:.1f} min)")
    print("\n".join(result.splitlines()[1:]))
    if result.startswith("Build failed!"):
        shutil.copy2(os.path.join(work, "log_failed.txt"), os.path.join(case_dir, "log_failed.txt"))
        print(f"saved {case_dir}/log_failed.txt")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
