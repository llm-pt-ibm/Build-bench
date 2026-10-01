"""Configuração do OBS compartilhada por upload e verificação.

O arquivo de configuração vem de BENCH_CONFIG (padrão: config/info.yaml), para
que cada sentido de migração tenha o seu. As credenciais vêm do .env
(OBS_USER / OBS_PASSWORD), e não do YAML: o servidor MCP é iniciado com um
ambiente reduzido, então ele mesmo carrega o .env.
"""
import os
import yaml
from dotenv import load_dotenv

load_dotenv(".env")


def load_obs_config() -> dict:
    with open(os.getenv("BENCH_CONFIG", "config/info.yaml"), "r") as f:
        info = yaml.safe_load(f)
    user = info["user"]
    name = os.getenv("OBS_USER") or user.get("user_name")
    return {
        "api": user["obs_api_url"].rstrip("/"),
        "user": name,
        "password": os.getenv("OBS_PASSWORD") or user.get("password"),
        # "home:{user}:build-bench" vira o projeto de quem está rodando.
        "project": user["target_project"].format(user=name),
        "repository": user["repository_name"],
        "arch": user["architecture_name"],
        "max_wait_seconds": int(info.get("obs", {}).get("max_wait_seconds", 3600)),
        "check_interval": int(info.get("obs", {}).get("check_interval", 30)),
    }
