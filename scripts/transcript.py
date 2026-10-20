"""Read what the model did in a run: an overview of its attempts, or one
attempt round by round (its reasoning, replies, tool calls and their results).

Usage: python scripts/transcript.py <log_dir> <run> [options]
       (or: make transcript RUN=<run> [ATTEMPT=n] ...)
  run          an archived run (a directory of log_dir), or "current" for the
               active run
  --package    package of the run (default: its only, or first, package)
  --attempt N  show attempt N round by round; without it, an overview
  --reasoning  include the model's reasoning (saved since run26d)
  --full       do not shorten anything
  --tool NAME  only the calls of this tool (e.g. run_command_tool) and their results
  --grep RE    only the rounds whose text matches the regular expression"""
import argparse
import glob
import json
import os
import re
import sys

SHORT = {"reasoning": 700, "content": 700, "args": 300, "result": 500}
EDITS = ("modify_file_tool", "replace_in_file_tool")


def shorten(text: str, limit: int, full: bool) -> str:
    text = (text or "").strip()
    if full or len(text) <= limit:
        return text
    return text[:limit] + f" […{len(text) - limit} more characters]"


def attempt_files(run_dir: str, package: str) -> dict:
    files = {}
    for path in glob.glob(os.path.join(run_dir, f"{package}_attempt*_messages.json")):
        m = re.search(r"_attempt(\d+)_messages\.json$", path)
        files[int(m.group(1))] = path
    return dict(sorted(files.items()))


def rounds(messages: list) -> list:
    """[(assistant message, [(tool call, result)])] in order."""
    results = {m.get("tool_call_id"): m.get("content") for m in messages if m.get("role") == "tool"}
    out = []
    for m in messages:
        if m.get("role") == "assistant":
            calls = [(c, results.get(c.get("id"), "")) for c in m.get("tool_calls") or []]
            out.append((m, calls))
    return out


def build_outcome(line: str) -> str:
    """A build result in a few words."""
    if "Build succeeded" in line:
        return "succeeded" + (", acceptance test passed" if "acceptance test passed" in line else "")
    if "acceptance test failed" in line:
        return "built, acceptance test failed"
    for word in ("failed", "unresolvable", "timeout", "broken", "infrastructure error", "error"):
        if word in line.lower():
            return f"build {word}"
    return shorten(line.replace("Build result: ", ""), 60, False)


def overview(run_dir: str, package: str, files: dict) -> None:
    result = {}
    for d in (run_dir, run_dir.replace("result_log_res", "result_text_res")):
        path = os.path.join(d, f"{package}_result.json")
        if os.path.isfile(path):
            with open(path) as f:
                result = json.load(f)
    summaries = {a["attempt"]: a for a in result.get("attempts") or []}
    print(f"{package} in {os.path.basename(run_dir)}: {len(files)} attempt transcript(s)"
          + (f", success in attempt {result['success_attempt']}" if result.get("success") else ""))
    print(f"\n{'att':>3} {'rounds':>6} {'edits':>5} {'builds':>6} {'cmds':>5} {'reason':>6}  "
          "how it ended; result of its last build")
    for attempt, path in files.items():
        with open(path) as f:
            messages = json.load(f)
        rs = rounds(messages)
        names = [c["function"]["name"] for _, calls in rs for c, _ in calls]
        summary = summaries.get(attempt, {})
        # the result's list includes the builds of the framework's final check
        builds = summary.get("builds") or [r.splitlines()[0] for _, calls in rs for c, r in calls
                                           if c["function"]["name"] == "check_build_result" and r]
        last = build_outcome(builds[-1]) if builds else "no build"
        print(f"{attempt:>3} {len(rs):>6} {sum(n in EDITS for n in names):>5} {len(builds):>6} "
              f"{names.count('run_command_tool'):>5} {sum(bool(m.get('reasoning')) for m, _ in rs):>6}  "
              f"{summary.get('ended_by') or 'stopped'}; {last}")
    print("\nedits: modify/replace calls; cmds: run_command_tool calls; reason: replies with saved reasoning")
    print("\n(show one attempt with --attempt N; ATTEMPT=N with make)")


def show_attempt(path: str, args) -> None:
    with open(path) as f:
        messages = json.load(f)
    user = next((m.get("content") or "" for m in messages if m.get("role") == "user"), "")
    prompt = user if args.full else f"{user.splitlines()[0] if user else ''} [{len(user)} characters; --full shows them]"
    print(f"=== {os.path.basename(path)}\n--- prompt: {prompt}\n")
    for number, (m, calls) in enumerate(rounds(messages), 1):
        if args.tool:
            calls = [(c, r) for c, r in calls if c["function"]["name"] == args.tool]
            if not calls:
                continue
        text = "\n".join([m.get("reasoning") or "", m.get("content") or ""]
                         + [c["function"]["arguments"] + (r or "") for c, r in calls])
        if args.grep and not re.search(args.grep, text, re.I):
            continue
        print(f"--- round {number}")
        if args.reasoning and m.get("reasoning"):
            print(f"[reasoning] {shorten(m['reasoning'], SHORT['reasoning'], args.full)}")
        if (m.get("content") or "").strip():
            print(f"[reply] {shorten(m['content'], SHORT['content'], args.full)}")
        for c, r in calls:
            print(f"→ {c['function']['name']}({shorten(c['function']['arguments'], SHORT['args'], args.full)})")
            print(f"← {shorten(r, SHORT['result'], args.full)}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log_dir")
    parser.add_argument("run")
    parser.add_argument("--package")
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--reasoning", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--tool")
    parser.add_argument("--grep")
    args = parser.parse_args()
    run_dir = args.log_dir if args.run == "current" else os.path.join(args.log_dir, args.run)
    if not os.path.isdir(run_dir):
        runs = sorted(os.path.basename(d) for d in glob.glob(os.path.join(args.log_dir, f"*{args.run}*")))
        sys.exit(f"error: no run {args.run} in {args.log_dir}" + (f"; did you mean: {', '.join(runs[:8])}" if runs else ""))
    packages = sorted({re.sub(r"_attempt\d+_messages\.json$", "", os.path.basename(p))
                       for p in glob.glob(os.path.join(run_dir, "*_attempt*_messages.json"))})
    package = args.package or (packages[0] if packages else None)
    if not package:
        sys.exit(f"error: no transcripts in {run_dir}")
    files = attempt_files(run_dir, package)
    if args.attempt is None:
        overview(run_dir, package, files)
    elif args.attempt not in files:
        sys.exit(f"error: no attempt {args.attempt} of {package} (there are: {', '.join(map(str, files))})")
    else:
        show_attempt(files[args.attempt], args)


if __name__ == "__main__":
    main()
