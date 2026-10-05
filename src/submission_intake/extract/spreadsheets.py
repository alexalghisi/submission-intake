"""Deterministic parsers for tabular documents. A spreadsheet doesn't need a language model."""

from __future__ import annotations

import re
from datetime import date, timedelta

from ..models import Document, Extraction
from ..normalize import parse_date, parse_money

SOV_COLUMNS: dict[str, re.Pattern[str]] = {
    "address": re.compile(r"^(address|location address|street|premises)", re.I),
    "building": re.compile(r"(building|bldg)", re.I),
    "contents": re.compile(r"(contents|bpp|personal property)", re.I),
    "business_income": re.compile(r"(business income|\bbi\b|rents|time element)", re.I),
    "tiv": re.compile(r"(^tiv$|total insured value|total value)", re.I),
}
LOSS_COLUMNS: dict[str, re.Pattern[str]] = {
    "date": re.compile(r"(date of loss|loss date|dol|occurrence date)", re.I),
    "incurred": re.compile(r"(total incurred|^incurred$|incurred total)", re.I),
}


def _header(rows: list[list[str]], columns: dict[str, re.Pattern[str]]) -> tuple[int, dict[str, int]] | None:
    """Finds the header row: the first of the top rows that names at least two of the expected columns."""
    for index, row in enumerate(rows[:10]):
        found: dict[str, int] = {}
        for col, cell in enumerate(row):
            for name, pattern in columns.items():
                if name not in found and pattern.search(cell):
                    found[name] = col
                    break
        if len(found) >= 2:
            return index, found
    return None


def _value(row: list[str], col: int | None) -> int | None:
    if col is None or col >= len(row):
        return None
    return parse_money(row[col])


def extract_sov(document: Document) -> list[Extraction]:
    located = _header(document.rows, SOV_COLUMNS)
    if located is None:
        return []
    header_index, cols = located
    locations: list[int] = []
    for row in document.rows[header_index + 1 :]:
        address = row[cols["address"]] if "address" in cols and cols["address"] < len(row) else ""
        if not address or re.match(r"^\s*(total|grand total)\b", address, re.I):
            continue  # skip totals rows: the sum is recomputed from the locations
        tiv = _value(row, cols.get("tiv"))
        if tiv is None:
            parts = [_value(row, cols.get(k)) for k in ("building", "contents", "business_income")]
            tiv = sum(p for p in parts if p is not None)
        locations.append(tiv)
    if not locations:
        return []
    evidence = f"{len(locations)} location rows under header: {' | '.join(document.rows[header_index])}"
    return [
        Extraction(
            field="locations_count",
            value=len(locations),
            document_id=document.id,
            evidence=evidence,
            method="parser",
            confidence=1.0,
        ),
        Extraction(
            field="total_insured_value",
            value=sum(locations),
            document_id=document.id,
            evidence=evidence,
            method="parser",
            confidence=1.0,
        ),
    ]


def extract_loss_run(document: Document, effective_date: date | None) -> list[Extraction]:
    """Counts losses in the five years before the effective date (or before today when it isn't known)."""
    located = _header(document.rows, LOSS_COLUMNS)
    if located is None:
        return []
    header_index, cols = located
    end = effective_date or date.today()
    start = end - timedelta(days=5 * 365 + 1)
    count, incurred = 0, 0
    for row in document.rows[header_index + 1 :]:
        when = parse_date(row[cols["date"]]) if cols["date"] < len(row) else None
        amount = _value(row, cols.get("incurred"))
        if when is None or amount is None or not (start <= when < end):
            continue
        count += 1
        incurred += amount
    evidence = f"{count} claims dated {start.isoformat()} to {end.isoformat()}"
    return [
        Extraction(
            field="loss_count_5y",
            value=count,
            document_id=document.id,
            evidence=evidence,
            method="parser",
            confidence=1.0,
        ),
        Extraction(
            field="total_incurred_5y",
            value=incurred,
            document_id=document.id,
            evidence=evidence,
            method="parser",
            confidence=1.0,
        ),
    ]
