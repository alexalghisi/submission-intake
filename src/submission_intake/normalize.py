"""Normalisation shared by extractors and conflict detection."""

from __future__ import annotations

import re
from datetime import date, datetime

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y", "%d-%b-%Y")


def parse_date(text: str) -> date | None:
    cleaned = text.strip().rstrip(".")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(text: str) -> int | None:
    cleaned = re.sub(r"[,$€£\s]", "", text.strip())
    if cleaned in ("", "-"):
        return None
    try:
        return round(float(cleaned))
    except ValueError:
        return None


_SUFFIXES = re.compile(r"\b(llc|l\.l\.c|inc|incorporated|corp|corporation|co|company|ltd|limited|lp|llp)\b\.?", re.I)


def company_key(name: str) -> str:
    """'Harbor Point Logistics, LLC' and 'HARBOR POINT LOGISTICS LLC.' compare equal; different companies don't."""
    without_suffix = _SUFFIXES.sub("", name.lower())
    return re.sub(r"[^a-z0-9]+", " ", without_suffix).strip()


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def appears_in(evidence: str, text: str) -> bool:
    """Evidence must be copied from the document (ignoring whitespace and case), not paraphrased."""
    needle = squash(evidence)
    return len(needle) >= 3 and needle in squash(text)
