import json, sys, requests
from xml.etree import ElementTree as ET

API = "https://api.opensuse.org/public"
REPOS = {"x86_64": ("openSUSE:Factory", "standard"), "ppc64le": ("openSUSE:Factory:PowerPC", "standard")}

def codes(arch, code):
    prj, repo = REPOS[arch]
    r = requests.get(f"{API}/build/{prj}/_result", params={"repository": repo, "arch": arch, "code": code}, timeout=600)
    r.raise_for_status()
    return {s.get("package") for s in ET.fromstring(r.text).iter("status")}

ok = {a: codes(a, "succeeded") for a in REPOS}
bad = {a: codes(a, "failed") for a in REPOS}
out = {"x86_64_to_ppc64le": sorted(ok["x86_64"] & bad["ppc64le"]),
       "ppc64le_to_x86_64": sorted(ok["ppc64le"] & bad["x86_64"])}
for k, v in out.items():
    print(f"{k}: {len(v)} candidates")
    print("  ", " ".join(v[:400]))
json.dump(out, open("candidates.json", "w"), indent=1)
