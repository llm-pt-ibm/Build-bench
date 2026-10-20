"""Live dashboard of the benchmark in the terminal: the active run and its
packages, the current package's attempt and round, how the earlier attempts
ended, the build and acceptance test in progress, what the model is doing
and the cost so far.

Usage: python scripts/dashboard.py [config] [seconds]
  (make watch, refreshed every 10 s; make status, printed once with 0 s)
From another machine:  ssh -t <build host> 'cd /root/build-bench && make watch'
Ctrl-C stops watching, not the run. NO_COLOR=1 turns the colors off."""
import datetime
import glob
import json
import os
import re
import shutil
import socket
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from watch_run import CALL, PROGRESS, host_path, short, tail_text  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ATTEMPT = re.compile(r"--- Build attempt (\d+)/(\d+) ---")
EDITS = ("modify_file_tool", "replace_in_file_tool")
COLOR = sys.stdout.isatty() and not os.getenv("NO_COLOR")


def paint(text, code):
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def bold(t): return paint(t, "1")
def dim(t): return paint(t, "2")
def green(t): return paint(t, "32")
def red(t): return paint(t, "31")
def yellow(t): return paint(t, "33")
def cyan(t): return paint(t, "36")


def bar(done, total, width=24):
    total = max(total, 1)
    filled = min(width, round(width * done / total))
    return paint("█" * filled, "36") + dim("░" * (width - filled))


def ago(seconds):
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def outcome(line):
    """A build result in a few words, colored."""
    if "Build succeeded" in line:
        return green("succeeded")
    if "acceptance test failed" in line:
        return yellow("built, acceptance test failed")
    if "infrastructure" in line.lower():
        return yellow("build host error")
    return red("build failed") if "fail" in line.lower() else short(line.replace("Build result: ", ""), 50)


def build_dirs(cfg, package):
    build = cfg.get("build") or {}
    return [host_path(os.path.join((build.get("script") or {}).get("stage_root", "/root/obs-worker/script"),
                                   package, "run")),
            host_path(os.path.join((build.get("local") or {}).get("worker_root", "/root/obs-worker"),
                                   "runs", package))]


def build_lines(cfg, package, run_started):
    """The package's latest build and acceptance test, as dashboard lines."""
    for run in build_dirs(cfg, package):
        log = os.path.join(run, "build.log")
        if not os.path.exists(log):
            continue
        state = read_json(os.path.join(run, "state.json"))
        started = state.get("time") or os.path.getmtime(log)
        stale = run_started and started < run_started
        status_file = os.path.join(run, "status")
        lines = []
        if not os.path.exists(status_file):
            text = [l for l in tail_text(log).splitlines() if l.strip()]
            progress = next((PROGRESS.search(l) for l in reversed(text) if PROGRESS.search(l)), None)
            if progress:
                done, total = (int(x.replace(",", "")) for x in progress.groups()[:2])
                lines.append(f"{cyan('running')} {ago(time.time() - started)}  {bar(done, total)} "
                             f"{done:,}/{total:,} actions")
                lines.append(dim(short(progress.group(3).strip(" ;"), 96)))
            else:
                lines.append(f"{cyan('running')} {ago(time.time() - started)}  "
                             + dim(short(text[-1], 80) if text else ""))
            return lines
        with open(status_file) as f:
            code = f.read().strip()
        ended = os.path.getmtime(status_file)
        when = datetime.datetime.fromtimestamp(ended).strftime("%H:%M")
        lines.append((green("succeeded") if code == "0" else red(f"failed (exit {code})"))
                     + f" at {when} after {ago(ended - started)}" + (dim("  (before this run)") if stale else ""))
        acceptance = os.path.join(run, "acceptance.log")
        if code == "0":
            if not os.path.exists(acceptance) or os.path.getmtime(acceptance) < ended:
                lines.append(f"{cyan('acceptance test running')} for {ago(time.time() - ended)}")
            else:
                with open(acceptance, errors="replace") as f:
                    text = f.read()
                suite = re.search(r"^(?:PASS|FAIL) (\w*test_suite).*?: (.*)$", text, re.M)
                checks = [c for c in re.findall(r"^(PASS|FAIL) (\S+)", text, re.M)
                          if not suite or c[1].rstrip(":") != suite.group(1)]
                passed = sum(r == "PASS" for r, _ in checks)
                verdict = green("passed") if "acceptance: 0 check(s) failed" in text else red("failed")
                lines.append(f"acceptance test {verdict}: {passed}/{len(checks)} checks"
                             + (f" · test suite: {suite.group(2)[:60]}" if suite else ""))
        return lines
    return [dim("no build yet")]


