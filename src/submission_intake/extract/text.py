"""Field extraction from free text: labelled forms, email bodies, and an LLM for everything else."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from ..models import DocKind, Document, Extraction
from ..normalize import appears_in, parse_date, squash

TEXT_FIELDS = ("insured_name", "broker_name", "effective_date", "mailing_address")


class TextExtractor(Protocol):
    def extract(self, document: Document) -> list[Extraction]: ...


LABELS: dict[str, tuple[str, ...]] = {
    "insured_name": ("named insured", "applicant name", "insured name", "first named insured"),
    "effective_date": ("proposed eff date", "proposed effective date", "effective date", "eff date"),
    "mailing_address": ("mailing address",),
    "broker_name": ("agency", "producer", "broker"),
}
DATE_IN_TEXT = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|[A-Z][a-z]+ \d{1,2}, \d{4}|\d{1,2} [A-Z][a-z]+ \d{4})\b"
)


def _typed(field_name: str, raw: str) -> str | date | None:
    raw = raw.strip()
    if field_name == "effective_date":
        match = DATE_IN_TEXT.search(raw)
        return parse_date(match.group(1)) if match else None
    return raw or None


class RulesExtractor:
    """Reads labelled forms ('Named Insured: …') and the usual way brokers phrase a submission email."""

    def extract(self, document: Document) -> list[Extraction]:
        results: list[Extraction] = []
        confidence = 0.9 if document.kind is DocKind.APPLICATION else 0.6
        for line in document.text.splitlines():
            label, sep, rest = line.partition(":")
            if not sep:
                continue
            key = squash(label).replace(".", "")
            for field_name, labels in LABELS.items():
                if key in labels:
                    value = _typed(field_name, rest.split("  ")[0])
                    if value is not None:
                        results.append(_extraction(field_name, value, document, line.strip(), "rules", confidence))
        if document.kind is DocKind.EMAIL_BODY:
            match = re.search(r"submission for (?P<name>.+?), effective (?P<date>[^.\n]+)", document.text)
            if match:
                when = _typed("effective_date", match.group("date"))
                results.append(_extraction("insured_name", match.group("name"), document, match.group(0), "rules", 0.6))
                if when is not None:
                    results.append(_extraction("effective_date", when, document, match.group(0), "rules", 0.6))
        return results


def _extraction(
    field_name: str, value: str | date, document: Document, evidence: str, method: str, confidence: float
) -> Extraction:
    return Extraction.model_validate(
        {
            "field": field_name,
            "value": value,
            "document_id": document.id,
            "evidence": evidence,
            "method": method,
            "confidence": confidence,
        }
    )


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str) -> str: ...


SYSTEM_PROMPT = f"""You extract fields from commercial insurance submission documents.
Return JSON: {{"fields": [{{"field": <one of {list(TEXT_FIELDS)}>, "value": <string; dates as YYYY-MM-DD>,
"evidence": <a short quote copied exactly from the document that contains the value>}}]}}.
Only include fields the document states. Never guess. Never paraphrase the evidence."""


@dataclass
class LLMExtractor:
    """
    Uses a model for documents the rules can't read, but only accepts what it can verify:
    every value needs a quote that is really in the document, and the quote has to contain the value.
    Anything else is rejected and counted, so a hallucinated value never reaches an underwriter.
    """

    client: LLMClient
    max_chars: int = 20_000
    rejected: list[str] = field(default_factory=list)

    def extract(self, document: Document) -> list[Extraction]:
        user = f"Document '{document.filename}' ({document.kind}):\n\n{document.text[: self.max_chars]}"
        try:
            payload = json.loads(self.client.complete_json(SYSTEM_PROMPT, user))
            items = payload["fields"]
            assert isinstance(items, list)
        except (json.JSONDecodeError, KeyError, TypeError, AssertionError):
            self.rejected.append(f"{document.id}: malformed response")
            return []
        results: list[Extraction] = []
        for item in items:
            reason = self._check(item, document)
            if reason is not None:
                self.rejected.append(f"{document.id}: {reason}")
                continue
            value = _typed(item["field"], item["value"])
            assert value is not None
            results.append(_extraction(item["field"], value, document, item["evidence"], "llm", 0.75))
        return results

    @staticmethod
    def _check(item: object, document: Document) -> str | None:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("field", "value", "evidence")):
            return "item is not {field, value, evidence} strings"
        name, value, evidence = item["field"], item["value"], item["evidence"]
        if name not in TEXT_FIELDS:
            return f"unknown field {name!r}"
        if not appears_in(evidence, document.text):
            return f"{name}: evidence not found in document"
        typed = _typed(name, value)
        if typed is None:
            return f"{name}: unparseable value {value!r}"
        if isinstance(typed, date):
            stated = [parse_date(m) for m in DATE_IN_TEXT.findall(evidence)]
            if typed not in stated:
                return f"{name}: evidence doesn't state {typed.isoformat()}"
        elif squash(value) not in squash(evidence):
            return f"{name}: evidence doesn't contain {value!r}"
        return None
