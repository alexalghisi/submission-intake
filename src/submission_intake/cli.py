"""Process a submission email locally: `submission-intake process path/to/email.eml [--json]`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from .email_parser import parse_email
from .extract.text import LLMExtractor
from .models import SubmissionResult
from .pipeline import Pipeline

LABELS = {
    "insured_name": "Insured",
    "broker_name": "Broker",
    "effective_date": "Effective",
    "mailing_address": "Mailing address",
    "locations_count": "Locations",
    "total_insured_value": "Total insured value",
    "loss_count_5y": "Losses (5y)",
    "total_incurred_5y": "Incurred (5y)",
}


def _show(value: object, field: str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int) and field in ("total_insured_value", "total_incurred_5y"):
        return f"${value:,}"
    return str(value)


def render(result: SubmissionResult, filenames: dict[str, str]) -> str:
    lines = []
    for field, label in LABELS.items():
        extraction = result.fields.get(field)
        if extraction is None:
            lines.append(f"  {label:<21} —")
            continue
        source = f"{filenames.get(extraction.document_id, extraction.document_id)}, {extraction.method}"
        lines.append(f"  {label:<21} {_show(extraction.value, field):<38} [{source}]")
    for conflict in result.conflicts:
        variants = " vs ".join(
            f"{_show(e.value, conflict.field)!r} ({filenames.get(e.document_id)})" for e in conflict.values
        )
        lines.append(f"  ! {conflict.field}: {variants}")
    verdict = "READY" if result.status == "ready" else "NEEDS REVIEW: " + "; ".join(result.review_reasons)
    return "\n".join([*lines, "", f"  {verdict}"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="submission-intake")
    sub = parser.add_subparsers(dest="command", required=True)
    process = sub.add_parser("process", help="extract a submission from .eml files")
    process.add_argument("emails", nargs="+")
    process.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(argv)

    llm = None
    if os.environ.get("OPENAI_API_KEY"):
        from .openai_client import OpenAIClient

        llm = LLMExtractor(OpenAIClient(model=os.environ.get("SUBMISSION_INTAKE_MODEL", "gpt-4o-mini")))
    pipeline = Pipeline(llm=llm)

    for path in args.emails:
        with open(path, "rb") as f:
            email = parse_email(f.read())
        documents, result = pipeline.process(email)
        if args.json:
            print(json.dumps(result.model_dump(mode="json"), indent=2))
            continue
        print(f"{email.subject}\n  from {email.sender}")
        print("  documents: " + ", ".join(f"{d.filename} ({d.kind.value})" for d in documents[1:]) + "\n")
        print(render(result, {d.id: d.filename for d in documents}))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