def model_lines(log_dir, package, attempt, width):
    """The model's latest reasoning or reply, and how long it has been thinking."""
    messages = read_json(os.path.join(log_dir, f"{package}_attempt{attempt}_messages.json"))
    last = next((m for m in reversed(messages if isinstance(messages, list) else [])
                 if m.get("role") == "assistant"), None)
    if not last:
        return []
    text = (last.get("reasoning") or last.get("content") or "").strip().replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return [dim("“…" + text[-(width * 2 - 10):] + "”")] if text else []


def last_run_lines(result_dir):
    """With nothing running: the latest archived run."""
    runs = [d for d in glob.glob(os.path.join(result_dir, "*")) if os.path.isdir(d)]
    if not runs:
        return [dim("no runs yet")]
    latest = max(runs, key=os.path.getmtime)
    out = [f"\n{dim('last run')} {bold(os.path.basename(latest))}"]
    for path in sorted(glob.glob(os.path.join(latest, "*_result.json"))):
        r = read_json(path)
        attempts = int(r.get("previous_attempts") or 0) + len(r.get("attempts") or [])
        verdict = (green(f"✓ success in attempt {r.get('success_attempt')}") if r.get("success")
                   else yellow("stopped") if r.get("complete") is False else red("✗ no success"))
        out.append(f"  {r.get('package', '?'):<20} {verdict}   {attempts} attempts · "
                   f"{r.get('minutes', 0):.0f} min · ${float(r.get('cost_usd') or 0):.2f}")
    out.append(dim("make summary lists all runs; make transcript RUN=... shows one"))
    return out


