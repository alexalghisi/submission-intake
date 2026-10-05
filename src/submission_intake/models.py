from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocKind(StrEnum):
    EMAIL_BODY = "email_body"
    APPLICATION = "application"  # ACORD-style application form
    SOV = "sov"  # statement of values: one row per location
    LOSS_RUN = "loss_run"  # claims history
    OTHER = "other"


class Document(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    filename: str
    content_type: str
    kind: DocKind = DocKind.OTHER
    text: str = ""
    # Structured rows for spreadsheets and CSVs; parsers use these instead of text.
    rows: list[list[str]] = Field(default_factory=list)


Method = Literal["parser", "rules", "llm"]

FIELD_NAMES = (
    "insured_name",
    "broker_name",
    "effective_date",
    "mailing_address",
    "locations_count",
    "total_insured_value",
    "loss_count_5y",
    "total_incurred_5y",
)

REQUIRED_FIELDS = ("insured_name", "effective_date", "total_insured_value")


class Extraction(BaseModel):
    """One value for one field, from one document, with the text that supports it."""

    model_config = ConfigDict(frozen=True)

    field: str
    value: str | int | float | date
    document_id: str
    evidence: str
    method: Method
    confidence: float = Field(ge=0, le=1)


class Conflict(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    values: list[Extraction]


class SubmissionResult(BaseModel):
    fields: dict[str, Extraction]
    conflicts: list[Conflict]
    missing: list[str]
    status: Literal["ready", "needs_review"]
    review_reasons: list[str]
