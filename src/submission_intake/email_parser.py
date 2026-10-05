from __future__ import annotations

import hashlib
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class ParsedEmail:
    message_id: str
    subject: str
    sender: str
    body: str
    attachments: list[Attachment]
    content_hash: str


def parse_email(raw: bytes) -> ParsedEmail:
    """Parses a broker's submission email. Messages without a Message-ID get one from their content hash."""
    message = BytesParser(policy=policy.default).parsebytes(raw)
    assert isinstance(message, EmailMessage)
    content_hash = hashlib.sha256(raw).hexdigest()
    body_part = message.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part is not None else ""
    attachments = []
    for part in message.iter_attachments():
        payload = part.get_payload(decode=True)
        attachments.append(
            Attachment(
                filename=part.get_filename() or "unnamed",
                content_type=part.get_content_type(),
                data=payload if isinstance(payload, bytes) else b"",
            )
        )
    message_id = str(message.get("Message-ID", "")).strip() or f"<sha256-{content_hash[:32]}>"
    return ParsedEmail(
        message_id=message_id,
        subject=str(message.get("Subject", "")),
        sender=str(message.get("From", "")),
        body=body.strip(),
        attachments=attachments,
        content_hash=content_hash,
    )
