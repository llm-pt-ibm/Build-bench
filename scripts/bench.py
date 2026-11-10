"""Single entry point of the benchmark, called by the Makefile (`make` lists
the commands). A run is scripts/run_repeats.sh; this script keeps one run at a
time (.bench/active.json), refuses to start over the files an interrupted run
left, and stops a run together with its builds."""
import argparse
import glob
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from tools.auto_repair.model_api import api_base  # noqa: E402
STATE_DIR = os.path.join(ROOT, ".bench")
ACTIVE = os.path.join(STATE_DIR, "active.json")
LOGS_DIR = os.path.join(ROOT, "logs")
DOTENV = os.path.join(ROOT, ".env")


# --- settings ----------------------------------------------------------------

# settings of older versions, refused rather than ignored (also as make variables)
REMOVED_SETTINGS = ("packages", "base_url", "api_key_env")


def load_profile(path: str, overrides: dict) -> dict:
    """The settings of a run: the config's, with the command line's overrides.
    `config` is the config file itself, `packages` the cases of its suite."""
    with open(path) as f:
        profile = yaml.safe_load(f) or {}
    profile["config"] = os.path.relpath(path, ROOT) if path.startswith(ROOT + os.sep) else path
    profile["removed"] = [k for k in REMOVED_SETTINGS if profile.pop(k, None) not in (None, "", [])]
    # "none" clears a setting of the config (e.g. PROVIDER=none for a model its provider does not serve)
    profile.update({k: None if str(v).lower() == "none" else v for k, v in overrides.items() if v not in (None, "")})
    profile["suite"] = profile.get("suite") or None
    profile["packages"] = suite_packages(profile) if profile["suite"] else []
    profile["repeats"] = int(profile.get("repeats") or 1)
    return profile


def suite_packages(profile: dict) -> list:
    """The cases of the profile's suite, one of the config's suites."""
    name, suites = str(profile["suite"]), profile.get("suites") or {}
    if name not in suites:
        listed = f"; its suites: {', '.join(map(str, suites))}" if suites else ""
        fail(f"no suite {name} in {profile['config']}{listed}")
    packages = load_profile_packages(suites[name])
    if not packages:
        fail(f"suite {name} of {profile['config']} has no cases")
    return packages


def check_settings(profile: dict) -> None:
    """A run has a suite, and none of the settings of older versions."""
    removed = profile.get("removed", []) + [k.upper() for k in REMOVED_SETTINGS if os.getenv(k.upper())]
    if removed:
        fail(f"{', '.join(removed)}: no longer read. A run's cases are a suite of the config (suite, or SUITE), "
             "and the model's address and key are API_BASE_URL and API_KEY in .env")
    llm = profile.get("llm") or {}
    if "round_notice_at" in llm or not isinstance(llm.get("round_notices", False), bool):
        fail(f"{profile['config']}: llm.round_notice_at is gone: llm.round_notices: true tells the model "
             "when half and a quarter of its rounds are left")
    if "build_drought_rounds" in llm or not isinstance(llm.get("build_drought_note", False), bool):
        fail(f"{profile['config']}: llm.build_drought_rounds is gone: llm.build_drought_note: true tells the "
             "model to build after a quarter of its rounds without a change or a build")
    if not isinstance(llm.get("extra_tools", False), bool):
        fail(f"{profile['config']}: llm.extra_tools is true or false now (true: search_files_tool, "
             "replace_in_file_tool and run_command_tool; false: only the paper's tools)")
    if not profile["suite"]:
        suites = ", ".join(map(str, profile.get("suites") or {})) or "it has none"
        fail(f"no suite: set suite in {profile['config']} (or SUITE) to one of its suites ({suites})")


def load_profile_packages(packages) -> list:
    """The cases of a suite ("a b", "a,b" or a list) as a list."""
    if isinstance(packages, str):
        packages = [p for p in packages.replace(",", " ").split() if p]
    return list(packages or [])


