"""Live view of a benchmark run: attempt, round, edits, builds, context size
and cost, refreshed every few seconds.
Usage: python scripts/watch_run.py [config] [package] [seconds]
  (defaults: config/x86_64_to_ppc64le_power9.yaml, the package of the newest
  log, 10 s; 0 s prints the view once). Works through the sshfs mount too;
  Ctrl-C stops it.
The cost comes from <package>_status.json, written by client.py after every
model call; for runs started before that existed it falls back to the
OpenRouter key's spend today (usage_daily), which includes any other use of
the key."""
import glob
import json
import os
import re
import sys
import time
import urllib.request

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CALL = re.compile(r"^\[(.{19})\] Tool call: (\w+)\((.*)\)$")


def env_value(name):
    try:
        for line in open(os.path.join(ROOT, ".env")):
            k, _, v = line.strip().partition("=")
            if k.strip() == name:
                return v.split(" #")[0].strip().strip("'\"")
    except OSError:
        pass
    return None


def key_spend_today():
    key, base = env_value("API_KEY"), env_value("API_BASE_URL") or ""
    if not key or "openrouter" not in base:
        return None
    try:
        req = urllib.request.Request(base.rstrip("/") + "/key", headers={"Authorization": f"Bearer {key}"})
        return json.load(urllib.request.urlopen(req, timeout=15))["data"].get("usage_daily")
    except Exception:
        return None


PROGRESS = re.compile(r"\[([\d,]+) / ([\d,]+)\](.*)")


def host_path(path):
    """A path of the build host, also when watching through the sshfs mount
    (this repository is /root/build-bench there)."""
    if os.path.exists(path) or not path.startswith("/root/"):
        return path
    return os.path.join(os.path.dirname(ROOT), path[len("/root/"):])


def tail_text(path, size=65536):
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - size))
        return f.read().decode("utf-8", errors="replace")


def build_status(cfg, package):
    # files of the build directory change under our feet (a new upload
    # removes them), so a failed read just means "try again next refresh"
    try:
        return _build_status(cfg, package)
    except (OSError, ValueError) as e:
        return f"unavailable ({e.__class__.__name__}), retrying"


def _build_status(cfg, package):
    """State of the package's current build: running (with progress) or finished."""
    build = cfg.get("build") or {}
    candidates = [os.path.join((build.get("script") or {}).get("stage_root", "/root/obs-worker/script"), package, "run"),
                  os.path.join((build.get("local") or {}).get("worker_root", "/root/obs-worker"), "runs", package)]
    for run in map(host_path, candidates):
        log = os.path.join(run, "build.log")
        if not os.path.exists(log):
            continue
        try:
            with open(os.path.join(run, "state.json")) as f:
                started = json.load(f)["time"]
        except (OSError, ValueError, KeyError):
            started = os.path.getmtime(log)
        status_file = os.path.join(run, "status")
        if os.path.exists(status_file):
            with open(status_file) as f:
                code = f.read().strip()
            ended = os.path.getmtime(status_file)
            return (f"finished at {time.strftime('%H:%M:%S', time.localtime(ended))} after "
                    f"{(ended - started) / 60:.0f} min ({'succeeded' if code == '0' else f'failed, exit {code}'})")
        lines = [l for l in tail_text(log).splitlines() if l.strip()]
        progress = next((PROGRESS.search(l) for l in reversed(lines) if PROGRESS.search(l)), None)
        state = f"running for {(time.time() - started) / 60:.0f} min"
        if progress:
            done, total = (int(x.replace(",", "")) for x in progress.groups()[:2])
            return f"{state}: {done:,} / {total:,} actions ({100 * done // max(total, 1)}%){progress.group(3)[:70]}"
        return f"{state}: {short(lines[-1], 90) if lines else ''}"
    return "none"


def short(text, n):
    text = re.sub(r"/root/obs-worker/script/[^/]+/cache/bazel/[0-9a-f]+/external", "<cache>", text)
    return text if len(text) <= n else text[:n - 1] + "…"


def main():
    config = sys.argv[1] if len(sys.argv) > 1 else "config/x86_64_to_ppc64le_power9.yaml"
    with open(os.path.join(ROOT, config)) as f:
        cfg = yaml.safe_load(f)
    log_dir = os.path.join(ROOT, cfg["paths"]["log_dir"])
    package = sys.argv[2] if len(sys.argv) > 2 else None
    every = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    while True:
        if not package:
            logs = [p for p in glob.glob(os.path.join(log_dir, "*.log")) if not p.endswith("global.log")]
            package = os.path.basename(max(logs, key=os.path.getmtime))[:-4] if logs else None
        if not package:   # nothing running yet (or any more)
            print(f"{time.strftime('%H:%M:%S')}  no package log in {os.path.relpath(log_dir, ROOT)} yet")
            if every <= 0:
                break
            time.sleep(every)
            continue
        lines = []
        try:
            with open(os.path.join(log_dir, f"{package}.log"), errors="replace") as f:
                lines = f.read().splitlines()
        except (OSError, TypeError):
            pass
        start = max((i for i, l in enumerate(lines) if "--- Build attempt 1/" in l), default=0)
        lines = lines[start:]
        attempt = next((l for l in reversed(lines) if "--- Build attempt" in l), "")
        rnd = next((l for l in reversed(lines) if "== Tool round" in l), "")
        calls = [m.groups() for m in map(CALL.match, lines) if m]
        edits = sum(c[1] in ("modify_file_tool", "replace_in_file_tool") for c in calls)
        builds = [l for l in lines if "Tool return text: Build result" in l or "[final check] check:" in l]
        status = {}
        try:
            with open(os.path.join(log_dir, f"{package}_status.json")) as f:
                status = json.load(f)
        except (OSError, ValueError):
            pass
        usage = status.get("usage") or {}
        if every > 0:
            print("\033[2J\033[H", end="")
        print(f"{time.strftime('%H:%M:%S')}  package {package}   (log {os.path.relpath(log_dir, ROOT)})")
        print(f"started {lines[0][1:20] if lines else '-'}   {attempt[22:].strip(' -')}   {rnd[22:].strip(' =')}")
        print(f"tool calls {len(calls)}   edits {edits}   builds {len(builds)}"
              + (f"   context {status.get('context_chars', 0) // 1000}k chars" if status else ""))
        if usage:
            print(f"cost ${usage.get('cost_usd', 0):.4f}   model calls {usage.get('llm_calls', 0)}   "
                  f"tokens in {usage.get('prompt_tokens', 0):,} (cached {usage.get('cached_tokens', 0):,}) "
                  f"out {usage.get('completion_tokens', 0):,}")
        else:
            spend = key_spend_today()
            print(f"cost: OpenRouter key spend today ${spend:.4f} (no status file for this run)"
                  if spend is not None else "cost: not available")
        print("\nlast build result: " + (short(builds[-1][22:], 150) if builds else "none yet"))
        print("current build: " + build_status(cfg, package))
        print("\nlast tool calls:")
        for t, name, args in calls[-8:]:
            print(f"  {t[11:]} {name:24} {short(args, 110)}")
        if any("Final saved" in l for l in lines):
            print("\nrun finished for this package")
        sys.stdout.flush()
        if every <= 0:
            break
        time.sleep(every)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
