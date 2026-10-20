"""Single entry point to run and inspect the benchmark (the Makefile calls it).

What to run comes from the run profile (bench.yaml); every setting can be
overridden on the command line (--label, --model, --attempts, ...):
  run [--bg]        start a run of the profile's packages
  resume FROM       continue the archived run FROM with more attempts
  stop              stop the active run and its builds, and archive what it left
  status            the active run and a view of its current package
  watch             the same view, refreshed every few seconds
  summary [PREFIX]  results of the archived runs, with the total cost
  archive NAME      move the files an interrupted run left into run directory NAME

A run is scripts/run_repeats.sh. This script adds what it lacks: one run at a
time (the active run is recorded in .bench/active.json), no start over the
files an interrupted run left (they would be archived with the new run), and
stopping a run with its builds, which run in sessions of their own."""
import argparse
import glob
import json
import os
import signal
import subprocess
import sys
import time

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
STATE_DIR = os.path.join(ROOT, ".bench")
ACTIVE = os.path.join(STATE_DIR, "active.json")
LOGS_DIR = os.path.join(ROOT, "logs")


# --- settings ----------------------------------------------------------------

def load_profile(path: str, overrides: dict) -> dict:
    with open(path) as f:
        profile = yaml.safe_load(f) or {}
    profile.update({k: v for k, v in overrides.items() if v not in (None, "")})
    packages = profile.get("packages") or []
    if isinstance(packages, str):
        packages = [p for p in packages.replace(",", " ").split() if p]
    profile["packages"] = list(packages)
    profile["repeats"] = int(profile.get("repeats") or 1)
    return profile


def run_env(profile: dict, resume: dict = None) -> dict:
    """The environment client.py reads its settings from."""
    env = dict(os.environ, PY=sys.executable)
    settings = {"BENCH_PACKAGES": ",".join(profile["packages"]), "LLM_MODEL": profile.get("model"),
                "OPENROUTER_PROVIDER": profile.get("provider"), "BENCH_MAX_ATTEMPTS": profile.get("attempts"),
                "LLM_TEMPERATURE": profile.get("temperature")}
    if resume:
        settings.update(BENCH_RESUME_FROM=resume["from"], BENCH_RESUME_WORKSPACE=resume.get("workspace"))
    for name, value in settings.items():
        if value in (None, ""):
            env.pop(name, None)
        else:
            env[name] = str(value)
    return env


def bench_paths(config: str) -> dict:
    with open(os.path.join(ROOT, config)) as f:
        paths = yaml.safe_load(f)["paths"]
    return {k: os.path.join(ROOT, paths[k]) for k in ("base_dir", "result_dir", "log_dir", "temp_work_dir")}


def case_names(paths: dict, packages: list) -> list:
    return packages or sorted(os.listdir(paths["base_dir"]))


# --- the active run ----------------------------------------------------------

def active_run():
    """The recorded active run, with alive=False when its process is gone."""
    try:
        with open(ACTIVE) as f:
            run = json.load(f)
    except (OSError, ValueError):
        return None
    try:
        os.kill(run["pid"], 0)
        run["alive"] = True
    except OSError:
        run["alive"] = False
    return run


def leftovers(paths: dict, packages: list) -> list:
    """Files an interrupted run left: run_repeats.sh archives the files at the
    top of the result and log directories when a run ends."""
    files = [p for d in (paths["result_dir"], paths["log_dir"]) if os.path.isdir(d)
             for p in sorted(glob.glob(os.path.join(d, "*"))) if os.path.isfile(p)]
    files += [p for p in (os.path.join(ROOT, "data", "case_study", f"{pkg}_diff.log")
                          for pkg in case_names(paths, packages)) if os.path.isfile(p)]
    return files


def archive(paths: dict, packages: list, name: str) -> list:
    """Move the files an interrupted run left into run directory name."""
    moved = []
    for path in leftovers(paths, packages):
        target = paths["result_dir"] if path.startswith(paths["result_dir"] + os.sep) else paths["log_dir"]
        os.makedirs(os.path.join(target, name), exist_ok=True)
        os.replace(path, os.path.join(target, name, os.path.basename(path)))
        moved.append(os.path.relpath(path, ROOT))
    for path in glob.glob(os.path.join(ROOT, f"pilot_{name.removesuffix('_stopped')}.log")):
        os.makedirs(os.path.join(paths["log_dir"], name), exist_ok=True)
        os.replace(path, os.path.join(paths["log_dir"], name, os.path.basename(path)))
        moved.append(os.path.relpath(path, ROOT))
    return moved


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def obs_config(config: str) -> dict:
    os.environ["BENCH_CONFIG"] = os.path.join(ROOT, config)
    from tools.auto_repair.obs_config import load_obs_config
    return load_obs_config()


