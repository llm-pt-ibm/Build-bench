"""Monta um caso do benchmark a partir da API pública do OBS (não precisa de conta).

Baixa as fontes do projeto onde o pacote COMPILA e o log de falha da arquitetura
onde ele QUEBRA, no mesmo formato de data/case_study/x86_succeed_pro/<pacote>/.

uso: python fetch_package.py <pacote> <direcao>
     direcao: x86_64_to_ppc64le | ppc64le_to_x86_64
"""
import json
import os
import sys
import time
import requests
from xml.etree import ElementTree as ET

API = "https://api.opensuse.org/public"
PROJ = {"x86_64": "openSUSE:Factory", "ppc64le": "openSUSE:Factory:PowerPC"}


def main(pkg: str, direction: str) -> None:
    src_arch, tgt_arch = direction.split("_to_")
    src_prj, tgt_prj = PROJ[src_arch], PROJ[tgt_arch]
    out = os.path.join(os.path.dirname(__file__), "..", "data", direction, pkg)
    os.makedirs(out, exist_ok=True)

    listing = ET.fromstring(requests.get(f"{API}/source/{src_prj}/{pkg}", timeout=120).text)
    files = []
    for e in listing.iter("entry"):
        name = e.get("name")
        r = requests.get(f"{API}/source/{src_prj}/{pkg}/{name}", timeout=1200)
        r.raise_for_status()
        with open(os.path.join(out, name), "wb") as f:
            f.write(r.content)
        files.append({"name": name, "size": e.get("size")})
        print(f"  {name} ({int(e.get('size')) // 1024} KiB)")

    log = requests.get(f"{API}/build/{tgt_prj}/standard/{tgt_arch}/{pkg}/_log", timeout=600)
    log.raise_for_status()
    with open(os.path.join(out, "log_failed.txt"), "wb") as f:
        f.write(log.content)

    manifest = {
        "task": {"package": pkg, "direction": direction,
                 "source": {"project": src_prj, "arch": src_arch, "srcmd5": listing.get("srcmd5")},
                 "target": {"project": tgt_prj, "arch": tgt_arch}},
        "files": files,
        "created_at": int(time.time()),
        "version": 1,
    }
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"ok: {out} (+ log_failed.txt de {tgt_prj}/{tgt_arch})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
