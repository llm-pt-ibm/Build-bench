import json
import os
import sys
import time
import requests
from xml.etree import ElementTree as ET

API = "https://api.opensuse.org/public"
PROJ = {"x86_64": "openSUSE:Factory", "aarch64": "openSUSE:Factory:ARM", "ppc64le": "openSUSE:Factory:PowerPC"}


def origin(pkg: str, direction: str) -> tuple:
    """Where a case comes from: the project of its sources, and the project and
    repository of its failing log (dataset/candidates.json, else Factory)."""
    src_arch, tgt_arch = direction.split("_to_")
    try:
        with open(os.path.join(os.path.dirname(__file__), "candidates.json")) as f:
            entry = json.load(f)[direction]["cases"][pkg]
    except (OSError, ValueError, KeyError, TypeError):
        entry = None
    if entry and entry["project"] != "openSUSE:Factory":
        return entry["project"], entry["project"], entry["repository"][tgt_arch]
    return PROJ[src_arch], PROJ[tgt_arch], "standard"


def main(pkg: str, direction: str, log_pkg: str = "") -> None:
    src_arch, tgt_arch = direction.split("_to_")
    src_prj, tgt_prj, tgt_repo = origin(log_pkg or pkg, direction)
    out = os.path.join(os.path.dirname(__file__), "..", "data", direction, pkg)
    os.makedirs(out, exist_ok=True)

    # expand: the files of a package that links to another one (common in devel projects)
    listing = ET.fromstring(requests.get(f"{API}/source/{src_prj}/{pkg}", params={"expand": 1}, timeout=120).text)
    files = []
    for e in listing.iter("entry"):
        name = e.get("name")
        r = requests.get(f"{API}/source/{src_prj}/{pkg}/{name}", params={"expand": 1}, timeout=1200)
        r.raise_for_status()
        with open(os.path.join(out, name), "wb") as f:
            f.write(r.content)
        files.append({"name": name, "size": e.get("size")})
        print(f"  {name} ({int(e.get('size')) // 1024} KiB)")

    log = requests.get(f"{API}/build/{tgt_prj}/{tgt_repo}/{tgt_arch}/{log_pkg or pkg}/_log", timeout=600)
    log.raise_for_status()
    with open(os.path.join(out, "log_failed.txt"), "wb") as f:
        f.write(log.content)

    manifest = {
        "task": {"package": pkg, "direction": direction,
                 "source": {"project": src_prj, "arch": src_arch, "srcmd5": listing.get("srcmd5")},
                 "target": {"project": tgt_prj, "repository": tgt_repo, "arch": tgt_arch}},
        "files": files,
        "created_at": int(time.time()),
        "version": 1,
    }
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"ok: {out} (+ log_failed.txt from {tgt_prj}/{tgt_arch})")


if __name__ == "__main__":
    # optional third argument: package name of the failing log, e.g. a
    # multibuild flavor such as python-torch:standard
    main(*sys.argv[1:4])
