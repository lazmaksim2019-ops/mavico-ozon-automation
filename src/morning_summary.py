"""Task 2: morning Telegram summary from Task 1 CSV.

Usage:
    python src/morning_summary.py --once [--csv data/products_2026-09-03.csv] [--dry-run]
    python src/morning_summary.py --schedule            # every day at SUMMARY_TIME (.env)
    python src/morning_summary.py --setup               # discover chat_id after /start

Real-world behaviour: --schedule does a FRESH ozon_export on every run,
sends low-stock alerts (stock < LOW_STOCK_THRESHOLD), and on export failure
sends an error alert instead of staying silent. Without Telegram keys it
works in --dry-run (prints message) so the task is verifiable.
"""
from __future__ import annotations

import argparse
import csv
import html
import logging
import sys
import time
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import BASE_DIR, load_settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "logs" / "morning_summary.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("morning_summary")

TG_LIMIT = 4096


def find_latest_csv() -> Path | None:
    files = sorted((BASE_DIR / "data").glob("products_*.csv"))
    return files[-1] if files else None


def read_rows(csv_path: Path) -> list[dict]:
    with open(csv_path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _fmt_price(v: str) -> str:
    try:
        return f"{float(str(v).replace(',', '.')):g}"
    except (ValueError, TypeError):
        return str(v) if v else "—"


def _fmt_price(v: str) -> str:
    return fmt_money(v)


RU_MONTHS = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def ru_date(d) -> str:
    return f"{d.day} {RU_MONTHS[d.month]} {d.year}"


def fmt_money(v: object) -> str:
    """1000 -> '1 000', 390.5 -> '390,5', '' -> '—'."""
    try:
        f = float(str(v).replace(",", "."))
    except (ValueError, TypeError, AttributeError):
        return str(v) if v else "—"
    s = f"{f:,.2f}".replace(",", " ").rstrip("0").rstrip(".")
    return s.replace(".", ",")


def build_message(rows: list[dict], threshold: int, export_label: str = "") -> str:
    del export_label  # заголовок — человеческая дата, а не имя файла
    parsed: list[tuple[dict, int]] = []
    for r in rows:
        try:
            stock = int(float(str(r.get("stock", 0) or 0)))
        except (ValueError, TypeError):
            stock = 0
        parsed.append((r, stock))

    out_of = [(r, s) for r, s in parsed if s <= 0]
    low = [(r, s) for r, s in parsed if 0 < s < threshold]
    ok = [(r, s) for r, s in parsed if s >= threshold]

    lines = ["☀️ <b>Утренняя сводка Ozon</b>", f"📅 {html.escape(ru_date(date.today()))}", ""]
    if not parsed:
        lines.append("Товаров в кабинете пока нет — выгрузка пустая.")
    else:
        lines.append(f"<b>📦 Товары ({len(parsed)}):</b>")
        for i, (r, stock) in enumerate(parsed, 1):
            name = html.escape(str(r.get("name", "") or "—"))
            offer = html.escape(str(r.get("offer_id", "") or "—"))
            price = html.escape(fmt_money(r.get("price", "")))
            if stock <= 0:
                status = "⛔ <b>нет в наличии</b>"
            elif stock < threshold:
                status = "⚠️ <b>заканчивается</b>"
            else:
                status = "✅ в наличии"
            lines.append(f"{i}. {name}")
            lines.append(f"   Артикул: {offer} · Цена: {price} ₽ · Остаток: {stock} — {status}")
        attention = out_of + low
        if attention:
            lines += ["", f"⚠️ <b>Требуют внимания ({len(attention)}):</b>"]
            for r, stock in attention:
                name = html.escape(str(r.get("name", "") or "—"))
                reason = "закончился" if stock <= 0 else f"осталось {stock} при пороге {threshold}"
                lines.append(f"• {name} — {reason}")
    lines += [
        "",
        f"📊 Всего: {len(parsed)} · ✅ В наличии: {len(ok)}"
        f" · ⚠️ Заканчиваются: {len(low)} · ⛔ Нет в наличии: {len(out_of)}",
    ]
    return "\n".join(lines)


def send_telegram(token: str, chat_id: str, text: str, timeout: int = 20) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks: list[str] = []
    while len(text) > TG_LIMIT:
        cut = text.rfind("\n", 0, TG_LIMIT)
        cut = cut if cut > 0 else TG_LIMIT
        chunks.append(text[:cut])
        text = text[cut:]
    chunks.append(text)
    for i, part in enumerate(chunks, 1):
        last: Exception | None = None
        for attempt in range(1, 4):
            try:
                resp = requests.post(
                    url,
                    json={"chat_id": chat_id, "text": part, "parse_mode": "HTML"},
                    timeout=timeout,
                )
                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", 2))
                    log.warning("Telegram 429, sleep %.0fs (chunk %d/%d)", wait, i, len(chunks))
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                log.info("Telegram chunk %d/%d sent (message_id=%s)", i, len(chunks), resp.json().get("result", {}).get("message_id"))
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
                log.warning("Telegram send try %d failed: %s", attempt, exc)
                time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"Telegram send failed: {last}")


