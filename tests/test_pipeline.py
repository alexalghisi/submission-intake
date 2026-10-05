from datetime import date

from samples.factory import Spec, email
from submission_intake.email_parser import parse_email
from submission_intake.merge import merge
from submission_intake.models import DocKind, Extraction
from submission_intake.pipeline import Pipeline


def extraction(field: str, value: object, doc: str, method: str = "rules", confidence: float = 0.9) -> Extraction:
    return Extraction.model_validate(
        {
            "field": field,
            "value": value,
            "document_id": doc,
            "evidence": "x",
            "method": method,
            "confidence": confidence,
        }
    )


def test_a_clean_submission_is_ready() -> None:
    _, result = Pipeline().process(parse_email(email(Spec())))
    assert result.status == "ready"
    assert {k: v.value for k, v in result.fields.items()} == {
        "insured_name": "Harbor Point Logistics, LLC",
        "effective_date": date(2026, 11, 1),
        "mailing_address": "4100 Wharf Rd, Baltimore, MD 21224",
        "broker_name": "Atlas Risk Partners",
        "locations_count": 2,
        "total_insured_value": 14_450_000,
        "loss_count_5y": 2,
        "total_incurred_5y": 160_950,
    }
    assert result.fields["insured_name"].document_id == "att1"  # the application, not the email body


def test_names_that_differ_only_in_formatting_are_not_conflicts() -> None:
    _, result = Pipeline().process(parse_email(email(Spec(application_name="HARBOR POINT LOGISTICS LLC"))))
    assert result.conflicts == []


def test_a_different_insured_on_the_application_goes_to_review() -> None:
    _, result = Pipeline().process(parse_email(email(Spec(application_name="Harbor Point Freight Inc"))))
    assert result.status == "needs_review"
    assert result.review_reasons == ["documents disagree on insured_name"]
    assert [e.value for e in result.conflicts[0].values] == ["Harbor Point Freight Inc", "Harbor Point Logistics, LLC"]


def test_missing_documents_are_reported() -> None:
    raw = email(Spec(claims=None))
    _, result = Pipeline().process(parse_email(raw))
    assert "loss_count_5y" not in result.fields
    assert result.status == "ready"  # loss runs are useful but not required


def test_merge_prefers_forms_and_parsers_and_flags_low_confidence() -> None:
    kinds = {"email": DocKind.EMAIL_BODY, "app": DocKind.APPLICATION, "other": DocKind.OTHER}
    result = merge(
        [
            extraction("insured_name", "Acme", "email", confidence=0.6),
            extraction("insured_name", "Acme Inc.", "app"),
            extraction("effective_date", date(2027, 1, 1), "other", method="llm", confidence=0.6),
        ],
        kinds,
    )
    assert result.fields["insured_name"].document_id == "app"
    assert result.conflicts == []
    assert result.review_reasons == ["missing total_insured_value", "low confidence in effective_date (0.60)"]


class FailingLLM:
    calls = 0

    def extract(self, document: object) -> list[Extraction]:
        FailingLLM.calls += 1
        return []


def test_the_llm_only_sees_documents_the_rules_could_not_fully_read() -> None:
    llm = FailingLLM()
    Pipeline(llm=llm).process(parse_email(email(Spec())))
    assert FailingLLM.calls == 0  # the application had every text field
