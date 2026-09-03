"""Central config: loads .env and validates required keys."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

@dataclass(frozen=True)
class Settings:
    ozon_client_id: str
    ozon_api_key: str
    ozon_base_url: str
    low_stock_threshold: int
    telegram_bot_token: str
    telegram_chat_id: str
    summary_time: str

def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"Env {name} must be int, got {raw!r}")

def load_settings(require_telegram: bool = False) -> Settings:
    client_id = os.getenv("OZON_CLIENT_ID", "").strip()
    api_key = os.getenv("OZON_API_KEY", "").strip()
    base_url = os.getenv("OZON_BASE_URL", "https://api-seller.ozon.ru").strip().rstrip("/")
    if not client_id or not api_key:
        raise RuntimeError("OZON_CLIENT_ID / OZON_API_KEY missing in .env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if require_telegram and (not token or not chat_id):
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing")
    return Settings(
        ozon_client_id=client_id,
        ozon_api_key=api_key,
        ozon_base_url=base_url,
        low_stock_threshold=_int_env("LOW_STOCK_THRESHOLD", 5),
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        summary_time=os.getenv("SUMMARY_TIME", "09:00").strip(),
    )
