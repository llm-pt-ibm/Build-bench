"""Validate that a build-recipe case is solvable through the framework: apply a
reference fix (known patches) to a copy of the case and build it with the
same backend the model uses (upload_file_to_obs_tool/check_build_result).
Success shows that the environment, recipe and check work end to end and that
the fix only needs changes inside the package, which the model's tools can do.
Usage: BENCH_CONFIG=<config> python dataset/recipe_reference_fix.py \\
           <case_dir> <name> <subdir>:<patch> [<subdir>:<patch> ...]
  name           package name of the copy (its own build directory and cache)
  subdir:patch   apply patch with `patch -p1` inside <copy>/<subdir>"""
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import yaml  # noqa: E402
from tools.auto_repair.obs_config import load_obs_config  # noqa: E402
from tools.auto_repair.script_build import script_upload, script_check  # noqa: E402


def main(case_dir: str, name: str, patches: list) -> int:
    with open(os.getenv("BENCH_CONFIG", "config/info.yaml")) as f:
        work = os.path.join(yaml.safe_load(f)["paths"]["temp_work_dir"], name)
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(os.path.normpath(case_dir), work, symlinks=True)
    for spec in patches:
        subdir, patch = spec.split(":", 1)
        with open(patch) as f:
            proc = subprocess.run(["patch", "-p1", "--fuzz=0", "-d", os.path.join(work, subdir)],
                                  stdin=f, capture_output=True, text=True)
        print(f"{os.path.basename(patch)} -> {subdir}: {'ok' if proc.returncode == 0 else 'FAILED'}")
        if proc.returncode != 0:
            print(proc.stdout + proc.stderr)
            return 2
    cfg = load_obs_config()
    started = time.time()
    print(script_upload(name, work, cfg), flush=True)
    result = script_check(work, name, cfg)
    print(result.splitlines()[0], f"({(time.time() - started) / 60:.1f} min)")
    print("\n".join(result.splitlines()[1:]))
    return 0 if result.startswith("Build succeeded!") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3:]))
