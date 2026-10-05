from samples.factory import Spec, application_pdf, email, loss_run_csv, sov_xlsx
from submission_intake.documents import XLSX, read_attachment
from submission_intake.email_parser import Attachment, parse_email
from submission_intake.models import DocKind


def test_parses_body_and_attachments() -> None:
    parsed = parse_email(email(Spec()))
    assert parsed.message_id == "<submission-1@atlasrisk.example>"
    assert "Harbor Point Logistics, LLC" in parsed.body
    assert [a.filename for a in parsed.attachments] == ["ACORD_application.pdf", "SOV.xlsx", "loss_runs.csv"]


def test_messages_without_an_id_get_a_stable_one() -> None:
    raw = email(Spec()).replace(b"Message-ID: <submission-1@atlasrisk.example>\n", b"")
    assert parse_email(raw).message_id == parse_email(raw).message_id
    assert parse_email(raw).message_id.startswith("<sha256-")


def test_reads_and_classifies_each_kind() -> None:
    spec = Spec()
    application = read_attachment("d1", Attachment("ACORD_application.pdf", "application/pdf", application_pdf(spec)))
    sov = read_attachment("d2", Attachment("SOV.xlsx", XLSX, sov_xlsx(spec)))
    losses = read_attachment("d3", Attachment("loss_runs.csv", "text/csv", loss_run_csv(spec.claims or [])))
    assert application.kind is DocKind.APPLICATION
    assert "Named Insured: Harbor Point Logistics, LLC" in application.text
    assert sov.kind is DocKind.SOV
    assert sov.rows[1][:3] == ["Loc #", "Address", "Building Value"]
    assert losses.kind is DocKind.LOSS_RUN
    assert losses.rows[1][1] == "2023-02-14"


def test_unknown_files_are_other() -> None:
    doc = read_attachment("d4", Attachment("photo.txt", "text/plain", b"just a note"))
    assert doc.kind is DocKind.OTHER


def test_sov_layouts_without_obvious_keywords_are_still_recognised() -> None:
    spec = Spec(sov_headers=("No.", "Location Address", "Bldg", "BPP", "BI"))
    sov = read_attachment("d2", Attachment("schedule.xlsx", XLSX, sov_xlsx(spec)))
    assert sov.kind is DocKind.SOV
