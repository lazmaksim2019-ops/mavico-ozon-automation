"""Task 3: clean dirty catalog_raw.csv -> catalog_clean.csv.

Usage:
    python src/clean_catalog.py [--in data/catalog_raw.csv] [--out data/catalog_clean.csv]

Does:
  1. brand / oem / qty (+qty_unit) from `name` into separate columns
  2. price -> float (handles '1 500 руб', '1500.00', '1500р', '1 500 rub', '8 990,00', ...)
  3. drops fully-empty rows and duplicates
  4. saves catalog_clean.csv (utf-8-sig for Excel)
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import BASE_DIR  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("clean_catalog")

NBSP = "\xa0"

# --- price -----------------------------------------------------------------
PRICE_RE = re.compile(r"\d+(?:[.,]\d+)?")

def clean_price(raw: object) -> float | None:
    """'1 500 руб'->1500.0, '8 990,00'->8990.0, 'от 450 руб'->450.0, ''->None."""
    if raw is None:
        return None
    s = str(raw).strip().lower().replace(NBSP, " ")
    if not s:
        return None
    # drop currency words, keep digits / separators
    s = re.sub(r"(руб\.?|rub|р\.?|от)", " ", s)
    s = s.replace(" ", "").replace(",", ".")
    # '12 500.00' -> spaces already removed => '12500.00'; '890 руб.' => '890.'
    s = s.strip().rstrip(".")
    if not s:
        return None
    # take first numeric chunk ('40*40' in names never reaches here, only price col)
    m = PRICE_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


# --- brand -----------------------------------------------------------------
BRAND_STOPWORDS = {
    "щетки", "стеклоочистителя", "колодки", "тормозные", "тормозной", "тормозная",
    "передние", "передний", "передняя", "задние", "задний", "задняя",
    "диск", "фильтр", "масляный", "масляная", "воздушный", "салонный", "угольный",
    "автополотенце", "микрофибры", "микрофибра", "набор", "комплект", "компл",
    "пара", "серии", "series",
}

def extract_brand(name: str) -> str:
    low = name.lower()
    if "mavico" in low:
        return "Mavico"
    if re.search(r"\bdba\b", low):
        return "DBA"
    # fallback: first Title-case word that is not a product-type stopword
    for word in re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", name):
        if word.lower() in BRAND_STOPWORDS:
            continue
        if word[0].isupper():
            return word
    return ""


# --- oem -------------------------------------------------------------------
OEM_AFTER_KEYWORD = re.compile(r"oem\s*([A-Za-z0-9][A-Za-z0-9\-–— ]{3,})", re.IGNORECASE)
OEM_DASH = re.compile(r"\b\d{3,6}[-–—]\d{3,8}(?:[-–—]\d+)?\b")
OEM_LONG = re.compile(r"\b\d{7,12}\b")

def extract_oem(name: str) -> str:
    m = OEM_AFTER_KEYWORD.search(name)
    if m:
        cand = re.sub(r"[^A-Za-z0-9\-]", "", m.group(1).strip())
        if len(re.sub(r"\D", "", cand)) >= 4:
            return cand
    m = OEM_DASH.search(name)
    if m:
        return m.group(0).replace("–", "-").replace("—", "-")
    m = OEM_LONG.search(name)
    if m:
        # avoid mistaking '600' quantities: require 7+ digits (quantities are short)
        return m.group(0)
    return ""


# --- qty -------------------------------------------------------------------
KOMPLEKT_RE = re.compile(r"компл|набор|к\s*-\s*т", re.IGNORECASE)
PARA_RE = re.compile(r"\bпара\b|\bпары\b", re.IGNORECASE)
SHT_RE = re.compile(r"(\d+)\s*шт", re.IGNORECASE)
X_RE = re.compile(r"[xх]\s*(\d+)", re.IGNORECASE)
SIZE_RE = re.compile(r"\d+\s*[xх*]\s*\d+")  # '40*40' is a size, not qty

def extract_qty(name: str) -> tuple[int | None, str]:
    """Returns (qty, unit) where unit in {'шт','комплект',''}. Default (1,'шт')."""
    low = name.lower()
    is_komplekt = bool(KOMPLEKT_RE.search(low))
    # '600шт/400шт' ambiguous: two numbers, take the first, unit шт
    sht_numbers = [int(x) for x in SHT_RE.findall(name)]
    if sht_numbers:
        qty = sht_numbers[0]
        return (qty, "комплект" if is_komplekt else "шт")
    mx = X_RE.search(name)
    if mx and not SIZE_RE.search(name):
        # 'x2' style, but '40*40' excluded above
        try:
            return (int(mx.group(1)), "комплект" if is_komplekt else "шт")
        except ValueError:
            pass
    if PARA_RE.search(name):
        # 'пара' = 2 pieces sold together
        return (2, "комплект" if is_komplekt else "шт")
    if is_komplekt:
        # 'комплект' without explicit number -> 1 комплект
        return (1, "комплект")
    if re.search(r"\bшт\b", low):
        return (1, "шт")
    return (1, "шт")


def norm_offer(offer: object) -> str:
    return re.sub(r"[\s\-]", "", str(offer or "").strip().upper())


def norm_name(name: object) -> str:
    s = str(name or "").lower().replace("ё", "е")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clean_catalog(in_path: Path, out_path: Path) -> pd.DataFrame:
    df = pd.read_csv(in_path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    n_in = len(df)
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()

    # 1. drop fully empty rows (all four cols empty)
    mask_empty = (df.apply(lambda r: all(str(v).strip() == "" for v in r), axis=1))
    n_empty = int(mask_empty.sum())
    df = df.loc[~mask_empty].copy()

    # 2. parse columns
    df["brand"] = df["name"].apply(extract_brand)
    df["oem"] = df["name"].apply(extract_oem)
    qty_unit = df["name"].apply(extract_qty)
    df["qty"] = [q for q, _ in qty_unit]
    df["qty_unit"] = [u for _, u in qty_unit]
    df["price"] = df["price"].apply(clean_price)
    n_bad_price = int(((df["price"].isna()) & (df["name"] != "")).sum())

    # stock -> nullable int
    def _stock(v: object) -> int | None:
        s = str(v or "").strip()
        if not s:
            return None
        try:
            return int(float(s.replace(",", ".")))
        except ValueError:
            return None

    df["stock"] = df["stock"].apply(_stock)

    # 3. dedup: same product written differently.
    # Key = normalized offer_id + price when offer present, else normalized name + price.
    df["_norm_offer"] = df["offer_id"].apply(norm_offer)
    df["_norm_name"] = df["name"].apply(norm_name)
    df["_price_key"] = df["price"].apply(lambda v: round(float(v), 2) if pd.notna(v) else "NA")
    df["_key"] = df.apply(
        lambda r: f"{r['_norm_offer']}|{r['_price_key']}" if r["_norm_offer"] else f"NAME:{r['_norm_name']}|{r['_price_key']}",
        axis=1,
    )
    before = len(df)
    df = df.drop_duplicates(subset=["_key"], keep="first").copy()
    n_dup = before - len(df)
    df = df.drop(columns=["_norm_offer", "_norm_name", "_price_key", "_key"])

    # normalize output types: stock as int-string ('' when unknown), price as float
    def _fmt_stock(v: object) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        try:
            if pd.isna(v):
                return ""
        except (TypeError, ValueError):
            pass
        try:
            return str(int(float(str(v).replace(",", "."))))
        except (ValueError, TypeError):
            return ""

    df["stock"] = df["stock"].apply(_fmt_stock)

    # цена на выходе — всегда 2 знака после точки: '1500.00', пусто если цены нет
    df["price"] = df["price"].apply(
        lambda v: f"{float(v):.2f}" if pd.notna(v) else ""
    )

    # column order
    df = df[["offer_id", "name", "brand", "oem", "qty", "qty_unit", "price", "stock"]]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    log.info(
        "in=%d empty_removed=%d dups_removed=%d bad_price=%d out=%d -> %s",
        n_in, n_empty, n_dup, n_bad_price, len(df), out_path,
    )
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="Clean catalog_raw.csv")
    ap.add_argument("--in", dest="inp", default=str(BASE_DIR / "data" / "catalog_raw.csv"))
    ap.add_argument("--out", dest="out", default=str(BASE_DIR / "data" / "catalog_clean.csv"))
    args = ap.parse_args()
    df = clean_catalog(Path(args.inp), Path(args.out))
    print(f"OK: {len(df)} rows -> {args.out}")


if __name__ == "__main__":
    main()