def run_env(profile: dict, resume: dict = None) -> dict:
    """The environment client.py reads its settings from."""
    env = dict(os.environ, PY=sys.executable)
    settings = {"BENCH_PACKAGES": ",".join(profile["packages"]), "LLM_MODEL": profile.get("model"),
                "OPENROUTER_PROVIDER": profile.get("provider"), "BENCH_MAX_ATTEMPTS": profile.get("attempts"),
                "LLM_TEMPERATURE": profile.get("temperature"),
                "BENCH_MAX_CONTEXT_CHARS": profile.get("context_chars")}
    if resume:
        settings.update(BENCH_RESUME_FROM=resume["from"], BENCH_RESUME_WORKSPACE=resume.get("workspace"))
    for name, value in settings.items():
        # empty rather than unset: client.py loads .env, which must not fill in
        # a setting that bench.yaml leaves empty
        env[name] = "" if value in (None, "") else str(value)
    return env


def dotenv_value(name: str):
    try:
        with open(DOTENV) as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key.strip() == name:
                    return value.split(" #")[0].strip().strip("'\"")
    except OSError:
        pass
    return None


def model_api() -> tuple:
    """API_BASE_URL and API_KEY, of the environment or of .env: OpenRouter's,
    or those of a server of one's own."""
    return tuple(os.getenv(k) or dotenv_value(k) or "" for k in ("API_BASE_URL", "API_KEY"))


def check_model_api(profile: dict) -> None:
    """The run's model API is that of .env; a server other than OpenRouter
    must answer and serve the model (so the run does not spend its first
    minutes retrying), and never gets the OpenRouter key."""
    base, key = model_api()
    if not base:
        fail("no API_BASE_URL in .env: https://openrouter.ai/api/v1, or the address of a server of your own, "
             "e.g. http://127.0.0.1:11434/v1 (Ollama)")
    if "openrouter.ai" in base:
        if not key:
            fail("no API_KEY in .env: the key of OpenRouter")
        return
    if key.startswith("sk-or-"):
        fail(f"API_KEY in .env is an OpenRouter key, and API_BASE_URL is another server ({api_base(base)}): "
             "set API_KEY to that server's key, or leave it empty")
    check_model_server(profile.get("model"), base, key)


def check_model_server(model, base: str, key: str) -> None:
    import urllib.request
    headers = {} if key in ("", "none") else {"Authorization": f"Bearer {key}"}
    try:
        request = urllib.request.Request(base.rstrip("/") + "/models", headers=headers)
        with urllib.request.urlopen(request, timeout=10) as r:
            served = [m.get("id") for m in json.load(r).get("data") or []]
    except Exception as e:
        fail(f"no model server answers at {api_base(base)} ({e.__class__.__name__}: {e}); start it first, e.g. "
             "`OLLAMA_CONTEXT_LENGTH=65536 ollama serve` or `vllm serve <model> --enable-auto-tool-choice ...`")
    if not model:
        fail("no model: set it in the config or with MODEL=...")
    if served and model not in served:
        fail(f"{api_base(base)} does not serve {model}; it serves: {', '.join(served[:12])} "
             f"(Ollama: `ollama pull {model}`)")


def bench_paths(config: str) -> dict:
    """Cases, workspaces, results and logs of config: they follow from its
    source_arch and target_arch (tools/auto_repair/bench_config.py)."""
    from tools.auto_repair import bench_config
    return bench_config.run_paths(bench_config.load(os.path.join(ROOT, config)))


# the key of the config each setting of the command line sets
OPTION_KEYS = {"label": "label", "suite": "suite", "model": "model", "provider": "provider",
               "repeats": "repeats",
               "temperature": "temperature", "attempts": "llm.max_build_attempts",
               "context_chars": "llm.max_context_chars"}


def yaml_value(value) -> str:
    """value as the config writes it after `key:` (nothing for None)."""
    if value is None:
        return ""
    if isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value):
        return value   # a number given on the command line
    text = yaml.safe_dump(value, default_flow_style=True, width=1 << 16).strip()
    return text[:-len("\n...")] if text.endswith("\n...") else text


