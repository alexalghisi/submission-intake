"""AWS Lambda handlers. Configure with DATABASE_URL and QUEUE_URL; the connection is reused across invocations."""

from __future__ import annotations

import os
from functools import cache
from typing import Any

import boto3
import psycopg

from .intake import Intake
from .pipeline import Pipeline
from .store import SubmissionStore


@cache
def _intake() -> Intake:
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    return Intake(
        store=SubmissionStore(conn),
        s3=boto3.client("s3"),
        sqs=boto3.client("sqs"),
        queue_url=os.environ["QUEUE_URL"],
        pipeline=Pipeline(),
    )


def email_stored(event: dict[str, Any], context: object) -> dict[str, int]:
    return _intake().on_email_stored(event)


def submissions_queued(event: dict[str, Any], context: object) -> dict[str, list[dict[str, str]]]:
    return _intake().on_submissions_queued(event)
