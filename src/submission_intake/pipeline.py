from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from .documents import read_attachment
from .email_parser import ParsedEmail
from .extract.spreadsheets import extract_loss_run, extract_sov
from .extract.text import TEXT_FIELDS, RulesExtractor, TextExtractor
from .merge import merge
from .models import DocKind, Document, Extraction, SubmissionResult

TEXT_KINDS = (DocKind.EMAIL_BODY, DocKind.APPLICATION, DocKind.OTHER)


@dataclass
class Pipeline:
    """
    Email in, structured submission out. Spreadsheets go through parsers, forms and prose through rules,
    and the model (when configured) only sees documents the rules couldn't fully read.
    """

    rules: TextExtractor = field(default_factory=RulesExtractor)
    llm: TextExtractor | None = None

    def documents(self, email: ParsedEmail) -> list[Document]:
        body = Document(
            id="email",
            filename="email body",
            content_type="text/plain",
            kind=DocKind.EMAIL_BODY,
            text=f"Subject: {email.subject}\nFrom: {email.sender}\n\n{email.body}",
        )
        return [body, *(read_attachment(f"att{i}", a) for i, a in enumerate(email.attachments, start=1))]

    def run(self, documents: Sequence[Document]) -> SubmissionResult:
        extractions: list[Extraction] = []
        for document in documents:
            if document.kind not in TEXT_KINDS:
                continue
            found = self.rules.extract(document)
            extractions += found
            unread = set(TEXT_FIELDS) - {e.field for e in found}
            if self.llm is not None and document.kind is not DocKind.EMAIL_BODY and unread:
                extractions += self.llm.extract(document)

        effective = _best_date(extractions)
        for document in documents:
            if document.kind is DocKind.SOV:
                extractions += extract_sov(document)
            elif document.kind is DocKind.LOSS_RUN:
                extractions += extract_loss_run(document, effective)

        return merge(extractions, {d.id: d.kind for d in documents})

    def process(self, email: ParsedEmail) -> tuple[list[Document], SubmissionResult]:
        documents = self.documents(email)
        return documents, self.run(documents)


def _best_date(extractions: Sequence[Extraction]) -> date | None:
    best: tuple[float, date] | None = None
    for e in extractions:
        if e.field == "effective_date" and isinstance(e.value, date) and (best is None or e.confidence > best[0]):
            best = (e.confidence, e.value)
    return best[1] if best else None
