import json
from datetime import date

import pytest

from samples.factory import Claim, Location, Spec, loss_run_csv, sov_xlsx
from submission_intake.documents import XLSX, read_attachment
from submission_intake.email_parser import Attachment
from submission_intake.extract.spreadsheets import extract_loss_run, extract_sov
from submission_intake.extract.text import LLMExtractor, RulesExtractor
from submission_intake.models import DocKind, Document, Extraction
from submission_intake.normalize import company_key, parse_date, parse_money


def values(extractions: list[Extraction]) -> dict[str, object]:
    return {e.field: e.value for e in extractions}


def test_normalisation() -> None:
    assert parse_date("11/01/2026") == date(2026, 11, 1)
    assert parse_date("November 1, 2026") == date(2026, 11, 1)
    assert parse_money("$1,234,567.40") == 1_234_567
    assert company_key("Harbor Point Logistics, LLC") == company_key("HARBOR POINT LOGISTICS LLC.")
    assert company_key("Harbor Point Logistics") != company_key("Harbor Point Freight")


def test_sov_sums_locations_and_ignores_the_totals_row() -> None:
    sov = read_attachment("sov", Attachment("SOV.xlsx", XLSX, sov_xlsx(Spec())))
    assert values(extract_sov(sov)) == {"locations_count": 2, "total_insured_value": 14_450_000}


@pytest.mark.parametrize(
    "headers",
    [
        ("Loc #", "Address", "Building Value", "Contents", "Business Income", "TIV"),
        ("No.", "Location Address", "Bldg", "BPP", "BI"),  # no TIV column: computed from the parts
    ],
)
def test_sov_understands_common_header_variants(headers: tuple[str, ...]) -> None:
    spec = Spec(sov_headers=headers, locations=[Location("1 Main St", 1_000_000, 200_000, 50_000)])
    sov = read_attachment("sov", Attachment("SOV.xlsx", XLSX, sov_xlsx(spec)))
    assert values(extract_sov(sov)) == {"locations_count": 1, "total_insured_value": 1_250_000}


def test_loss_run_counts_five_years_before_the_effective_date() -> None:
    claims = [
        Claim("2023-02-14", "Water", 48_200),
        Claim("2024-08-03", "Wind", 112_750),
        Claim("2019-05-20", "Theft", 9_000),
    ]
    doc = read_attachment("lr", Attachment("loss_runs.csv", "text/csv", loss_run_csv(claims)))
    assert values(extract_loss_run(doc, date(2026, 11, 1))) == {"loss_count_5y": 2, "total_incurred_5y": 160_950}


def test_rules_read_labelled_applications_and_email_phrasing() -> None:
    application = Document(
        id="app",
        filename="app.pdf",
        content_type="application/pdf",
        kind=DocKind.APPLICATION,
        text="Named Insured: Harbor Point Logistics, LLC\nProposed Eff Date: 11/01/2026\nAgency: Atlas Risk Partners",
    )
    body = Document(
        id="body",
        filename="email",
        content_type="text/plain",
        kind=DocKind.EMAIL_BODY,
        text="Please find attached a new submission for Harbor Point Logistics, effective 2026-11-01. Thanks",
    )
    assert values(RulesExtractor().extract(application)) == {
        "insured_name": "Harbor Point Logistics, LLC",
        "effective_date": date(2026, 11, 1),
        "broker_name": "Atlas Risk Partners",
    }
    assert values(RulesExtractor().extract(body)) == {
        "insured_name": "Harbor Point Logistics",
        "effective_date": date(2026, 11, 1),
    }


class Scripted:
    def __init__(self, response: object) -> None:
        self.response = response if isinstance(response, str) else json.dumps(response)

    def complete_json(self, system: str, user: str) -> str:
        return self.response


NOTE = Document(
    id="note",
    filename="cover.txt",
    content_type="text/plain",
    text="Coverage should start on March 3, 2027 for Bluefin Seafoods Inc, mailing to 9 Dock St, Gloucester MA.",
)


def test_llm_values_are_kept_only_with_verbatim_evidence() -> None:
    extractor = LLMExtractor(
        Scripted(
            {
                "fields": [
                    {"field": "insured_name", "value": "Bluefin Seafoods Inc", "evidence": "for Bluefin Seafoods Inc"},
                    {"field": "effective_date", "value": "2027-03-03", "evidence": "start on March 3, 2027"},
                    {"field": "broker_name", "value": "Atlas", "evidence": "brokered by Atlas"},  # not in the text
                    {
                        "field": "mailing_address",
                        "value": "10 Dock St",
                        "evidence": "mailing to 9 Dock St",
                    },  # wrong value
                    {
                        "field": "effective_date",
                        "value": "2027-04-03",
                        "evidence": "start on March 3, 2027",
                    },  # wrong date
                    {"field": "premium", "value": "1", "evidence": "Coverage"},  # unknown field
                ]
            }
        )
    )
    assert values(extractor.extract(NOTE)) == {
        "insured_name": "Bluefin Seafoods Inc",
        "effective_date": date(2027, 3, 3),
    }
    assert extractor.rejected == [
        "note: broker_name: evidence not found in document",
        "note: mailing_address: evidence doesn't contain '10 Dock St'",
        "note: effective_date: evidence doesn't state 2027-04-03",
        "note: unknown field 'premium'",
    ]


def test_malformed_llm_output_is_rejected_not_raised() -> None:
    extractor = LLMExtractor(Scripted("Sure! Here are the fields: ..."))
    assert extractor.extract(NOTE) == []
    assert extractor.rejected == ["note: malformed response"]
