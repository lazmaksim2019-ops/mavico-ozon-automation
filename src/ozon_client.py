"""Thin Ozon Seller API client with pagination, batching and 429-aware retries.

Verified against live docs (docs.ozon.ru/api/seller, dev.ozon.ru) and a real
test cabinet on 2026-09-03. Endpoints used:
  POST /v3/product/list        - product list, pagination via last_id
  POST /v3/product/info/list   - details batch (offer_id / name / sku / price)
  POST /v5/product/info/prices - price batch (filter.product_id + cursor)
  POST /v4/product/info/stocks - stock batch (FBS/rFBS; FBO warehouses return [])
/v1/analytics/stocks needs an extra role -> 403 on test keys, so we skip it
gracefully and treat missing stock as 0 with a warning.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterable

import requests

log = logging.getLogger(__name__)

LIST_LIMIT = 100
INFO_BATCH = 100
PRICES_BATCH = 1000
STOCKS_BATCH = 1000
MAX_RETRIES = 5
BACKOFF_BASE = 1.5


def chunked(seq: list, size: int) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


class OzonAPIError(RuntimeError):
    pass


class OzonClient:
    def __init__(self, client_id: str, api_key: str, base_url: str = "https://api-seller.ozon.ru"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {"Client-Id": client_id, "Api-Key": api_key, "Content-Type": "application/json"}
        )

    # -- low-level POST with retries -------------------------------------
    def _post(self, path: str, payload: dict, timeout: int = 30) -> dict:
        url = self.base_url + path
        last_err: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.session.post(url, json=payload, timeout=timeout)
            except requests.RequestException as exc:  # network error -> retry
                last_err = exc
                wait = BACKOFF_BASE ** attempt
                log.warning("POST %s network error (try %d/%d): %s. Sleep %.1fs", path, attempt, MAX_RETRIES, exc, wait)
                time.sleep(wait)
                continue
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else BACKOFF_BASE ** attempt
                except ValueError:
                    wait = BACKOFF_BASE ** attempt
                log.warning("POST %s 429 rate-limit (try %d/%d). Sleep %.1fs", path, attempt, MAX_RETRIES, wait)
                time.sleep(wait)
                last_err = OzonAPIError(f"429 rate limited on {path}")
                continue
            if 500 <= resp.status_code < 600:
                wait = BACKOFF_BASE ** attempt
                log.warning("POST %s %d (try %d/%d). Sleep %.1fs. Body: %s", path, resp.status_code, attempt, MAX_RETRIES, wait, resp.text[:500])
                time.sleep(wait)
                last_err = OzonAPIError(f"{resp.status_code} on {path}")
                continue
            if resp.status_code == 403:
                # permission errors (e.g. /v1/analytics/stocks) must NOT be retried
                raise OzonAPIError(f"403 on {path}: {resp.text[:500]}")
            if resp.status_code != 200:
                raise OzonAPIError(f"{resp.status_code} on {path}: {resp.text[:500]}")
            try:
                return resp.json()
            except ValueError as exc:
                raise OzonAPIError(f"Bad JSON on {path}: {resp.text[:300]}") from exc
        raise OzonAPIError(f"POST {path} failed after {MAX_RETRIES} tries: {last_err}")

    # -- high-level methods ----------------------------------------------
    def list_products(self) -> tuple[list[dict], int]:
        """All products via /v3/product/list. Returns (items, total)."""
        items: list[dict] = []
        last_id = ""
        total = 0
        page = 0
        while True:
            page += 1
            payload: dict[str, Any] = {"filter": {"visibility": "ALL"}, "limit": LIST_LIMIT}
            if last_id:
                payload["last_id"] = last_id
            data = self._post("/v3/product/list", payload)
            result = data.get("result", {})
            batch = result.get("items", [])
            total = int(result.get("total", 0) or 0)
            items.extend(batch)
            log.info("list page %d: +%d (total %d/%d)", page, len(batch), len(items), total)
            last_id = result.get("last_id", "")
            if not last_id or len(items) >= total:
                break
        return items, total

    def get_info_list(self, product_ids: list[int]) -> dict[int, dict]:
        """Batch details. Returns {product_id: {offer_id, name, sku, price}}."""
        out: dict[int, dict] = {}
        for batch in chunked(product_ids, INFO_BATCH):
            data = self._post("/v3/product/info/list", {"product_id": batch})
            for it in data.get("items", []):
                pid = int(it.get("id"))
                out[pid] = {
                    "offer_id": str(it.get("offer_id", "")),
                    "name": it.get("name", ""),
                    "sku": it.get("sku", ""),
                    "price_raw": it.get("price", ""),
                }
            log.info("info/list batch %d -> %d items", len(batch), len(data.get("items", [])))
            time.sleep(0.2)  # be nice to rate limits
        return out

    def get_prices(self, product_ids: list[int]) -> dict[int, float | None]:
        """Batch prices via /v5/product/info/prices. Returns {product_id: price}."""
        out: dict[int, float | None] = {}
        str_ids = [str(p) for p in product_ids]
        for batch in chunked(str_ids, PRICES_BATCH):
            cursor = ""
            while True:
                payload: dict[str, Any] = {"filter": {"product_id": batch}, "limit": min(len(batch), 1000)}
                if cursor:
                    payload["cursor"] = cursor
                data = self._post("/v5/product/info/prices", payload)
                result = data.get("result", data)
                for it in result.get("items", []):
                    pid = int(it.get("product_id"))
                    price_obj = it.get("price", {}) or {}
                    # prefer actual selling price, fall back through the chain
                    val = (
                        price_obj.get("marketing_seller_price")
                        or price_obj.get("price")
                        or price_obj.get("retail_price")
                        or 0
                    )
                    try:
                        out[pid] = float(val) if float(val) else None
                    except (TypeError, ValueError):
                        out[pid] = None
                cursor = result.get("cursor", "") or data.get("cursor", "")
                # single filter batch fits in one page; stop when page smaller than batch
                if not cursor or len(result.get("items", [])) < len(batch):
                    break
            log.info("prices batch %d done", len(batch))
            time.sleep(0.2)
        return out

    def get_stocks(self, product_ids: list[int]) -> dict[int, int]:
        """Batch stocks via /v4/product/info/stocks (FBS/rFBS). Missing -> 0."""
        out: dict[int, int] = {p: 0 for p in product_ids}
        str_ids = [str(p) for p in product_ids]
        for batch in chunked(str_ids, STOCKS_BATCH):
            cursor = ""
            while True:
                payload: dict[str, Any] = {"filter": {"product_id": batch}, "limit": min(len(batch), 1000)}
                if cursor:
                    payload["cursor"] = cursor
                try:
                    data = self._post("/v4/product/info/stocks", payload)
                except OzonAPIError as exc:
                    log.warning("stocks request failed, keep 0 for batch: %s", exc)
                    break
                result = data.get("result", data)
                for it in result.get("items", []):
                    pid = int(it.get("product_id"))
                    total = 0
                    for wh in it.get("stocks", []) or []:
                        try:
                            total += int(wh.get("present", 0) or 0)
                        except (TypeError, ValueError):
                            continue
                    out[pid] = total
                cursor = result.get("cursor", "") or data.get("cursor", "")
                if not cursor or len(result.get("items", [])) < len(batch):
                    break
            log.info("stocks batch %d done", len(batch))
            time.sleep(0.2)
        return out
