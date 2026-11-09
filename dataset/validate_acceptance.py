"""Check the acceptance tests of RPM cases (acceptance/<direction>/<package>/) on
the source architecture, where the distribution builds the packages: each test
package builds in the project's source repository against the distribution's
own build of the package, and must pass there (a test that fails on a working
package is wrong).

Usage: BENCH_CONFIG=<config> python dataset/validate_acceptance.py [packages]"""
import json
import os
import shutil
import sys
import tempfile
import time
from xml.etree import ElementTree as ET

import requests
from requests.auth import HTTPBasicAuth

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from tools.auto_repair.obs_config import FACTORY, load_obs_config  # noqa: E402
from tools.auto_repair.upload_files import main_upload  # noqa: E402

PUBLIC = "https://api.opensuse.org/public"
FINAL = {"succeeded", "failed", "unresolvable", "broken", "excluded", "disabled"}

cfg = load_obs_config()
auth = HTTPBasicAuth(cfg["user"], cfg["password"])
API, PRJ = cfg["api"], cfg["project"]
SRC = cfg["direction"].split("_to_")[0]
TESTS = os.path.join(ROOT, "acceptance", cfg["direction"])


def working_disturl(pkg: str) -> str:
    """The DISTURL of a working build of pkg on the source architecture: the
    project's own, which the test package then installs, else the distribution's."""
    for base, login in ((f"{API}/build/{PRJ}/{SRC}/{SRC}/{pkg}", auth),
                        (f"{PUBLIC}/build/{FACTORY[SRC]}/standard/{SRC}/{pkg}", None)):
        r = requests.get(base, auth=login, timeout=120)
        names = [b.get("filename") for b in ET.fromstring(r.text).iter("binary")] if r.ok else []
        rpm = next((n for n in names if n.endswith(".rpm") and not n.endswith(".src.rpm") and "-debug" not in n), None)
        if rpm:
            info = requests.get(f"{base}/{rpm}", params={"view": "fileinfo"}, auth=login, timeout=120)
            return ET.fromstring(info.text).findtext("disturl")
    sys.exit(f"no build of {pkg} on {SRC}")


def main(only: list) -> None:
    pkgs = sorted(p for p in os.listdir(TESTS) if os.path.isfile(os.path.join(TESTS, p, f"{p}-acceptance.spec"))
                  and (not only or p in only))
    sent = {}
    for pkg in pkgs:
        name = f"{pkg}-acceptance"
        meta = (f'<package name="{name}" project="{PRJ}"><title/><description/>'
                f'<build><disable/><enable repository="{SRC}"/></build></package>')
        requests.put(f"{API}/source/{PRJ}/{name}/_meta", data=meta, auth=auth, timeout=120).raise_for_status()
        with tempfile.TemporaryDirectory() as tmp:
            work = os.path.join(tmp, name)
            shutil.copytree(os.path.join(TESTS, pkg), work)
            with open(os.path.join(work, "expected-disturl"), "w") as f:
                f.write(working_disturl(pkg) + "\n")
            print(f"  {name}: {main_upload(name, work)}", flush=True)
            with open(os.path.join(work, ".last_upload.json")) as f:
                sent[name] = json.load(f)["srcmd5"]
    done = {}
    while len(done) < len(sent):
        time.sleep(60)
        try:
            r = requests.get(f"{API}/build/{PRJ}/_result", params={"repository": SRC}, auth=auth, timeout=300)
            for res in ET.fromstring(r.text).iter("result"):
                for st in res.iter("status"):
                    name, code = st.get("package"), st.get("code")
                    if name in sent and name not in done and code in FINAL and res.get("dirty") != "true":
                        log = "" if code != "succeeded" and code != "failed" else requests.get(
                            f"{API}/build/{PRJ}/{SRC}/{SRC}/{name}/_log", auth=auth, timeout=300).text
                        if code in ("succeeded", "failed") and f"srcmd5 '{sent[name]}'" not in log[:8192]:
                            continue
                        done[name] = (code, st.findtext("details") or "", log)
        except requests.RequestException as e:
            print(f"  {e.__class__.__name__}; trying again", flush=True)
            continue
        print(f"  {time.strftime('%H:%M:%S')} {len(done)}/{len(sent)} test packages built", flush=True)
    for name, (code, details, log) in sorted(done.items()):
        print(f"\n== {name}: {'PASSES' if code == 'succeeded' else code.upper()} {details}")
        if code != "succeeded":
            lines = [line for line in log.splitlines() if "Check failed" in line or "error" in line.lower()]
            print("\n".join(lines[-8:] or log.splitlines()[-15:]))


if __name__ == "__main__":
    main(sys.argv[1:])
