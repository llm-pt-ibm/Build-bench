import hashlib
import os
import shutil
import sys
import tempfile
import time
import requests
from requests.auth import HTTPBasicAuth
from xml.etree import ElementTree as ET

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from tools.auto_repair.obs_config import load_obs_config  # noqa: E402
from tools.auto_repair.upload_files import _source_files, main_upload  # noqa: E402

REPOS = {"x86_64": ("openSUSE:Factory", "standard"), "aarch64": ("openSUSE:Factory:ARM", "standard"),
         "ppc64le": ("openSUSE:Factory:PowerPC", "standard")}
FINAL = {"succeeded", "failed", "unresolvable", "broken", "excluded", "disabled"}
# a test that hangs is stopped after 15 minutes without output, not OBS's 90
PRJCONF = "BuildFlags: logidlelimit:900\n"

cfg = load_obs_config()
auth = HTTPBasicAuth(cfg["user"], cfg["password"])
API, PRJ = cfg["api"], cfg["project"]
DIRECTION = cfg["direction"]   # the config's: BENCH_CONFIG=<config> chooses it
ARCHES = DIRECTION.split("_to_")


def put(url, body):
    r = requests.put(url, data=body, auth=auth, timeout=120)
    if r.status_code != 200:
        sys.exit(f"ERROR {r.status_code} on PUT {url}:\n{r.text[:500]}")


def project_meta() -> str:
    repos = "".join(
        f'<repository name="{arch}" rebuild="local">'   # not when a dependency changes
        f'<path project="{REPOS[arch][0]}" repository="{REPOS[arch][1]}"/>'
        f'<arch>{arch}</arch></repository>' for arch in ARCHES)
    return (f'<project name="{PRJ}"><title>Build-bench cross-ISA</title>'
            f'<description>Cross-ISA build repair benchmark {ARCHES[0]} -&gt; {ARCHES[1]}</description>'
            f'<person userid="{cfg["user"]}" role="maintainer"/>'
            f'<publish><disable/></publish>{repos}</project>')


def package_meta(pkg: str, disable_repo: str = "") -> str:
    build = f'<build><disable repository="{disable_repo}"/></build>' if disable_repo else ""
    return f'<package name="{pkg}" project="{PRJ}"><title/><description/>{build}</package>'


def wait_all(pkgs: list, timeout=12 * 3600) -> dict:
    """{package: {repository: code}} once every build of pkgs is final (or at the timeout)."""
    deadline = time.time() + timeout
    time.sleep(60)
    while True:
        try:
            r = requests.get(f"{API}/build/{PRJ}/_result", auth=auth, timeout=300)
        except requests.RequestException as e:   # e.g. a moment without DNS: the builds go on
            print(f"  {time.strftime('%H:%M:%S')} {e.__class__.__name__}; trying again", flush=True)
            time.sleep(120)
            continue
        codes = {}
        if r.status_code == 200:
            for res in ET.fromstring(r.text).iter("result"):
                for st in res.iter("status"):
                    if st.get("package") in pkgs:
                        code = st.get("code") if res.get("dirty") != "true" else f"{st.get('code')}(dirty)"
                        codes.setdefault(st.get("package"), {})[res.get("repository")] = code
        done = [p for p in pkgs if len(codes.get(p, {})) == len(ARCHES) and all(c in FINAL for c in codes[p].values())]
        print(f"  {time.strftime('%H:%M:%S')} {len(done)}/{len(pkgs)} packages built", flush=True)
        if len(done) == len(pkgs) or time.time() > deadline:
            return codes
        time.sleep(120)


def uploaded(pkg: str, folder: str) -> bool:
    """The package is on OBS with the files of folder already (a setup run again)."""
    r = requests.get(f"{API}/source/{PRJ}/{pkg}", auth=auth, timeout=120)
    if r.status_code != 200:
        return False
    remote = {e.get("name"): e.get("md5") for e in ET.fromstring(r.text).iter("entry")}
    local = {}
    for name in _source_files(folder):
        with open(os.path.join(folder, name), "rb") as f:
            local[name] = hashlib.md5(f.read()).hexdigest()
    return remote == local


