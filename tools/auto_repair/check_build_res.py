import json
import os
import re
import time
import requests
from requests.auth import HTTPBasicAuth
from xml.etree import ElementTree

from tools.auto_repair.obs_config import load_obs_config

# Estados em que o OBS já decidiu o build. Todo o resto (scheduled, dispatching,
# blocked, building, signing, finished, ...) quer dizer que ainda falta esperar.
FINAL = {"succeeded", "failed", "unresolvable", "broken", "excluded", "disabled"}
# O cabeçalho do _log diz de qual revisão o build veio.
LOG_SRCMD5 = re.compile(r"srcmd5 '([0-9a-f]{32})'")


def _get(url, auth, **params):
    r = requests.get(url, auth=auth, params=params, timeout=600)
    r.raise_for_status()
    return r


def check_main(temp_dir: str, package_name: str) -> str:
    """Espera o build da ÚLTIMA revisão enviada e devolve o resultado.

    O código original aceitava qualquer estado diferente de "building" e caía
    em "failed" com o log do build anterior. Aqui o build só vale quando o
    srcmd5 no cabeçalho do log é o do último upload (.last_upload.json).
    """
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
                    # Sem log para conferir a revisão: só aceita depois de um tempo do upload.
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
                    # Sem srcmd5 no cabeçalho não há como conferir; aceita o resultado.
                    if m is None or m.group(1) == uploaded["srcmd5"]:
                        if code == "succeeded":
                            return "Build succeeded! The build has been successfully completed."
                        log = _get(f"{build_url}/_log", auth).content
                        path = os.path.join(temp_dir, "log_failed.txt")
                        with open(path, "wb") as f:
                            f.write(log)
                        return f"Build failed! The failed log has been updated to: {path}"
        except (requests.exceptions.RequestException, ElementTree.ParseError):
            pass
        time.sleep(cfg["check_interval"])

    return f"Build timeout! The build has not been completed within {cfg['max_wait_seconds']} seconds. Default build failed."
