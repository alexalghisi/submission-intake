"""The two AWS entry points: an email lands in S3, and a submission is processed from SQS."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote_plus

from .email_parser import parse_email
from .pipeline import Pipeline
from .store import SubmissionStore

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sqs import SQSClient

log = logging.getLogger("submission_intake")


@dataclass
class Intake:
    store: SubmissionStore
    s3: S3Client
    sqs: SQSClient
    queue_url: str
    pipeline: Pipeline

    def on_email_stored(self, event: dict[str, Any]) -> dict[str, int]:
        """S3 ObjectCreated: record the submission and queue it. A repeated event or resent email queues nothing."""
        created = duplicates = 0
        for record in event.get("Records", []):
            bucket = record["s3"]["bucket"]["name"]
            key = unquote_plus(record["s3"]["object"]["key"])
            raw = self.s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            received = self.store.record_received(parse_email(raw), f"s3://{bucket}/{key}")
            if not received.created:
                duplicates += 1
                continue
            self.sqs.send_message(QueueUrl=self.queue_url, MessageBody=json.dumps({"submission_id": received.id}))
            created += 1
        return {"created": created, "duplicates": duplicates}

    def on_submissions_queued(self, event: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
        """
        SQS batch: processes each submission and reports only the failed messages back, so SQS retries
        those and nothing else (ReportBatchItemFailures). After maxReceiveCount they go to the DLQ.
        """
        failures: list[dict[str, str]] = []
        for record in event.get("Records", []):
            submission_id = json.loads(record["body"])["submission_id"]
            try:
                self.process(submission_id)
            except Exception as error:
                log.exception("submission %s failed", submission_id)
                self.store.mark_failed(submission_id, f"{type(error).__name__}: {error}")
                failures.append({"itemIdentifier": record["messageId"]})
        return {"batchItemFailures": failures}

    def process(self, submission_id: str) -> str:
        if not self.store.claim(submission_id):
            return "skipped"  # already processed, or in progress elsewhere
        row = self.store.get(submission_id)
        assert row is not None
        bucket, key = row["raw_key"].removeprefix("s3://").split("/", 1)
        raw = self.s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        documents, result = self.pipeline.process(parse_email(raw))
        self.store.save_result(submission_id, documents, result)
        log.info("submission %s: %s %s", submission_id, result.status, result.review_reasons)
        return result.status
