"""Start a build-recipe case: the case directory with a build.sh and a
manifest.json to fill in, and the skeleton of its acceptance test.

Usage: python dataset/new_case.py <data_dir> <name> [environment]
       (or: make new-case CASE=<name> [ENV=<environment>])
RPM packages of openSUSE are fetched instead: dataset/fetch_package.py."""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

BUILD_SH = """#!/bin/bash
# Build recipe for {name}. It runs from the package root on the build host, in
# the build environment the case declares (envs/<environment>.sh, which
# exports the tools), and the build succeeds when it exits with status 0.
#   $BENCH_CACHE_DIR         build state of this run (e.g. a Bazel output root)
#   $BENCH_SHARED_CACHE_DIR  caches later runs can reuse (disk/repository caches)
#   $BENCH_JOBS              number of parallel jobs
# Leave the artifacts (e.g. a wheel) where the acceptance test looks for them.
set -euo pipefail
echo "TODO: build {name}"
exit 1
"""

ACCEPTANCE_SH = """#!/bin/bash
# Acceptance test of {name}: check that the built software installs and works.
# The framework runs it after every successful build, on the build host in the
# case's build environment, with
#   $BENCH_SRC_DIR    the build copy of the package, with the artifacts build.sh left
#   $BENCH_CACHE_DIR  scratch space of the run
#   $BENCH_JOBS       number of parallel jobs
# It passes when it exits with status 0; the model can read it, not change it.
set -euo pipefail
echo "TODO: install the artifacts from $BENCH_SRC_DIR and check that they work"
exit 1
"""


def new_case(data_dir: str, name: str, environment: str = "") -> list:
    direction = os.path.basename(os.path.normpath(data_dir))
    case = os.path.join(data_dir, name)
    if os.path.exists(case):
        raise SystemExit(f"error: {os.path.relpath(case, ROOT)} exists already")
    os.makedirs(case)
    with open(os.path.join(case, "build.sh"), "w") as f:
        f.write(BUILD_SH.format(name=name))
    os.chmod(os.path.join(case, "build.sh"), 0o755)
    manifest = {"task": {"package": name, "version": "TODO", "direction": direction, "type": "recipe",
                         "sources": {name: "TODO: URL of the sources"},
                         "source_build": f"TODO: evidence that {name} builds on {direction.split('_to_')[0]}"},
                "environment": environment or "TODO",
                "fetch": f"dataset/fetch_{name}.sh",
                "version": 1}
    with open(os.path.join(case, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    created = [os.path.join(case, "build.sh"), os.path.join(case, "manifest.json")]
    test = os.path.join(ROOT, "acceptance", direction, f"{name}.sh")
    if not os.path.exists(test):
        os.makedirs(os.path.dirname(test), exist_ok=True)
        with open(test, "w") as f:
            f.write(ACCEPTANCE_SH.format(name=name))
        os.chmod(test, 0o755)
        created.append(test)
    return created


def main() -> None:
    data_dir, name = sys.argv[1], sys.argv[2]
    created = new_case(data_dir, name, sys.argv[3] if len(sys.argv) > 3 else "")
    print("created:\n" + "\n".join(f"  {os.path.relpath(p, ROOT)}" for p in created))
    print(f"""
next steps:
  1. put the sources next to build.sh (large trees: a dataset/fetch_{name}.sh that
     downloads them, and the directories in .gitignore)
  2. write build.sh and set "environment" in manifest.json (envs/<environment>.sh;
     the paths it uses go in script.experiment_paths of the config)
  3. save the original failure: BENCH_CONFIG=<config> python dataset/recipe_baseline.py {os.path.relpath(os.path.join(data_dir, name), ROOT)}
  4. write the acceptance test
  5. make check-case CASE={name}""")


if __name__ == "__main__":
    main()
