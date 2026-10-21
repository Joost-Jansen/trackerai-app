"""Shared DeGiro Excel/CSV input; format detection uses content, not filename."""

import csv
import io
import math
from pathlib import Path

import pandas as pd


def read_export(path: str, *, nrows: int | None = None) -> pd.DataFrame:
    with open(path, "rb") as stream:
        signature = stream.read(8)
    if signature.startswith((b"PK", b"\xd0\xcf\x11\xe0")):
        return pd.read_excel(path, nrows=nrows)
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    header = text.splitlines()[0] if text else ""
    dialect = csv.Sniffer().sniff(header, delimiters=",;\t")
    # Preserve identifiers, blank currency-column headers, and numeric strings.
    # Domain parsers convert only numeric fields; product names stay untouched.
    return pd.read_csv(io.StringIO(text), sep=dialect.delimiter, dtype=str, nrows=nrows)


def number(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if "," in text:
        if "." in text and text.rfind(".") > text.rfind(","):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None
