"""Prepara o projeto no OBS e confere o ponto de partida de cada caso.

1. Cria home:<OBS_USER>:build-bench com dois repositórios:
     x86_64  -> openSUSE:Factory/standard
     ppc64le -> openSUSE:Factory:PowerPC/standard
2. Cria cada pacote de data/<sentido>/ e sobe as fontes originais.
3. Espera o build nos dois repositórios e confere a triagem do artigo:
   tem que compilar na arquitetura de origem e falhar na de destino.
4. Desliga o repositório de origem do pacote, para cada reparo gerar só um build.

uso: python dataset/setup_obs.py [pacote ...]   (sem argumentos: todos os casos)
"""
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
from tools.auto_repair.upload_files import main_upload  # noqa: E402

DIRECTIONS = ["x86_64_to_ppc64le", "ppc64le_to_x86_64"]
REPOS = {"x86_64": ("openSUSE:Factory", "standard"), "ppc64le": ("openSUSE:Factory:PowerPC", "standard")}
FINAL = {"succeeded", "failed", "unresolvable", "broken", "excluded", "disabled"}

os.environ.setdefault("BENCH_CONFIG", "config/x86_64_to_ppc64le.yaml")
cfg = load_obs_config()
auth = HTTPBasicAuth(cfg["user"], cfg["password"])
API, PRJ = cfg["api"], cfg["project"]


def put(url, body):
    r = requests.put(url, data=body, auth=auth, timeout=120)
    if r.status_code != 200:
        sys.exit(f"ERRO {r.status_code} em PUT {url}:\n{r.text[:500]}")


def project_meta() -> str:
    repos = "".join(
        f'<repository name="{arch}"><path project="{p}" repository="{r}"/><arch>{arch}</arch></repository>'
        for arch, (p, r) in REPOS.items())
    return (f'<project name="{PRJ}"><title>Build-bench cross-ISA</title>'
            f'<description>Benchmark de reparo de build x86_64 &lt;-&gt; ppc64le</description>'
            f'<person userid="{cfg["user"]}" role="maintainer"/>'
            f'<publish><disable/></publish>{repos}</project>')


def package_meta(pkg: str, disable_repo: str = "") -> str:
    build = f'<build><disable repository="{disable_repo}"/></build>' if disable_repo else ""
    return f'<package name="{pkg}" project="{PRJ}"><title/><description/>{build}</package>'


def wait_both(pkg: str, timeout=4 * 3600) -> dict:
    deadline, codes = time.time() + timeout, {}
    time.sleep(60)  # dá tempo de o agendador ver a revisão nova
    while time.time() < deadline:
        r = requests.get(f"{API}/build/{PRJ}/_result", params={"package": pkg}, auth=auth, timeout=120)
        codes = {}
        for res in ET.fromstring(r.text).iter("result"):
            st = res.find("status")
            code = st.get("code") if st is not None else "?"
            codes[res.get("repository")] = code if res.get("dirty") != "true" else f"{code}(dirty)"
        print(f"  {time.strftime('%H:%M:%S')} {pkg}: {codes}", flush=True)
        if codes and all(c in FINAL for c in codes.values()):
            return codes
        time.sleep(60)
    return codes


def main(only: list) -> None:
    print(f"projeto {PRJ}")
    put(f"{API}/source/{PRJ}/_meta", project_meta())
    for direction in DIRECTIONS:
        src_arch, tgt_arch = direction.split("_to_")
        base = os.path.join("data", direction)
        for pkg in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            if only and pkg not in only:
                continue
            print(f"\n== {direction}: {pkg}")
            put(f"{API}/source/{PRJ}/{pkg}/_meta", package_meta(pkg))
            with tempfile.TemporaryDirectory() as tmp:  # o marcador de upload não suja data/
                work = os.path.join(tmp, pkg)
                shutil.copytree(os.path.join(base, pkg), work)
                print(" ", main_upload(pkg, work))
            codes = wait_both(pkg)
            ok = codes.get(src_arch) == "succeeded" and codes.get(tgt_arch) == "failed"
            print(f"  triagem: {src_arch}={codes.get(src_arch)} {tgt_arch}={codes.get(tgt_arch)} -> "
                  + ("CASO VÁLIDO" if ok else "CASO INVÁLIDO (não reproduz no seu projeto)"))
            if ok:
                put(f"{API}/source/{PRJ}/{pkg}/_meta", package_meta(pkg, disable_repo=src_arch))


if __name__ == "__main__":
    if not cfg["user"] or not cfg["password"]:
        sys.exit("Preencha OBS_USER e OBS_PASSWORD no .env antes.")
    main(sys.argv[1:])
