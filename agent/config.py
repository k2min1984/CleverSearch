"""
########################################################
# Description
# CleverSearch Agent - 설정 파일 로드/저장
# %APPDATA%\CleverSearchAgent\config.json 위치에 보관하여
# exe 단일 배포 시에도 사용자별 설정이 유지된다.
########################################################
"""
import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("APPDATA") or str(Path.home())) / "CleverSearchAgent"
CONFIG_PATH = CONFIG_DIR / "config.json"
REGISTRY_PATH = CONFIG_DIR / "registered_files.txt"
LOG_PATH = CONFIG_DIR / "agent.log"

DEFAULT_CONFIG: dict = {
    "api_url": "https://localhost:8000/api/v1/index/agent-notify",
    "api_key": "",
    "verify_ssl": False,
    "folders": [],
    "extensions": ["pdf", "hwp", "hwpx", "docx", "pptx", "xlsx", "xls", "jpg", "jpeg", "png", "txt"],
    "stable_wait_seconds": 2,
    "scan_on_start": True,
}


def _ensure_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    _ensure_dir()
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    _ensure_dir()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
