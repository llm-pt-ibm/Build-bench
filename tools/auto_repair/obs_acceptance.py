"""Acceptance tests of RPM cases built on OBS. acceptance/<direction>/<package>/
holds the spec of a test package, <package>-acceptance, which installs the
package and checks that it works. After every successful build of the package
the test package builds in the same project and repository, and the build
counts only when the test package builds too. The test package gets
expected-disturl, the DISTURL of the build to test, so that it never tests
another build of the package (an older one of the distribution). The model can
read the test, not change it."""
import json
import os
import shutil
import tempfile
import time
from xml.etree import ElementTree

from tools.auto_repair.acceptance import ACCEPTANCE_DIR, failure_message
from tools.auto_repair.log_excerpt import error_excerpt
from tools.auto_repair.obs_http import obs_request
from tools.auto_repair.upload_files import main_upload

FINAL = {"succeeded", "failed", "unresolvable", "broken", "excluded", "disabled"}


def test_dir(cfg: dict, package: str):
    path = os.path.join(ACCEPTANCE_DIR, cfg.get("direction") or "", package)
    return path if os.path.isfile(os.path.join(path, f"{package}-acceptance.spec")) else None


def disturl(cfg: dict, package: str, srcmd5: str) -> str:
    return f"obs://build.opensuse.org/{cfg['project']}/{cfg['repository']}/{srcmd5}-{package}"


def run(cfg: dict, auth, temp_dir: str, package: str, srcmd5: str) -> str:
    """The result of a successful build of package (sources srcmd5), with its acceptance test."""
    tests = test_dir(cfg, package)
    if not tests:
        return "Build succeeded! The build has been successfully completed."
    name = f"{package}-acceptance"
    meta = (f'<package name="{name}" project="{cfg["project"]}"><title/><description/>'
            f'<build><disable/><enable repository="{cfg["repository"]}"/></build></package>')
    r = obs_request("PUT", f"{cfg['api']}/source/{cfg['project']}/{name}/_meta", auth=auth, data=meta, timeout=120)
    if r.status_code != 200:
        return f"Build check error: the acceptance test package could not be created (HTTP {r.status_code})"
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, name)
        shutil.copytree(tests, work)
        with open(os.path.join(work, "expected-disturl"), "w") as f:
            f.write(disturl(cfg, package, srcmd5) + "\n")
        sent = main_upload(name, work)
        if not sent.startswith("Success"):
            return f"Build check error: the acceptance test could not be uploaded: {sent}"
        with open(os.path.join(work, ".last_upload.json")) as f:
            uploaded = json.load(f)
    code, log = wait(cfg, auth, name, uploaded)
    if code == "succeeded":
        return "Build succeeded! The build has been successfully completed and its acceptance test passed."
    path = os.path.join(temp_dir, "log_failed.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("=== the build succeeded; the build of its acceptance test "
                f"(acceptance/{cfg['direction']}/{package}/) did not:\n{log}")
    return failure_message(os.path.join(tests, f"{name}.spec"), path, error_excerpt(log))


def wait(cfg: dict, auth, name: str, uploaded: dict) -> tuple:
    """(code, log) of the test package's build of the uploaded sources."""
    base = f"{cfg['api']}/build/{cfg['project']}"
    deadline = time.time() + cfg["max_wait_seconds"]
    while time.time() < deadline:
        time.sleep(cfg["check_interval"])
        try:
            r = obs_request("GET", f"{base}/_result", auth=auth, timeout=300,
                            params={"package": name, "repository": cfg["repository"], "arch": cfg["arch"]})
            result = ElementTree.fromstring(r.text).find("result")
            status = result.find("status") if result is not None else None
            if status is None or result.get("dirty") == "true" or status.get("code") not in FINAL:
                continue
            code = status.get("code")
            if code != "succeeded" and code != "failed":
                if time.time() - uploaded["time"] > 60:
                    return code, f"{code}: {status.findtext('details') or ''}"
                continue
            log = obs_request("GET", f"{base}/{cfg['repository']}/{cfg['arch']}/{name}/_log", auth=auth,
                              timeout=600).text
            if f"srcmd5 '{uploaded['srcmd5']}'" in log[:8192]:
                return code, log
        except Exception:   # a moment without the network: the build goes on
            continue
    return "timeout", f"the acceptance test did not finish within {cfg['max_wait_seconds']} seconds"
