"""Task 1: export seller products to CSV with export date.

Usage:
    python src/ozon_export.py [--out data/products_2026-09-03.csv] [--limit 0]

Flow: /v3/product/list (pagination) -> /v3/product/info/list (batch 100)
      -> /v5/product/info/prices + /v4/product/info/stocks (batch) -> CSV.
Keys only from .env. 429/5xx retried with backoff (see ozon_client).
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import BASE_DIR, load_settings  # noqa: E402
from src.ozon_client import OzonClient  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "logs" / "ozon_export.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("ozon_export")


def export(out_path: Path, limit: int = 0) -> Path:
    settings = load_settings()
    client = OzonClient(settings.ozon_client_id, settings.ozon_api_key, settings.ozon_base_url)

    items, total = client.list_products()
    log.info("list done: got %d items, total=%d", len(items), total)
    if limit and len(items) > limit:
        items = items[:limit]
        log.info("debug --limit applied: %d items", len(items))

    product_ids = [int(x["product_id"]) for x in items]
    offer_by_pid = {int(x["product_id"]): str(x.get("offer_id", "")) for x in items}

    if not product_ids:
        log.warning("Cabinet is empty (total=0). Writing CSV with header only.")
        info: dict[int, dict] = {}
        prices: dict[int, float | None] = {}
        stocks: dict[int, int] = {}
    else:
        info = client.get_info_list(product_ids)
        try:
            prices = client.get_prices(product_ids)
        except Exception as exc:  # prices must not kill the whole export
            log.warning("prices failed, fallback to info/list price: %s", exc)
            prices = {}
        try:
            stocks = client.get_stocks(product_ids)
        except Exception as exc:
            log.warning("stocks failed, default 0: %s", exc)
            stocks = {p: 0 for p in product_ids}

    today = date.today().isoformat()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f, fieldnames=["offer_id", "product_id", "sku", "name", "price", "stock", "export_date"]
        )
        w.writeheader()
        for pid in product_ids:
            det = info.get(pid, {})
            price = prices.get(pid)
            if price is None:
                try:
                    price = float(str(det.get("price_raw", "") or 0) or 0) or ""
                except ValueError:
                    price = ""
            w.writerow(
                {
                    "offer_id": det.get("offer_id", offer_by_pid.get(pid, "")),
                    "product_id": pid,
                    "sku": det.get("sku", ""),
                    "name": det.get("name", ""),
                    "price": price,
                    "stock": stocks.get(pid, 0),
                    "export_date": today,
                }
            )
    log.info("CSV written: %s (%d rows)", out_path, len(product_ids))
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Export Ozon products to CSV")
    ap.add_argument("--out", default="", help="Output CSV path (default data/products_<today>.csv)")
    ap.add_argument("--limit", type=int, default=0, help="Debug: take first N products only")
    args = ap.parse_args()
    out = Path(args.out) if args.out else BASE_DIR / "data" / f"products_{date.today().isoformat()}.csv"
    try:
        export(out, limit=args.limit)
    except Exception as exc:
        log.exception("Export failed: %s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