def render(config, run):
    with open(os.path.join(ROOT, config)) as f:
        cfg = yaml.safe_load(f)
    log_dir = os.path.join(ROOT, cfg["paths"]["log_dir"])
    result_dir = os.path.join(ROOT, cfg["paths"]["result_dir"])
    width = min(shutil.get_terminal_size((110, 40)).columns, 130)
    out = []
    run_started = None
    if run:
        try:
            run_started = time.mktime(time.strptime(run["started"], "%Y-%m-%d %H:%M:%S"))
        except (KeyError, ValueError):
            pass
    logs = sorted((p for p in glob.glob(os.path.join(log_dir, "*.log")) if not p.endswith("global.log")),
                  key=os.path.getmtime)
    packages = (run or {}).get("packages") or [os.path.basename(p)[:-4] for p in logs]
    title = f"{bold('Build-bench')}  "
    if run:
        state = (cyan(f"running on {run.get('host')}") if run.get("alive") is None
                 else green("running") if run.get("alive") else red("not running"))
        title += (f"{bold(run['label'])} · {state} · {run.get('model') or 'model of .env'}"
                  + (f" @ {run['base_url']}" if run.get("base_url")
                     else f" @ {run['provider']}" if run.get("provider") else ""))
    else:
        title += dim("no active run (make run starts one)")
    out.append(f"{title}   {dim(time.strftime('%H:%M:%S'))}")
    if not packages:
        out.extend(last_run_lines(result_dir))
        return out

    # every package: done, running or waiting
    states, total_cost, tokens_in, tokens_out = [], 0.0, 0, 0
    current = None
    for pkg in packages:
        result = read_json(os.path.join(result_dir, f"{pkg}_result.json"))
        status = read_json(os.path.join(log_dir, f"{pkg}_status.json"))
        usage = status.get("usage") or result
        total_cost += float(usage.get("cost_usd") or 0)
        tokens_in += int(usage.get("prompt_tokens") or 0)
        tokens_out += int(usage.get("completion_tokens") or 0)
        if result.get("complete", bool(result)) and result:
            states.append(f"{pkg} " + (green("✓") if result.get("success") else red("✗")))
        elif os.path.exists(os.path.join(log_dir, f"{pkg}.log")):
            states.append(f"{pkg} " + cyan("▶"))
            current = pkg
        else:
            states.append(dim(f"{pkg} ·"))
    done = sum("✓" in s or "✗" in s for s in states)
    elapsed = ago(time.time() - run_started) if run_started else "-"
    out.append(f"{dim('config')} {os.path.basename(config)}   {dim('elapsed')} {elapsed}   "
               f"{dim('cost')} {bold(f'${total_cost:.2f}')}   {dim('tokens')} {tokens_in / 1e6:.1f}M in · "
               f"{tokens_out / 1e6:.2f}M out")
    out.append(f"{dim('packages')} {bar(done, len(packages), 12)} {done}/{len(packages)}   " + "  ".join(states))
    if not current:
        return out

    # the current package
    with open(os.path.join(log_dir, f"{current}.log"), errors="replace") as f:
        lines = f.read().splitlines()
    starts = [i for i, l in enumerate(lines) if ATTEMPT.search(l)]
    attempt, last = (int(x) for x in ATTEMPT.search(lines[starts[-1]]).groups()) if starts else (0, 0)
    first = int(ATTEMPT.search(lines[starts[0]]).group(1)) if starts else 1
    status = read_json(os.path.join(log_dir, f"{current}_status.json"))
    rnd, max_rounds = status.get("round", 0), status.get("max_rounds") or 60
    calls = [m.groups() for m in map(CALL.match, lines) if m]
    names = [c[1] for c in calls]
    out.append("")
    out.append(f"{bold(current)}  attempt {attempt}/{last} {bar(attempt - first + 1, last - first + 1, 12)}   "
               f"round {rnd}/{max_rounds} {bar(rnd, max_rounds, 20)}")
    out.append(f"  {dim('edits')} {sum(n in EDITS for n in names)} · {dim('builds')} "
               f"{sum('Build result:' in l for l in lines)} · {dim('experiments')} "
               f"{names.count('run_command_tool')} · {dim('tool calls')} {len(calls)} · {dim('context')} "
               f"{status.get('context_chars', 0) // 1000}k chars")

    result = read_json(os.path.join(result_dir, f"{current}_result.json"))
    history = []
    for a in result.get("attempts") or []:
        builds = a.get("builds") or []
        history.append(f"{a['attempt']}: " + (outcome(builds[-1]) if builds else dim("no build")))
    if history:
        out.append(f"  {dim('attempts')} " + dim(" · ").join(history[-6:]))

    out.append(f"{bold('build')}  " + "\n       ".join(build_lines(cfg, current, run_started)))
    if calls:
        idle = time.time() - time.mktime(time.strptime(calls[-1][0], "%Y-%m-%d %H:%M:%S"))
        if names[-1] == "check_build_result" and not any("Build result:" in l for l in lines[-5:]):
            doing = f"waiting for the build and its test ({ago(idle)})"
        elif any("[final check]" in l for l in lines[-3:]) or (lines and "final check" in lines[-1]):
            doing = "the framework is building what the attempt left"
        else:
            doing = f"thinking for {ago(idle)}" if idle > 30 else "working"
        out.append(f"{bold('model')}  {doing}")
    out.extend("       " + l for l in model_lines(log_dir, current, attempt, width - 10))
    out.append(dim("recent tool calls"))
    for t, name, args in calls[-6:]:
        out.append(f"  {dim(t[11:])} {name:<24} {dim(short(args, width - 38))}")
    return out


def main():
    config = sys.argv[1] if len(sys.argv) > 1 else "config/x86_64_to_ppc64le_power9.yaml"
    every = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    while True:
        run = read_json(os.path.join(ROOT, ".bench", "active.json")) or None
        if run:
            if run.get("host", socket.gethostname()) != socket.gethostname():
                run["alive"] = None   # watched from another machine (e.g. through a mount)
            else:
                try:
                    os.kill(run["pid"], 0)
                    run["alive"] = True
                except (OSError, KeyError):
                    run["alive"] = False
            config = run.get("config", config)
        try:
            screen = render(config, run)
        except Exception as e:   # files change under our feet: show it and try again
            screen = [f"dashboard error: {e.__class__.__name__}: {e} (retrying)"]
        if every > 0:
            print("\033[2J\033[H", end="")
        print("\n".join(screen))
        sys.stdout.flush()
        if every <= 0:
            break
        time.sleep(every)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