def setup_helper(token: str) -> None:
    """Explain how to get chat_id: check getMe + getUpdates."""
    if not token:
        print("1. Создайте бота через @BotFather -> /newbot, впишите токен в .env как TELEGRAM_BOT_TOKEN")
        print("2. Напишите боту /start, затем снова запустите: python src/morning_summary.py --setup")
        return
    me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15).json()
    print("Bot:", me)
    upd = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15).json()
    chats = {}
    for u in upd.get("result", []):
        msg = u.get("message") or u.get("my_chat_member") or {}
        chat = msg.get("chat", {})
        if chat.get("id"):
            chats[str(chat["id"])] = chat.get("title") or chat.get("username") or chat.get("first_name")
    if chats:
        print("Найденные chat_id (напишите боту /start если список пуст):")
        for cid, title in chats.items():
            print(f"  TELEGRAM_CHAT_ID={cid}  ({title})")
        print("Впишите нужный в .env")
    else:
        print("Сообщений нет. Напишите боту /start в Telegram и повторите --setup.")


def do_once(csv_path: Path | None, dry_run: bool) -> str:
    settings = load_settings(require_telegram=not dry_run)
    if csv_path is None:
        # fresh export so the morning status is never stale
        from src.ozon_export import export as run_export

        csv_path = BASE_DIR / "data" / f"products_{date.today().isoformat()}.csv"
        log.info("No --csv given, running fresh export -> %s", csv_path)
        try:
            run_export(csv_path)
        except Exception as exc:
            log.exception("Export failed")
            if not dry_run:
                send_telegram(settings.telegram_bot_token, settings.telegram_chat_id, f"❌ Утренняя выгрузка Ozon не удалась: {html.escape(str(exc))}")
            raise
    rows = read_rows(csv_path)
    msg = build_message(rows, settings.low_stock_threshold, csv_path.name)
    if dry_run:
        plain = msg.replace("<b>", "").replace("</b>", "")
        (BASE_DIR / "logs" / "last_summary.txt").write_text(plain, encoding="utf-8")
        (BASE_DIR / "logs" / "last_summary.html").write_text(msg, encoding="utf-8")
        try:
            sys.stdout.buffer.write((plain + "\n").encode("utf-8", "replace"))
            sys.stdout.buffer.flush()
        except Exception:
            log.info("summary: %s", plain.encode("ascii", "replace").decode())
        log.info("dry-run written to logs/last_summary.txt")
    else:
        send_telegram(settings.telegram_bot_token, settings.telegram_chat_id, msg)
    return msg


def main() -> None:
    ap = argparse.ArgumentParser(description="Morning Ozon summary to Telegram")
    ap.add_argument("--once", action="store_true", help="Send once and exit")
    ap.add_argument("--schedule", action="store_true", help="Run daily at SUMMARY_TIME")
    ap.add_argument("--setup", action="store_true", help="Discover TELEGRAM_CHAT_ID")
    ap.add_argument("--csv", default="", help="Use existing CSV instead of fresh export")
    ap.add_argument("--dry-run", action="store_true", help="Print message, do not send")
    args = ap.parse_args()

    if args.setup:
        from src.config import load_settings as _ls

        try:
            tok = _ls().telegram_bot_token
        except RuntimeError:
            tok = ""
        setup_helper(tok)
        return
    if args.schedule:
        settings = load_settings()
        try:
            import schedule
        except ImportError:
            raise SystemExit("pip install schedule  (см. requirements.txt)")
        log.info("Scheduler on: daily at %s, threshold=%d", settings.summary_time, settings.low_stock_threshold)
        schedule.every().day.at(settings.summary_time).do(
            do_once, csv_path=Path(args.csv) if args.csv else None, dry_run=args.dry_run
        )
        print(f"Планировщик запущен: каждый день в {settings.summary_time}. Ctrl+C для выхода.")
        while True:
            schedule.run_pending()
            time.sleep(20)
        return
    # default: once
    do_once(Path(args.csv) if args.csv else None, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