def leak_findings(config: str, paths: dict, packages: list) -> dict:
    """Package -> what the model could read that gives the answer away."""
    from tools.auto_repair.leak_check import leak_report
    cfg = obs_config(config)
    print("checking what the model can read for leaks of the answer ...", file=sys.stderr, flush=True)
    return {pkg: leak_report(cfg, pkg, os.path.join(paths["base_dir"], pkg)) for pkg in case_names(paths, packages)}


def check_can_start(profile: dict, paths: dict, allow_leaks: bool = False) -> None:
    run = active_run()
    if run and run["alive"]:
        fail(f"run {run['label']} is active (pid {run['pid']}); stop it with `make stop` first")
    left = leftovers(paths, profile["packages"])
    if left:
        fail("an interrupted run left these files, which the new run would archive as its own:\n  "
             + "\n  ".join(os.path.relpath(p, ROOT) for p in left)
             + "\narchive them with `make archive NAME=<run>_stopped` (or delete them)")
    taken = [f"{profile['label']}_{i}" for i in range(1, profile["repeats"] + 1)
             if os.path.exists(os.path.join(paths["result_dir"], f"{profile['label']}_{i}"))
             or os.path.exists(os.path.join(paths["log_dir"], f"{profile['label']}_{i}"))]
    if taken:
        fail(f"run directories {', '.join(taken)} exist already; choose another label (LABEL=...)")
    for pkg in profile["packages"]:
        if not os.path.isdir(os.path.join(paths["base_dir"], pkg)):
            fail(f"no case {pkg} in {os.path.relpath(paths['base_dir'], ROOT)}")
    if not os.path.isfile(os.path.join(ROOT, ".env")) and not os.getenv("API_KEY"):
        fail("no .env with API_KEY (and no API_KEY in the environment)")
    leaks = {pkg: found for pkg, found in leak_findings(profile["config"], paths, profile["packages"]).items()
             if found}
    if leaks and not allow_leaks:
        fail("the model could read the answer:\n" + "\n".join(f"  {pkg}: {line}" for pkg, found in leaks.items()
                                                            for line in found)
             + "\nhide it (script.experiment_hide in the config), move it out of reach, "
               "or start anyway with ALLOW_LEAKS=1")


def runner(spec: dict) -> int:
    """Run run_repeats.sh for spec, recorded as the active run until it ends."""
    os.makedirs(STATE_DIR, exist_ok=True)
    record = {k: v for k, v in spec.items() if k != "env"}   # the environment may hold secrets
    with open(ACTIVE, "w") as f:
        json.dump(dict(record, pid=os.getpid(), pgid=os.getpgid(0)), f, indent=1)
    try:
        return subprocess.call(["bash", os.path.join(ROOT, "scripts", "run_repeats.sh"), spec["label"],
                                str(spec["repeats"]), spec["config"]], env=spec["env"], cwd=ROOT)
    finally:
        run = active_run()
        if run and run["pid"] == os.getpid():
            os.remove(ACTIVE)


# --- commands ----------------------------------------------------------------

def cmd_run(profile: dict, background: bool, resume: dict = None, allow_leaks: bool = False) -> None:
    if not profile.get("label"):
        fail("no label: set it in the profile or with LABEL=...")
    paths = bench_paths(profile["config"])
    check_can_start(profile, paths, allow_leaks)
    spec = {"label": profile["label"], "repeats": profile["repeats"], "config": profile["config"],
            "packages": profile["packages"], "model": profile.get("model"), "provider": profile.get("provider"),
            "attempts": profile.get("attempts"), "resume": resume, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            "env": run_env(profile, resume)}
    what = (f"{spec['label']}: {', '.join(spec['packages']) or 'all packages'}, {spec['model'] or 'model of .env'}"
            f"{' on ' + spec['provider'] if spec['provider'] else ''}, {spec['attempts'] or 'default'} attempts"
            f"{', continuing ' + resume['from'] if resume else ''}")
    if not background:
        print(f"running {what}")
        sys.exit(runner(spec))
    os.makedirs(LOGS_DIR, exist_ok=True)
    log = os.path.join(LOGS_DIR, f"{spec['label']}.log")
    with open(log, "w") as out:
        proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "_runner"], cwd=ROOT,
                                stdin=subprocess.PIPE, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        proc.stdin.write(json.dumps(spec).encode())
        proc.stdin.close()
    for _ in range(20):   # until the runner has recorded itself
        run = active_run()
        if run and run["pid"] == proc.pid:
            break
        time.sleep(0.25)
    print(f"started {what}\n  pid {proc.pid}, log {os.path.relpath(log, ROOT)}\n"
          "  follow it with `make status` or `make watch`; stop it with `make stop`")