def set_config_value(text: str, key: str, value) -> str:
    """text of a config with key (a top-level one, or one of a section: llm.<name>)
    set to value on its own line, keeping the line's comment where it was; a key
    the config lacks is added."""
    section, _, name = key.rpartition(".")
    lines = text.split("\n")
    first, last, indent = 0, len(lines), ""
    if section:
        head = next((i for i, line in enumerate(lines) if re.match(rf"{section}:\s*(#.*)?$", line)), None)
        if head is None:
            return text.rstrip("\n") + f"\n{section}:\n  {name}: {yaml_value(value)}\n"
        first = last = head + 1
        while last < len(lines) and (lines[last].startswith((" ", "\t")) or not lines[last].strip()):
            last += 1
        indent = next((re.match(r"\s*", line).group() for line in lines[first:last] if line.strip()), "  ")
    for i in range(first, last):
        m = re.match(rf"({re.escape(indent)}{re.escape(name)}:)([^#]*)(#.*)?$", lines[i])
        if m and (section or not lines[i][:1].isspace()):
            new = f"{m.group(1)} {yaml_value(value)}".rstrip()
            if m.group(3):   # the comment stays in its column
                column = len(m.group(1)) + len(m.group(2))
                new = new.ljust(column - 1) + " " + m.group(3)
            lines[i] = new
            return "\n".join(lines)
    while last > first and not lines[last - 1].strip():
        last -= 1   # after the section's last line, not after blank lines
    lines.insert(last, f"{indent}{name}: {yaml_value(value)}")
    return "\n".join(lines)


def frozen_config(profile: dict) -> str:
    """A copy of the config for the run that starts, with the values the run
    uses where the command line (or a continuation) changed them, so that the
    copy run_repeats.sh keeps with the run's logs says what the run did;
    bench.yaml can be edited for the next run in the meantime."""
    text = open(os.path.join(ROOT, profile["config"])).read()
    raw = yaml.safe_load(text) or {}
    changed = []
    for option, key in OPTION_KEYS.items():
        section, _, name = key.rpartition(".")
        in_file = (raw.get(section) or {}).get(name) if section else raw.get(name)
        value = profile.get(option)
        if section and value in (None, ""):
            continue   # not set on the command line: the config's value applies
        if option == "repeats":
            in_file = int(in_file or 1)
        if str(in_file if in_file is not None else "") != str(value if value is not None else ""):
            text = set_config_value(text, key, value)
            changed.append(key)
    if changed:
        text = (f"# this run's settings: {profile['config']}, with {', '.join(changed)} as the run set them "
                "(make variables, or a continuation)\n" + text)
    os.makedirs(STATE_DIR, exist_ok=True)
    copy = os.path.join(STATE_DIR, "run.yaml")
    with open(copy, "w") as f:
        f.write(text)
    return os.path.relpath(copy, ROOT)


def case_names(paths: dict, packages: list) -> list:
    return packages or sorted(os.listdir(paths["base_dir"]))


# --- the active run ----------------------------------------------------------

def active_run():
    """The recorded active run, with alive=False when its process is gone, and
    alive=None when it runs on another host (e.g. seen through a mount)."""
    try:
        with open(ACTIVE) as f:
            run = json.load(f)
    except (OSError, ValueError):
        return None
    if run.get("host", socket.gethostname()) != socket.gethostname():
        run["alive"] = None
        return run
    try:
        os.kill(run["pid"], 0)
        run["alive"] = True
    except OSError:
        run["alive"] = False
    return run


def elsewhere(run) -> None:
    """Commands that act on a run work only on the host it runs on."""
    if run and run["alive"] is None:
        fail(f"run {run['label']} runs on {run['host']}: use this command there")


