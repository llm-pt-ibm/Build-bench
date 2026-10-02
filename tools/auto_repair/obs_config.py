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
        "project": user["target_project"].format(user=name),
        "repository": user["repository_name"],
        "arch": user["architecture_name"],
        "max_wait_seconds": int(info.get("obs", {}).get("max_wait_seconds", 3600)),
        "check_interval": int(info.get("obs", {}).get("check_interval", 30)),
    }
