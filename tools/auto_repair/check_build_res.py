import json
import os
import re
import time
import requests
from requests.auth import HTTPBasicAuth
from xml.etree import ElementTree

from tools.auto_repair.obs_config import load_obs_config
from tools.auto_repair.obs_http import obs_request
from tools.auto_repair.log_excerpt import error_excerpt

FINAL = {"succeeded", "failed", "unresolvable", "broken", "excluded", "disabled"}
LOG_SRCMD5 = re.compile(r"srcmd5 '([0-9a-f]{32})'")


def _get(url, auth, **params):
    r = obs_request("GET", url, auth=auth, params=params, timeout=600)
    r.raise_for_status()
    return r


def check_main(temp_dir: str, package_name: str) -> str:
    marker = os.path.join(temp_dir, ".last_upload.json")
    if not os.path.exists(marker):
        return "Build check error: no upload found in this directory. Call upload_file_to_obs_tool first."
    with open(marker) as f:
        uploaded = json.load(f)

    cfg = load_obs_config()
    if not cfg["user"] or not cfg["password"]:
        return "Build check error: OBS credentials missing (set OBS_USER and OBS_PASSWORD in .env)"
    auth = HTTPBasicAuth(cfg["user"], cfg["password"])
    build_url = f"{cfg['api']}/build/{cfg['project']}/{cfg['repository']}/{cfg['arch']}/{package_name}"
    deadline = time.time() + cfg["max_wait_seconds"]

    while time.time() < deadline:
        try:
            res = ElementTree.fromstring(_get(
                f"{cfg['api']}/build/{cfg['project']}/_result", auth,
                package=package_name, repository=cfg["repository"], arch=cfg["arch"]).text)
            result = res.find("result")
            status = result.find("status") if result is not None else None
            code = status.get("code") if status is not None else None
            details = (status.findtext("details") or "") if status is not None else ""
            dirty = result is not None and result.get("dirty") == "true"

            if code in FINAL and not dirty:
                if code in ("unresolvable", "broken", "excluded", "disabled"):
                    if time.time() - uploaded["time"] > 60:
                        return {
                            "unresolvable": f"Build unresolvable! The build can not begin: {details}",
                            "broken": f"Build broken! OBS could not process the sources: {details}",
                            "excluded": f"Build excluded! The package is excluded for {cfg['arch']}: {details}",
                            "disabled": f"Build disabled for {cfg['arch']}: {details}",
                        }[code]
                else:
                    head = _get(f"{build_url}/_log", auth, start=0, end=8192).text
                    m = LOG_SRCMD5.search(head)
                    if m is None or m.group(1) == uploaded["srcmd5"]:
                        if code == "succeeded":
                            return "Build succeeded! The build has been successfully completed."
                        log = _get(f"{build_url}/_log", auth).content
                        path = os.path.join(temp_dir, "log_failed.txt")
                        with open(path, "wb") as f:
                            f.write(log)
                        excerpt = error_excerpt(log.decode("utf-8", errors="replace"))
                        return (f"Build failed! The failed log has been updated to: {path}\n"
                                f"Key lines of the log:\n{excerpt}")
        except (requests.exceptions.RequestException, ElementTree.ParseError):
            pass
        time.sleep(cfg["check_interval"])

    return f"Build timeout! The build has not been completed within {cfg['max_wait_seconds']} seconds. Default build failed."
