import hashlib
import json
import os
import time
import requests
from requests.auth import HTTPBasicAuth
from xml.etree import ElementTree

from tools.auto_repair.obs_config import load_obs_config

NOT_SOURCES = {"log_failed.txt", "manifest.json", ".last_upload.json"}


def _source_files(package_dir: str) -> list:
    return sorted(
        f for f in os.listdir(package_dir)
        if os.path.isfile(os.path.join(package_dir, f))
        and f not in NOT_SOURCES
        and not f.startswith(".")
    )


def main_upload(package_name: str, package_dir: str) -> str:
    cfg = load_obs_config()
    if not cfg["user"] or not cfg["password"]:
        return "Error: OBS credentials missing (set OBS_USER and OBS_PASSWORD in .env)"
    auth = HTTPBasicAuth(cfg["user"], cfg["password"])
    base = f"{cfg['api']}/source/{cfg['project']}/{package_name}"

    files = _source_files(package_dir)
    if not any(f.endswith(".spec") for f in files):
        return f"Error: no .spec file in {package_dir}"

    filelist = ElementTree.Element("directory")
    for name in files:
        with open(os.path.join(package_dir, name), "rb") as f:
            data = f.read()
        try:
            r = requests.put(f"{base}/{name}", params={"rev": "repository"}, data=data,
                             auth=auth, timeout=1200,
                             headers={"Content-Type": "application/octet-stream"})
        except requests.exceptions.RequestException as e:
            return f"Error: upload of {name} failed: {e}"
        if r.status_code not in (200, 201):
            return f"Error: upload of {name} failed: HTTP {r.status_code}: {r.text[:300]}"
        ElementTree.SubElement(filelist, "entry", name=name, md5=hashlib.md5(data).hexdigest())

    try:
        r = requests.post(base, params={"cmd": "commitfilelist", "comment": "build-bench repair"},
                          data=ElementTree.tostring(filelist), auth=auth, timeout=600)
    except requests.exceptions.RequestException as e:
        return f"Error: commit failed: {e}"
    if r.status_code != 200:
        return f"Error: commit failed: HTTP {r.status_code}: {r.text[:300]}"
    root = ElementTree.fromstring(r.text)
    missing = [e.get("name") for e in root.iter("entry") if e.get("error")]
    if missing:
        return f"Error: OBS reported missing files after commit: {missing}"

    srcmd5 = root.get("srcmd5")
    with open(os.path.join(package_dir, ".last_upload.json"), "w") as f:
        json.dump({"srcmd5": srcmd5, "rev": root.get("rev"), "time": time.time(),
                   "files": files}, f)
    return f"Success: {len(files)} files uploaded to OBS {cfg['project']}/{package_name} (rev {root.get('rev')})."
