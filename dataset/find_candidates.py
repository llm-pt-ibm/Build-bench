"""Packages that build on one architecture and fail on the other from the same
sources: openSUSE:Factory against its port of the other architecture, and the
Tumbleweed repositories of the devel projects in devel_projects.txt.

Usage: python dataset/find_candidates.py <arch> <arch>   (e.g. x86_64 aarch64)
Both directions go to dataset/candidates.json, with the day of the query and,
for each package, the project and repositories of the failure."""
import json
import os
import sys
import time
from xml.etree import ElementTree as ET

import requests

API = "https://api.opensuse.org/public"
HERE = os.path.dirname(os.path.abspath(__file__))
PORTS = {"x86_64": "openSUSE:Factory", "aarch64": "openSUSE:Factory:ARM", "ppc64le": "openSUSE:Factory:PowerPC"}
TUMBLEWEED = ("openSUSE_Tumbleweed", "openSUSE_Factory")
PORT_REPOS = {"aarch64": "openSUSE_Factory_ARM", "ppc64le": "openSUSE_Factory_PowerPC"}


def statuses(project: str, **params) -> dict:
    """{(repository, arch): {package: code}} of a project's builds."""
    for wait in (0, 10, 30):
        time.sleep(wait)
        try:
            r = requests.get(f"{API}/build/{project}/_result", params=params, timeout=900)
            if r.status_code == 404:
                return {}
            r.raise_for_status()
            out = {}
            for res in ET.fromstring(r.text).findall("result"):
                out.setdefault((res.get("repository"), res.get("arch")), {}).update(
                    {s.get("package"): s.get("code") for s in res.findall("status")})
            return out
        except requests.RequestException as e:
            error = e
    print(f"  {project}: {error}", file=sys.stderr)
    return {}


def factory(a: str, b: str) -> tuple:
    """Factory and its port of the other architecture: ({arch: {package: code}}, repositories)."""
    return ({x: statuses(PORTS[x], repository="standard", arch=x).get(("standard", x), {}) for x in (a, b)},
            {a: "standard", b: "standard"})


def devel(project: str, a: str, b: str):
    """The Tumbleweed builds of a devel project for both architectures, as factory(), or None."""
    codes = {}
    for repo in TUMBLEWEED + tuple(PORT_REPOS[x] for x in (a, b) if x in PORT_REPOS):
        codes.update(statuses(project, repository=repo))
    for repo in TUMBLEWEED:
        picked = {x: repo if (repo, x) in codes else PORT_REPOS.get(x) for x in (a, b)}
        if all((picked[x], x) in codes for x in (a, b)):
            return {x: codes[(picked[x], x)] for x in (a, b)}, picked
    return None


def find(a: str, b: str) -> dict:
    found = {f"{a}_to_{b}": {}, f"{b}_to_{a}": {}}
    with open(os.path.join(HERE, "devel_projects.txt")) as f:
        projects = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    for project in ["openSUSE:Factory"] + projects:
        builds = factory(a, b) if project == "openSUSE:Factory" else devel(project, a, b)
        added = [0, 0]
        if builds:
            codes, repos = builds
            for package in codes[a].keys() & codes[b].keys():
                for i, (src, tgt) in enumerate(((a, b), (b, a))):
                    if codes[src][package] == "succeeded" and codes[tgt][package] == "failed" \
                            and package not in found[f"{src}_to_{tgt}"]:
                        found[f"{src}_to_{tgt}"][package] = {"project": project, "repository": repos}
                        added[i] += 1
        print(f"{project}: +{added[0]} / +{added[1]}", file=sys.stderr)
    return found


if __name__ == "__main__":
    a, b = sys.argv[1:3]
    path = os.path.join(HERE, "candidates.json")
    data = json.load(open(path)) if os.path.isfile(path) else {}
    for direction, cases in find(a, b).items():
        data[direction] = {"queried": time.strftime("%Y-%m-%d"), "cases": dict(sorted(cases.items()))}
        print(f"{direction}: {len(cases)} candidates")
    with open(path, "w") as f:
        json.dump(data, f, indent=1)
