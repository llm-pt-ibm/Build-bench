"""Acceptance tests: after a successful build the framework checks that the
built software works, with a test the case defines outside the package, in
acceptance/<source>_to_<target>/<package>.sh. The model can read the test
(read-only) but not change it, and a build only counts as successful when its
acceptance test passes.

The test runs on the build host, in the case's build environment, with:
  BENCH_PACKAGE      package name
  BENCH_SRC_DIR      build copy of the package (build-recipe cases; artifacts
                     such as wheels are where build.sh left them)
  BENCH_BUILD_ROOT   build root of an osc build (RPM cases); the built RPMs
                     are in $BENCH_BUILD_ROOT/home/abuild/rpmbuild/RPMS
  BENCH_CACHE_DIR    persistent scratch directory for the test
It passes when it exits with status 0."""
import os
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ACCEPTANCE_DIR = os.path.join(ROOT, "acceptance")
RUNNER = os.path.join(ROOT, "scripts", "script_worker", "run.sh")
OUTPUT_KEPT = 200000


def acceptance_test(cfg: dict, package: str):
    if not cfg.get("direction"):
        return None
    path = os.path.join(ACCEPTANCE_DIR, cfg["direction"], f"{package}.sh")
    return path if os.path.isfile(path) else None


def run_acceptance(test: str, env_script: str, workdir: str, env: dict, timeout: int):
    """Run the test; returns (passed, output)."""
    try:
        proc = subprocess.run(["bash", RUNNER, workdir, env_script or "", test],
                              env=dict(os.environ, **env), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        output = proc.stdout.decode("utf-8", errors="replace")
        passed = proc.returncode == 0
    except subprocess.TimeoutExpired as e:
        output = (e.stdout or b"").decode("utf-8", errors="replace") + f"\nacceptance test timed out after {timeout} s"
        passed = False
    if len(output) > OUTPUT_KEPT:
        output = output[:OUTPUT_KEPT // 4] + "\n...\n" + output[-3 * OUTPUT_KEPT // 4:]
    return passed, output


def failure_message(test: str, log_path: str, excerpt: str) -> str:
    return (f"Build failed! The package was built, but its acceptance test failed: the framework runs "
            f"{os.path.relpath(test, ROOT)} after every successful build to check that the built software "
            f"works (you can read the test but not change it). The failed log has been updated to: {log_path}\n"
            f"Key lines of the log:\n{excerpt}")
