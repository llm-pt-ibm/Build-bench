"""Check a benchmark case before running it: that it has what the framework
needs for its type and nothing that gives the answer away.

Usage: BENCH_CONFIG=<config> python dataset/check_case.py <case_dir>
       (or: make check-case CASE=<name>)
Prints one line per check (OK, WARN, FAIL) and exits with 1 when one fails."""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from tools.auto_repair.case_type import case_type  # noqa: E402
from tools.auto_repair.leak_check import leak_report  # noqa: E402

METADATA = {"build.sh", "manifest.json", "log_failed.txt", "log_failed_original.txt", ".last_upload.json"}
# what an OBS log shows when the build never ran for reasons of its own
NOT_A_BUILD_FAILURE = ("unresolvable", "nothing provides", "no compliant workers")


def check_case(case_dir: str, cfg: dict) -> list:
    """[(level, message)] with level OK, WARN or FAIL."""
    results = []

    def add(level, message):
        results.append((level, message))

    case_dir = os.path.normpath(case_dir)
    name, direction = os.path.basename(case_dir), os.path.basename(os.path.dirname(case_dir))
    if not os.path.isdir(case_dir):
        return [("FAIL", f"no case directory {case_dir}")]
    entries = set(os.listdir(case_dir))
    kind = case_type(case_dir)
    add("OK", f"case {name} ({direction}), {'build recipe (build.sh)' if kind == 'recipe' else 'RPM package (.spec)'}")

    manifest = {}
    if "manifest.json" not in entries:
        add("WARN", "no manifest.json: nothing records where the case comes from")
    else:
        try:
            with open(os.path.join(case_dir, "manifest.json")) as f:
                manifest = json.load(f)
            task = manifest.get("task") or {}
            if task.get("package") not in (None, name):
                add("WARN", f"manifest.json names package {task.get('package')!r}, the directory is {name!r}")
            if task.get("direction") not in (None, direction):
                add("WARN", f"manifest.json says direction {task.get('direction')!r}, the directory is in {direction!r}")
            add("OK", "manifest.json")
        except ValueError as e:
            add("FAIL", f"manifest.json is not valid JSON: {e}")

    if kind == "recipe":
        env = manifest.get("environment")
        if not env:
            add("WARN", "manifest.json has no environment: build.sh runs without a build environment (envs/)")
        elif not os.path.isfile(os.path.join(ROOT, "envs", f"{env}.sh")):
            add("FAIL", f"build environment envs/{env}.sh not found")
        else:
            add("OK", f"build environment envs/{env}.sh")
        sources = sorted(entries - METADATA - {"extracted"})
        if sources:
            add("OK", f"sources: {', '.join(sources[:6])}{' ...' if len(sources) > 6 else ''}")
        else:
            fetch = manifest.get("fetch")
            add("FAIL", "no sources next to build.sh" + (f": run {fetch}" if fetch else ""))
        with open(os.path.join(case_dir, "build.sh"), errors="replace") as f:
            if "TODO" in f.read():
                add("WARN", "build.sh still has TODOs (template of make new-case)")
    else:
        specs = [e for e in entries if e.endswith(".spec")]
        add("OK" if len(specs) == 1 else "WARN", f"spec file(s): {', '.join(specs)}")
        missing = [f["name"] for f in manifest.get("files") or [] if f.get("name") not in entries]
        if missing:
            add("FAIL", f"files listed in manifest.json are missing: {', '.join(missing)}")

    log = os.path.join(case_dir, "log_failed.txt")
    if not os.path.isfile(log) or os.path.getsize(log) == 0:
        hint = ("dataset/recipe_baseline.py builds the case and saves it" if kind == "recipe"
                else "dataset/fetch_package.py downloads it from OBS")
        add("FAIL", f"no log_failed.txt (the original failure): {hint}")
    else:
        with open(log, errors="replace") as f:
            text = f.read()
        lower = text[-20000:].lower()
        reasons = [r for r in NOT_A_BUILD_FAILURE if r in lower] if kind == "rpm" else []
        if len(text) < 500 or reasons:
            add("WARN", "log_failed.txt may not be a build failure"
                + (f" ({', '.join(reasons)})" if reasons else f" (only {len(text)} characters)"))
        else:
            add("OK", f"log_failed.txt ({len(text) // 1024} KiB)")

    left = sorted(entries & {"log_failed_original.txt", ".last_upload.json", "extracted"})
    if left:
        add("WARN", f"files the framework creates in the workspace are in the case: {', '.join(left)}")

    test = os.path.join(ROOT, "acceptance", direction, f"{name}.sh")
    if os.path.isfile(test):
        with open(test, errors="replace") as f:
            todo = "TODO" in f.read()
        add("WARN" if todo else "OK",
            f"acceptance test {os.path.relpath(test, ROOT)}" + (" still has TODOs" if todo else ""))
    else:
        add("WARN", f"no acceptance test ({os.path.relpath(test, ROOT)}): a build that finishes counts as a success")

    for line in leak_report(cfg, name, case_dir):
        add("FAIL", f"leak: {line}")
    if not any(m.startswith("leak:") for _, m in results):
        add("OK", "leak check: no built copy and no reference fix within the model's reach")
    return results


def main() -> int:
    from tools.auto_repair.obs_config import load_obs_config
    results = check_case(sys.argv[1], load_obs_config())
    for level, message in results:
        print(f"{level:<4}  {message}")
    failed = sum(level == "FAIL" for level, _ in results)
    print(f"\n{'FAILED: ' + str(failed) + ' check(s)' if failed else 'ready to run'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
