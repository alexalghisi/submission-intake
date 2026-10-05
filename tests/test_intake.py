"""End to end on real Postgres and a mocked AWS (moto): S3 event, SQS batch, retries."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import boto3
import psycopg
import pytest
from moto import mock_aws

from samples.factory import Spec, email
from submission_intake.intake import Intake
from submission_intake.pipeline import Pipeline
from submission_intake.store import SubmissionStore

DATABASE_URL = os.environ.get("SUBMISSION_INTAKE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="SUBMISSION_INTAKE_TEST_DATABASE_URL is not set")
BUCKET = "submissions-inbox"


@pytest.fixture
def intake() -> Iterator[Intake]:
    assert DATABASE_URL is not None
    with mock_aws(), psycopg.connect(DATABASE_URL) as conn:
        conn.execute("DROP TABLE IF EXISTS documents, submissions")
        store = SubmissionStore(conn)
        store.migrate()
        s3 = boto3.client("s3", region_name="eu-central-1")
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "eu-central-1"})
        sqs = boto3.client("sqs", region_name="eu-central-1")
        queue_url = sqs.create_queue(QueueName="submissions")["QueueUrl"]
        yield Intake(store=store, s3=s3, sqs=sqs, queue_url=queue_url, pipeline=Pipeline())


def put_email(intake: Intake, key: str, raw: bytes) -> dict[str, Any]:
    intake.s3.put_object(Bucket=BUCKET, Key=key, Body=raw)
    return {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": key}}}]}


def raw_key(intake: Intake, record: dict[str, str]) -> str:
    row = intake.store.get(json.loads(record["body"])["submission_id"])
    assert row is not None
    return str(row["raw_key"])


def drain(intake: Intake) -> list[dict[str, str]]:
    messages = intake.sqs.receive_message(QueueUrl=intake.queue_url, MaxNumberOfMessages=10).get("Messages", [])
    return [{"messageId": m["MessageId"], "body": m["Body"]} for m in messages]


def test_an_email_becomes_a_ready_submission(intake: Intake) -> None:
    assert intake.on_email_stored(put_email(intake, "inbox/2026/10/05/msg1.eml", email(Spec()))) == {
        "created": 1,
        "duplicates": 0,
    }
    records = drain(intake)
    assert intake.on_submissions_queued({"Records": records}) == {"batchItemFailures": []}

    submission_id = json.loads(records[0]["body"])["submission_id"]
    row = intake.store.get(submission_id)
    assert row is not None
    assert row["status"] == "ready"
    assert row["result"]["fields"]["total_insured_value"]["value"] == 14_450_000
    assert [(d["filename"], d["kind"]) for d in row["documents"]] == [
        ("ACORD_application.pdf", "application"),
        ("SOV.xlsx", "sov"),
        ("loss_runs.csv", "loss_run"),
        ("(email body)", "email_body"),
    ]


def test_repeated_events_and_resent_emails_are_queued_once(intake: Intake) -> None:
    raw = email(Spec())
    event = put_email(intake, "inbox/a.eml", raw)
    intake.on_email_stored(event)
    assert intake.on_email_stored(event) == {"created": 0, "duplicates": 1}
    assert intake.on_email_stored(put_email(intake, "inbox/resent.eml", raw)) == {"created": 0, "duplicates": 1}
    assert len(drain(intake)) == 1


def test_redelivered_messages_are_not_processed_twice(intake: Intake) -> None:
    intake.on_email_stored(put_email(intake, "inbox/a.eml", email(Spec())))
    records = drain(intake)
    intake.on_submissions_queued({"Records": records})
    submission_id = json.loads(records[0]["body"])["submission_id"]
    assert intake.process(submission_id) == "skipped"
    row = intake.store.get(submission_id)
    assert row is not None and row["attempts"] == 1


def test_conflicting_documents_land_in_the_review_queue(intake: Intake) -> None:
    raw = email(Spec(application_name="Harbor Point Freight Inc", message_id="<conflict@atlasrisk.example>"))
    intake.on_email_stored(put_email(intake, "inbox/conflict.eml", raw))
    intake.on_submissions_queued({"Records": drain(intake)})
    queue = intake.store.review_queue()
    assert [r["reasons"] for r in queue] == [["documents disagree on insured_name"]]


def test_one_bad_message_fails_alone_and_can_be_retried(intake: Intake) -> None:
    intake.on_email_stored(put_email(intake, "inbox/good.eml", email(Spec())))
    intake.on_email_stored(put_email(intake, "inbox/bad.eml", email(Spec(message_id="<bad@atlasrisk.example>"))))
    records = drain(intake)
    bad = next(r for r in records if raw_key(intake, r).endswith("bad.eml"))
    intake.s3.delete_object(Bucket=BUCKET, Key="inbox/bad.eml")  # the raw email went missing

    assert intake.on_submissions_queued({"Records": records}) == {
        "batchItemFailures": [{"itemIdentifier": bad["messageId"]}]
    }
    bad_id = json.loads(bad["body"])["submission_id"]
    failed = intake.store.get(bad_id)
    assert failed is not None and failed["status"] == "failed" and "NoSuchKey" in failed["error"]

    intake.s3.put_object(Bucket=BUCKET, Key="inbox/bad.eml", Body=email(Spec(message_id="<bad@atlasrisk.example>")))
    assert intake.process(bad_id) == "ready"