def built_once(pkg: str, arch: str) -> bool:
    """The package built on arch in this project at least once: its failure does not hold."""
    r = requests.get(f"{API}/build/{PRJ}/{arch}/{arch}/_jobhistory", params={"package": pkg, "limit": 50},
                     auth=auth, timeout=120)
    return r.ok and any(j.get("code") == "succeeded" for j in ET.fromstring(r.text).iter("jobhist"))


def rebuild(pkg: str, arch: str) -> None:
    r = requests.post(f"{API}/build/{PRJ}", params={"cmd": "rebuild", "package": pkg, "arch": arch},
                      auth=auth, timeout=120)
    if r.status_code != 200:
        sys.exit(f"ERROR {r.status_code} on the rebuild of {pkg}:\n{r.text[:500]}")


def main(only: list, once: list) -> None:
    """Upload the cases, build each on both architectures, build the ones that
    fail on the target once more (not those of once, slow builds), and keep
    those whose failure repeats and that never built on the target."""
    src_arch, tgt_arch = ARCHES
    base = os.path.join("data", DIRECTION)
    pkgs = [p for p in sorted(os.listdir(base)) if os.path.isdir(os.path.join(base, p)) and (not only or p in only)]
    print(f"project {PRJ} ({DIRECTION}): {len(pkgs)} packages")
    put(f"{API}/source/{PRJ}/_meta", project_meta())
    put(f"{API}/source/{PRJ}/_config", PRJCONF)
    for pkg in pkgs:
        if uploaded(pkg, os.path.join(base, pkg)):
            print(f"  {pkg}: on OBS already", flush=True)
            continue
        put(f"{API}/source/{PRJ}/{pkg}/_meta", package_meta(pkg))
        with tempfile.TemporaryDirectory() as tmp:
            work = os.path.join(tmp, pkg)
            shutil.copytree(os.path.join(base, pkg), work)
            print(f"  {pkg}: {main_upload(pkg, work)}", flush=True)
    codes = wait_all(pkgs)
    failing = [p for p in pkgs if codes.get(p, {}).get(src_arch) == "succeeded"
               and codes.get(p, {}).get(tgt_arch) == "failed" and not built_once(p, tgt_arch)]
    twice = [p for p in failing if p not in once]
    for pkg in twice:   # the failure must repeat
        rebuild(pkg, tgt_arch)
    again = wait_all(twice) if twice else {}
    for pkg in pkgs:
        first = codes.get(pkg, {})
        second = again.get(pkg, {}).get(tgt_arch)
        ok = pkg in failing and (pkg in once or second == "failed")
        why = ("" if pkg in failing else f", does not build on {src_arch}" if first.get(src_arch) != "succeeded"
               else f", builds on {tgt_arch}" if first.get(tgt_arch) != "failed" else f", built on {tgt_arch} before")
        print(f"  triage {pkg}: {src_arch}={first.get(src_arch)} {tgt_arch}={first.get(tgt_arch)}"
              + (f", again {second}" if pkg in twice else ", built once only" if pkg in failing else "") + why
              + " -> "
              + ("VALID CASE" if ok else "INVALID CASE (does not reproduce in your project)"))
        if ok:
            put(f"{API}/source/{PRJ}/{pkg}/_meta", package_meta(pkg, disable_repo=src_arch))


if __name__ == "__main__":
    if not cfg["user"] or not cfg["password"]:
        sys.exit("Set OBS_USER and OBS_PASSWORD in .env first.")
    args = sys.argv[1:]
    once = args[args.index("--once") + 1].split(",") if "--once" in args else []
    if "--once" in args:
        del args[args.index("--once"):args.index("--once") + 2]
    main(args, once)