def cmd_resume(profile: dict, source: str, workspace: str, background: bool, attempts,
               allow_leaks: bool = False) -> None:
    if not attempts:
        fail("say how many more attempts: ATTEMPTS=<n> (the profile's value is not used for a continuation)")
    profile["attempts"] = attempts
    paths = bench_paths(profile["config"])
    for pkg in case_names(paths, profile["packages"]):
        if not os.path.isfile(os.path.join(paths["result_dir"], source, f"{pkg}_result.json")):
            fail(f"{source} has no result for {pkg}: it was stopped before its first attempt ended "
                 f"(see {os.path.relpath(paths['result_dir'], ROOT)}/)")
    if not profile.get("label") or profile["label"] == load_profile(PROFILE_PATH, {}).get("label"):
        profile["label"] = f"{source}_cont"
    profile["repeats"] = 1
    cmd_run(profile, background, resume={"from": source, "workspace": workspace}, allow_leaks=allow_leaks)


def stop_builds(config: str, packages: list) -> None:
    """Builds, their tests and run_command_tool's commands run in sessions of
    their own: stop them too."""
    from tools.auto_repair.local_build import _stop
    from tools.auto_repair.script_build import stop_experiments
    cfg = obs_config(config)
    for pkg in packages:
        _stop(os.path.join(cfg["script"]["stage_root"], pkg, "run", "state.json"))
        _stop(os.path.join(cfg["local"]["worker_root"], "runs", pkg, "state.json"))
        stop_experiments(pkg, cfg)


def cmd_stop(profile: dict) -> None:
    run = active_run()
    if not run:
        fail("no active run (see `make status`)")
    if run["alive"]:
        print(f"stopping run {run['label']} (pid {run['pid']})")
        group = run.get("pgid", run["pid"])   # the runner, run_repeats.sh, client.py and server.py
        try:
            os.killpg(group, signal.SIGTERM)
            for _ in range(30):
                time.sleep(0.5)
                os.kill(run["pid"], 0)
            os.killpg(group, signal.SIGKILL)
        except OSError:
            pass
    paths = bench_paths(run["config"])
    packages = case_names(paths, run["packages"])
    stop_builds(run["config"], packages)
    # the run of run_repeats.sh that was interrupted is the one whose log is still at the top
    current = sorted(glob.glob(os.path.join(ROOT, f"pilot_{run['label']}_*.log")))
    name = (os.path.basename(current[-1])[len("pilot_"):-len(".log")] if current else run["label"]) + "_stopped"
    moved = archive(paths, packages, name)
    if os.path.exists(ACTIVE):
        os.remove(ACTIVE)
    print(f"stopped; {len(moved)} files archived as {name}" if moved else "stopped; nothing to archive")


def cmd_status(profile: dict, every: int) -> None:
    run = active_run()
    config = run["config"] if run else profile["config"]
    if run:
        state = "running" if run["alive"] else "not running (ended without cleaning up: see its log)"
        print(f"run {run['label']}: {state}, started {run['started']}, "
              f"{', '.join(run['packages']) or 'all packages'}, {run.get('model') or ''}"
              f"{', continuing ' + run['resume']['from'] if run.get('resume') else ''}\n")
    else:
        print("no active run (`make summary` lists the archived ones)")
        return
    package = run["packages"][0] if len(run["packages"]) == 1 else ""
    subprocess.call([sys.executable, os.path.join(ROOT, "scripts", "watch_run.py"), config, package, str(every)])


