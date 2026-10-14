"""Live view of a benchmark run: attempt, round, edits, builds, context size
and cost, refreshed every few seconds.
Usage: python scripts/watch_run.py [config] [package] [seconds]
  (defaults: config/x86_64_to_ppc64le_power9.yaml, the package of the newest
  log, 10 s). Works through the sshfs mount too; Ctrl-C stops it.
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


def short(text, n):
    text = re.sub(r"/root/obs-worker/script/[^/]+/cache/bazel/[0-9a-f]+/external", "<cache>", text)
    return text if len(text) <= n else text[:n - 1] + "…"


def main():
    config = sys.argv[1] if len(sys.argv) > 1 else "config/x86_64_to_ppc64le_power9.yaml"
    with open(os.path.join(ROOT, config)) as f:
        log_dir = os.path.join(ROOT, yaml.safe_load(f)["paths"]["log_dir"])
    package = sys.argv[2] if len(sys.argv) > 2 else None
    every = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    while True:
        if not package:
            logs = [p for p in glob.glob(os.path.join(log_dir, "*.log")) if not p.endswith("global.log")]
            package = os.path.basename(max(logs, key=os.path.getmtime))[:-4] if logs else None
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
        print("\nlast build: " + (short(builds[-1][22:], 150) if builds else "none yet"))
        print("\nlast tool calls:")
        for t, name, args in calls[-8:]:
            print(f"  {t[11:]} {name:24} {short(args, 110)}")
        if any("Final saved" in l for l in lines):
            print("\nrun finished for this package")
        sys.stdout.flush()
        time.sleep(every)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