def leftovers(paths: dict, packages: list) -> list:
    """Files an interrupted run left: run_repeats.sh archives the files at the
    top of the result and log directories when a run ends."""
    files = [p for d in (paths["result_dir"], paths["log_dir"]) if os.path.isdir(d)
             for p in sorted(glob.glob(os.path.join(d, "*"))) if os.path.isfile(p)]
    files += [p for p in (os.path.join(ROOT, "data", "case_study", f"{pkg}_diff.log")
                          for pkg in case_names(paths, packages)) if os.path.isfile(p)]
    return files


def free_name(paths: dict, name: str) -> str:
    """name, or name2, name3... when a run directory of that name exists already."""
    def taken(candidate):
        return any(os.path.exists(os.path.join(paths[d], candidate)) for d in ("result_dir", "log_dir"))
    number = 2
    candidate = name
    while taken(candidate):
        candidate, number = f"{name}{number}", number + 1
    return candidate


def archive(paths: dict, packages: list, name: str) -> tuple:
    """Move the files an interrupted run left into a new run directory: name,
    or name2, name3... so that an archive never mixes runs. Returns the
    directory's name and the files moved."""
    pilot = f"pilot_{name.removesuffix('_stopped')}.log"
    logs = glob.glob(os.path.join(LOGS_DIR, pilot)) + glob.glob(os.path.join(ROOT, pilot))
    files = leftovers(paths, packages)
    if not files and not logs:
        return name, []
    name = free_name(paths, name)
    moved = []
    for path in files:
        target = paths["result_dir"] if path.startswith(paths["result_dir"] + os.sep) else paths["log_dir"]
        os.makedirs(os.path.join(target, name), exist_ok=True)
        os.replace(path, os.path.join(target, name, os.path.basename(path)))
        moved.append(os.path.relpath(path, ROOT))
    for path in logs:
        os.makedirs(os.path.join(paths["log_dir"], name), exist_ok=True)
        os.replace(path, os.path.join(paths["log_dir"], name, os.path.basename(path)))
        moved.append(os.path.relpath(path, ROOT))
    return name, moved


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


def check_build_host(config: str, paths: dict, packages: list) -> None:
    """Local and build-recipe builds run on this host: it must be the build host
    (and not, say, a laptop that sees the repository through a mount)."""
    from tools.auto_repair import container
    from tools.auto_repair.case_type import case_environment, case_type
    from tools.auto_repair.paths import build_dirs, env_dir
    with open(os.path.join(ROOT, config)) as f:
        build = yaml.safe_load(f).get("build") or {}
    dirs, needs = build_dirs(build), []
    if (os.getenv("BENCH_BUILD_BACKEND") or build.get("backend") or "obs").lower() == "local":
        needs.append(dirs["worker_root"])
    for pkg in case_names(paths, packages):
        case = os.path.join(paths["base_dir"], pkg)
        if case_type(case) == "recipe":
            env = case_environment(case)
            if env and not os.path.isfile(os.path.join(env_dir(env), ".complete")):
                fail(f"build environment {env} of {pkg} is not set up in {env_dir(env)}: "
                     f"run make setup-env ENV={env}")
            problem = container.check({"container": container.settings(build)}, env)
            if problem:
                fail(f"{pkg}: {problem}")
    missing = sorted({p for p in needs if not os.path.isdir(p)})
    if missing:
        fail(f"this host ({socket.gethostname()}) is not the build host of {config}: "
             f"{', '.join(missing)} not found; start the run there")


def check_can_start(profile: dict, paths: dict, allow_leaks: bool = False) -> None:
    run = active_run()
    elsewhere(run)
    if run and run["alive"]:
        fail(f"run {run['label']} is active (pid {run['pid']}); stop it with `make stop` first")
    check_build_host(profile["config"], paths, profile["packages"])
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
    check_model_api(profile)
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
        json.dump(dict(record, pid=os.getpid(), pgid=os.getpgid(0), host=socket.gethostname()), f, indent=1)
    try:
        return subprocess.call(["bash", os.path.join(ROOT, "scripts", "run_repeats.sh"), spec["label"],
                                str(spec["repeats"]), spec["config"]], env=spec["env"], cwd=ROOT)
    finally:
        run = active_run()
        if run and run["pid"] == os.getpid():
            os.remove(ACTIVE)


