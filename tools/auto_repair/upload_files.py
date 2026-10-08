import hashlib
import json
import os
import time
import requests
from requests.auth import HTTPBasicAuth
from xml.etree import ElementTree

from tools.auto_repair.obs_config import load_obs_config
from tools.auto_repair.obs_http import obs_request

NOT_SOURCES = {"log_failed.txt", "log_failed_original.txt", "manifest.json", ".last_upload.json"}


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

    # md5 of the files already committed on OBS: unchanged files are not sent again
    remote = {}
    try:
        r = obs_request("GET", base, auth=auth, timeout=600)
        if r.status_code == 200:
            remote = {e.get("name"): e.get("md5") for e in ElementTree.fromstring(r.text).iter("entry")}
    except (requests.exceptions.RequestException, ElementTree.ParseError):
        pass

    contents = {}
    for name in files:
        with open(os.path.join(package_dir, name), "rb") as f:
            contents[name] = f.read()
    md5 = {name: hashlib.md5(data).hexdigest() for name, data in contents.items()}

    def put(name):
        try:
            r = obs_request("PUT", f"{base}/{name}", params={"rev": "repository"}, data=contents[name],
                            auth=auth, timeout=1200,
                            headers={"Content-Type": "application/octet-stream"})
        except requests.exceptions.RequestException as e:
            return f"Error: upload of {name} failed: {e}"
        if r.status_code not in (200, 201):
            return f"Error: upload of {name} failed: HTTP {r.status_code}: {r.text[:300]}"
        return None

    def commit():
        filelist = ElementTree.Element("directory")
        for name in files:
            ElementTree.SubElement(filelist, "entry", name=name, md5=md5[name])
        try:
            r = obs_request("POST", base, params={"cmd": "commitfilelist", "comment": "build-bench repair"},
                            data=ElementTree.tostring(filelist), auth=auth, timeout=600)
        except requests.exceptions.RequestException as e:
            return None, f"Error: commit failed: {e}"
        if r.status_code != 200:
            return None, f"Error: commit failed: HTTP {r.status_code}: {r.text[:300]}"
        return ElementTree.fromstring(r.text), None

    sent = [name for name in files if remote.get(name) != md5[name]]
    for name in sent:
        error = put(name)
        if error:
            return error
    root, error = commit()
    if error:
        return error
    missing = [e.get("name") for e in root.iter("entry") if e.get("error")]
    if missing:
        # OBS did not have an unchanged file after all: send it and commit again
        for name in missing:
            error = put(name)
            if error:
                return error
        sent += [name for name in missing if name not in sent]
        root, error = commit()
        if error:
            return error
        missing = [e.get("name") for e in root.iter("entry") if e.get("error")]
        if missing:
            return f"Error: OBS reported missing files after commit: {missing}"

    srcmd5 = root.get("srcmd5")
    with open(os.path.join(package_dir, ".last_upload.json"), "w") as f:
        json.dump({"srcmd5": srcmd5, "rev": root.get("rev"), "time": time.time(),
                   "files": files}, f)
    return (f"Success: {len(files)} files committed to OBS {cfg['project']}/{package_name} "
            f"(rev {root.get('rev')}; {len(sent)} sent, {len(files) - len(sent)} unchanged).")