def cmd_summary(profile: dict, prefix: str, key_usage: bool) -> None:
    paths = bench_paths(profile["config"])
    rows, total = [], 0.0
    for run_dir in sorted(glob.glob(os.path.join(paths["log_dir"], f"{prefix}*")) +
                          glob.glob(os.path.join(paths["result_dir"], f"{prefix}*"))):
        run = os.path.basename(run_dir)
        if not os.path.isdir(run_dir) or any(r[0] == run for r in rows):
            continue
        for path in sorted(glob.glob(os.path.join(paths["result_dir"], run, "*_result.json"))):
            with open(path) as f:
                d = json.load(f)
            ok = ("yes" if d["success"] else "INFRA" if d.get("infrastructure_error")
                  else "stop" if d.get("complete") is False else "no")
            attempts = int(d.get("previous_attempts") or 0) + len(d.get("attempts") or [])
            minutes = f"{d['minutes']:.0f}" if d.get("minutes") is not None else "-"
            rows.append((run, d["package"], ok, str(d.get("success_attempt") or "-"), str(attempts),
                         minutes, float(d.get("cost_usd") or 0)))
        if not any(r[0] == run for r in rows):   # a stopped run: no result, the last status
            for path in sorted(glob.glob(os.path.join(paths["log_dir"], run, "*_status.json"))):
                with open(path) as f:
                    d = json.load(f)
                rows.append((run, d["package"], "stop", "-", str(d.get("attempt") or "-"), "-",
                             float(d["usage"].get("cost_usd") or 0)))
    print(f"{'run':<46} {'package':<16} {'ok':<5} {'att':>3} {'of':>3} {'min':>5} {'cost $':>8}")
    for run, pkg, ok, att, of, minutes, cost in rows:
        total += cost
        print(f"{run:<46} {pkg:<16} {ok:<5} {att:>3} {of:>3} {minutes:>5} {cost:>8.3f}")
    print(f"\n{len(rows)} package runs of {profile['config']}, total cost ${total:.2f}")
    if key_usage:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from watch_run import env_value
        import urllib.request
        key, base = env_value("API_KEY"), env_value("API_BASE_URL") or "https://openrouter.ai/api/v1"
        try:
            req = urllib.request.Request(base.rstrip("/") + "/key", headers={"Authorization": f"Bearer {key}"})
            k = json.load(urllib.request.urlopen(req, timeout=30))["data"]
            print(f"OpenRouter key (all uses): total ${k.get('usage') or 0:.2f}, this month "
                  f"${k.get('usage_monthly') or 0:.2f}, today ${k.get('usage_daily') or 0:.2f}")
        except Exception as e:
            print(f"OpenRouter key usage not available: {e}")


def cmd_leaks(profile: dict) -> None:
    paths = bench_paths(profile["config"])
    findings = leak_findings(profile["config"], paths, profile["packages"])
    for pkg, found in findings.items():
        print(f"{pkg}: " + ("nothing found" if not found else f"{len(found)} finding(s)"))
        for line in found:
            print(f"  {line}")
    sys.exit(1 if any(findings.values()) else 0)


def cmd_archive(profile: dict, name: str) -> None:
    run = active_run()
    if run and run["alive"]:
        fail(f"run {run['label']} is active; stop it with `make stop`")
    paths = bench_paths(profile["config"])
    moved = archive(paths, profile["packages"], name)
    print("\n".join(f"  {p}" for p in moved) if moved else "nothing to archive")


PROFILE_PATH = os.path.join(ROOT, "bench.yaml")


def main() -> None:
    global PROFILE_PATH
    os.chdir(ROOT)
    if sys.argv[1:2] == ["_runner"]:
        sys.exit(runner(json.load(sys.stdin)))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", default=PROFILE_PATH)
    for option in ("config", "label", "packages", "model", "provider", "attempts", "repeats", "temperature"):
        parser.add_argument(f"--{option}")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--bg", action="store_true", help="run in the background")
    run.add_argument("--allow-leaks", action="store_true", help="start even if the leak check finds something")
    resume = sub.add_parser("resume")
    resume.add_argument("source", help="archived run to continue, e.g. run29_v41flash_scratch_12att_1")
    resume.add_argument("--workspace", help="copy of the workspace to continue from (default: the current one)")
    resume.add_argument("--bg", action="store_true")
    resume.add_argument("--allow-leaks", action="store_true")
    sub.add_parser("leaks")
    sub.add_parser("stop")
    sub.add_parser("status")
    watch = sub.add_parser("watch")
    watch.add_argument("--every", type=int, default=10)
    summary = sub.add_parser("summary")
    summary.add_argument("prefix", nargs="?", default="")
    summary.add_argument("--key", action="store_true", help="also the OpenRouter key's usage")
    arch = sub.add_parser("archive")
    arch.add_argument("name")
    args = parser.parse_args()
    PROFILE_PATH = os.path.abspath(args.profile)
    profile = load_profile(PROFILE_PATH, {k: getattr(args, k) for k in
                                          ("config", "label", "packages", "model", "provider", "attempts",
                                           "repeats", "temperature")})
    if args.command == "run":
        cmd_run(profile, args.bg, allow_leaks=args.allow_leaks)
    elif args.command == "resume":
        cmd_resume(profile, args.source, args.workspace, args.bg, args.attempts, args.allow_leaks)
    elif args.command == "leaks":
        cmd_leaks(profile)
    elif args.command == "stop":
        cmd_stop(profile)
    elif args.command == "status":
        cmd_status(profile, 0)
    elif args.command == "watch":
        cmd_status(profile, args.every)
    elif args.command == "summary":
        cmd_summary(profile, args.prefix, args.key)
    elif args.command == "archive":
        cmd_archive(profile, args.name)


if __name__ == "__main__":
    main()