# --- commands ----------------------------------------------------------------

def cmd_run(profile: dict, background: bool, resume: dict = None, allow_leaks: bool = False) -> None:
    check_settings(profile)
    if not profile.get("label"):
        fail("no label: set it in the config or with LABEL=...")
    paths = bench_paths(profile["config"])
    check_can_start(profile, paths, allow_leaks)
    attempts = profile.get("attempts") or (profile.get("llm") or {}).get("max_build_attempts")
    base = model_api()[0]
    spec = {"label": profile["label"], "repeats": profile["repeats"], "config": frozen_config(profile),
            "suite": profile.get("suite"), "packages": profile["packages"], "model": profile.get("model"), "provider": profile.get("provider"),
            "api_base": None if "openrouter.ai" in base else api_base(base), "attempts": attempts, "resume": resume, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            "env": run_env(profile, resume)}
    what = (f"{spec['label']}: suite {spec['suite']} ({', '.join(spec['packages'])}), "
            f"{spec['model'] or 'model of .env'}"
            f"{' on ' + spec['provider'] if spec['provider'] else ''}"
            f"{' at ' + spec['api_base'] if spec['api_base'] else ''}, {spec['attempts'] or 'default'} attempts"
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
        fail("say how many more attempts: ATTEMPTS=<n> (the config's llm.max_build_attempts is not used for a continuation)")
    check_settings(profile)
    profile["attempts"] = attempts
    paths = bench_paths(profile["config"])
    for pkg in case_names(paths, profile["packages"]):
        if not os.path.isfile(os.path.join(paths["result_dir"], source, f"{pkg}_result.json")):
            fail(f"{source} has no result for {pkg}: it was stopped before its first attempt ended "
                 f"(see {os.path.relpath(paths['result_dir'], ROOT)}/)")
    if not profile.get("label") or profile["label"] == load_profile(CONFIG_PATH, {}).get("label"):
        profile["label"] = f"{source}_cont"
    profile["repeats"] = 1
    cmd_run(profile, background, resume={"from": source, "workspace": workspace}, allow_leaks=allow_leaks)


def stop_builds(config: str, packages: list) -> None:
    """Builds, their tests and run_command_tool's commands run in sessions of
    their own: stop them too."""
    from tools.auto_repair import container
    from tools.auto_repair.local_build import _stop
    from tools.auto_repair.script_build import stop_experiments
    cfg = obs_config(config)
    for pkg in packages:
        _stop(os.path.join(cfg["script"]["stage_root"], pkg, "run", "state.json"))
        container.remove_matching(cfg, f"bench-{pkg}-")
        _stop(os.path.join(cfg["local"]["worker_root"], "runs", pkg, "state.json"))
        stop_experiments(pkg, cfg)


def cmd_stop(profile: dict) -> None:
    run = active_run()
    if not run:
        fail("no active run (see `make status`)")
    elsewhere(run)
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
    current = sorted(glob.glob(os.path.join(LOGS_DIR, f"pilot_{run['label']}_*.log")))
    name = (os.path.basename(current[-1])[len("pilot_"):-len(".log")] if current else run["label"]) + "_stopped"
    name, moved = archive(paths, packages, name)
    if os.path.exists(ACTIVE):
        os.remove(ACTIVE)
    print(f"stopped; {len(moved)} files archived as {name}" if moved else "stopped; nothing to archive")


def cmd_status(profile: dict, every: int) -> None:
    """The dashboard of scripts/dashboard.py: once, or refreshed every `every` seconds."""
    run = active_run()
    config = run["config"] if run else profile["config"]
    subprocess.call([sys.executable, os.path.join(ROOT, "scripts", "dashboard.py"), config, str(every)])


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


def cmd_check_case(profile: dict, name: str) -> None:
    sys.path.insert(0, os.path.join(ROOT, "dataset"))
    from check_case import check_case
    paths = bench_paths(profile["config"])
    results = check_case(os.path.join(paths["base_dir"], name), obs_config(profile["config"]))
    for level, message in results:
        print(f"{level:<4}  {message}")
    failed = sum(level == "FAIL" for level, _ in results)
    print(f"\n{'FAILED: ' + str(failed) + ' check(s)' if failed else 'ready to run'}")
    sys.exit(1 if failed else 0)


def cmd_new_case(profile: dict, name: str, environment: str, sources: list) -> None:
    paths = bench_paths(profile["config"])
    sys.exit(subprocess.call([sys.executable, os.path.join(ROOT, "dataset", "new_case.py"), paths["base_dir"], name,
                              "--env", environment or ""] + [a for s in sources for a in ("--source", s)]))


def cmd_fetch(profile: dict, name: str) -> None:
    """The sources of case `name` again (its manifest.json), e.g. after a clone."""
    case_dir = os.path.join(bench_paths(profile["config"])["base_dir"], name)
    sys.exit(subprocess.call([sys.executable, os.path.join(ROOT, "dataset", "new_case.py"), "--fetch", case_dir]))


def cmd_baseline(profile: dict, name: str) -> None:
    """Build case `name` as it is, without the model, and save its failure as log_failed.txt."""
    case_dir = os.path.join(bench_paths(profile["config"])["base_dir"], name)
    if not os.path.isdir(case_dir):
        sys.exit(f"error: no case {os.path.relpath(case_dir, ROOT)}")
    env = dict(os.environ, BENCH_CONFIG=os.path.join(ROOT, profile["config"]))
    sys.exit(subprocess.call([sys.executable, os.path.join(ROOT, "dataset", "recipe_baseline.py"), case_dir],
                             env=env))


def cmd_new_env(name: str) -> None:
    from tools.auto_repair import build_env
    path = build_env.new(name)
    print(f"created {os.path.relpath(path, ROOT)} from envs/env.example.yaml: keep the keys the environment "
          f"needs, then make setup-env ENV={name}")


def cmd_transcript(profile: dict, extra: list) -> None:
    paths = bench_paths(profile["config"])
    sys.exit(subprocess.call([sys.executable, os.path.join(ROOT, "scripts", "transcript.py"), paths["log_dir"]]
                             + extra))


def container_cfg(profile: dict) -> dict:
    """The container settings of the profile's config (no .env needed)."""
    from tools.auto_repair import container
    with open(os.path.join(ROOT, profile["config"])) as f:
        return {"container": container.settings(yaml.safe_load(f).get("build") or {})}


def cmd_setup_env(profile: dict, name: str) -> None:
    """Make build environment `name` from envs/<name>/env.yaml, in the user's
    own directory ($BENCH_HOME/envs/<name>), and its container image."""
    from tools.auto_repair import build_env, container
    from tools.auto_repair.paths import env_dir
    print(f"setting up environment {name} in {env_dir(name)}")
    try:
        build_env.setup(name)
        code = 0
    except subprocess.CalledProcessError as e:
        print(f"error: {' '.join(map(str, e.cmd))[:300]} failed (status {e.returncode}); fix it and run "
              "make setup-env again: what is done is kept", file=sys.stderr)
        code = 1
    cfg = container_cfg(profile)
    if code == 0:
        problem = container.runtime_problem(cfg)
        if problem:
            fail(f"{problem}; the environment is set up, its image is not")
        print(f"\n=== image {container.image(name)} ({container.RUNTIME})")
        image = container.build_image(cfg, name, os.path.join(env_dir(name), "image-packages.txt"),
                                      build_env.load(name)["system"])
        info_path = os.path.join(env_dir(name), "env.json")
        with open(info_path) as f:
            info = json.load(f)
        info["image"] = image
        with open(info_path, "w") as f:
            json.dump(info, f, indent=1)
        print(f"image {image['name']} {image['id'][:12]}: {image['base']}, {image['packages']} packages")
    sys.exit(code)


def cmd_check_env(profile: dict, name: str) -> None:
    """Load build environment `name` as a build does, in its container, and
    show what it provides."""
    from tools.auto_repair import build_env, container
    from tools.auto_repair.paths import env_dir
    if not build_env.exists(name):
        fail(f"no environment {os.path.relpath(build_env.spec_file(name), ROOT)}")
    script = build_env.env_script(name)
    cfg = container_cfg(profile)
    problem = container.check(cfg, name)
    if problem:
        fail(problem)
    print(f"in a {container.RUNTIME} container of {container.image(name)}")
    mode = cfg["container"]["build_network"]
    print(f"network of builds: {mode}" + (" (any host, every connection logged)" if mode == "log" else ""),
          flush=True)
    argv = container.command(cfg, f"bench-check-env-{os.getpid()}", name, container.framework_mounts(name),
                             {"BENCH_ENV_DIR": env_dir(name)}, env_dir(name),
                             ["bash", "-c", 'source "$1" || exit 2', "check-env", script])
    code = subprocess.call(argv, env=container.runtime_env())
    print("environment ready" if code == 0 else f"environment {name} is not usable (status {code})")
    sys.exit(code)


def cmd_archive(profile: dict, name: str) -> None:
    run = active_run()
    elsewhere(run)
    if run and run["alive"]:
        fail(f"run {run['label']} is active; stop it with `make stop`")
    paths = bench_paths(profile["config"])
    name, moved = archive(paths, profile["packages"], name)
    print(f"archived as {name}:\n" + "\n".join(f"  {p}" for p in moved) if moved else "nothing to archive")


CONFIG_PATH = os.path.join(ROOT, "bench.yaml")
# settings of the config the command line can override; attempts and
# context_chars override llm.max_build_attempts and llm.max_context_chars
PROFILE_OPTIONS = ("label", "suite", "model", "provider",
                   "attempts", "repeats", "temperature", "context_chars")


def main() -> None:
    global CONFIG_PATH
    os.chdir(ROOT)
    if sys.argv[1:2] == ["_runner"]:
        sys.exit(runner(json.load(sys.stdin)))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=CONFIG_PATH)
    for option in PROFILE_OPTIONS:
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
    check = sub.add_parser("check-case")
    check.add_argument("name")
    new = sub.add_parser("new-case")
    new.add_argument("name")
    new.add_argument("--env", default="")
    new.add_argument("--source", action="append", default=[])
    fetch = sub.add_parser("fetch")
    fetch.add_argument("name")
    baseline = sub.add_parser("baseline")
    baseline.add_argument("name")
    new_env = sub.add_parser("new-env")
    new_env.add_argument("name")
    setup_env = sub.add_parser("setup-env")
    setup_env.add_argument("name")
    check_env = sub.add_parser("check-env")
    check_env.add_argument("name")
    transcript = sub.add_parser("transcript", help="see scripts/transcript.py")
    transcript.add_argument("extra", nargs=argparse.REMAINDER)
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
    CONFIG_PATH = os.path.abspath(args.config)
    profile = load_profile(CONFIG_PATH, {k: getattr(args, k) for k in PROFILE_OPTIONS})
    if args.command == "run":
        cmd_run(profile, args.bg, allow_leaks=args.allow_leaks)
    elif args.command == "resume":
        cmd_resume(profile, args.source, args.workspace, args.bg, args.attempts, args.allow_leaks)
    elif args.command == "leaks":
        cmd_leaks(profile)
    elif args.command == "check-case":
        cmd_check_case(profile, args.name)
    elif args.command == "new-case":
        cmd_new_case(profile, args.name, args.env, args.source)
    elif args.command == "fetch":
        cmd_fetch(profile, args.name)
    elif args.command == "baseline":
        cmd_baseline(profile, args.name)
    elif args.command == "new-env":
        cmd_new_env(args.name)
    elif args.command == "setup-env":
        cmd_setup_env(profile, args.name)
    elif args.command == "check-env":
        cmd_check_env(profile, args.name)
    elif args.command == "transcript":
        cmd_transcript(profile, args.extra)
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
