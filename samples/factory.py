"""Builds realistic broker submissions (email + PDF application + SOV workbook + loss run) for tests and evals."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from email.message import EmailMessage

import openpyxl
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


@dataclass
class Location:
    address: str
    building: int
    contents: int
    business_income: int

    @property
    def tiv(self) -> int:
        return self.building + self.contents + self.business_income


@dataclass
class Claim:
    date_of_loss: str  # ISO date
    cause: str
    incurred: int


@dataclass
class Spec:
    insured_name: str = "Harbor Point Logistics, LLC"
    application_name: str | None = None  # the name as written on the application, when it differs
    broker_name: str = "Atlas Risk Partners"
    effective_date: str = "2026-11-01"
    application_date_format: str = "%m/%d/%Y"
    mailing_address: str = "4100 Wharf Rd, Baltimore, MD 21224"
    locations: list[Location] = field(
        default_factory=lambda: [
            Location("4100 Wharf Rd, Baltimore, MD 21224", 8_500_000, 1_200_000, 900_000),
            Location("77 Pier Ave, Norfolk, VA 23510", 3_100_000, 450_000, 300_000),
        ]
    )
    sov_headers: tuple[str, ...] = ("Loc #", "Address", "Building Value", "Contents", "Business Income", "TIV")
    claims: list[Claim] | None = field(
        default_factory=lambda: [
            Claim("2023-02-14", "Water damage", 48_200),
            Claim("2024-08-03", "Wind", 112_750),
            Claim("2019-05-20", "Theft", 9_000),
        ]
    )
    message_id: str = "<submission-1@atlasrisk.example>"


def application_pdf(spec: Spec) -> bytes:
    from datetime import date

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=LETTER)
    effective = date.fromisoformat(spec.effective_date).strftime(spec.application_date_format)
    lines = [
        "COMMERCIAL INSURANCE APPLICATION",
        "",
        "APPLICANT INFORMATION",
        f"Named Insured: {spec.application_name or spec.insured_name}",
        f"Mailing Address: {spec.mailing_address}",
        "FEIN: 52-1234567        NAICS: 493110",
        "",
        "POLICY INFORMATION",
        f"Proposed Eff Date: {effective}",
        "Lines of Business: Commercial Property, General Liability",
        f"Agency: {spec.broker_name}",
    ]
    y = 740
    for line in lines:
        pdf.drawString(54, y, line)
        y -= 18
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def sov_xlsx(spec: Spec) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Statement of Values", spec.insured_name])
    sheet.append([])
    sheet.append(list(spec.sov_headers))
    for i, loc in enumerate(spec.locations, start=1):
        row: list[object] = [i, loc.address, loc.building, loc.contents, loc.business_income]
        if len(spec.sov_headers) > 5:
            row.append(loc.tiv)
        sheet.append(row)
    sheet.append(["", "Total", *([""] * (len(spec.sov_headers) - 3)), sum(loc.tiv for loc in spec.locations)])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def loss_run_csv(claims: list[Claim]) -> bytes:
    lines = ["Claim #,Date of Loss,Cause,Paid,Reserve,Total Incurred,Status"]
    for i, claim in enumerate(claims, start=1):
        paid = claim.incurred * 3 // 4
        lines.append(
            f"C-{1000 + i},{claim.date_of_loss},{claim.cause},{paid},{claim.incurred - paid},{claim.incurred},Closed"
        )
    return ("\n".join(lines) + "\n").encode()


def email(spec: Spec) -> bytes:
    message = EmailMessage()
    message["From"] = f"Dana Whitfield <dana@{spec.broker_name.split()[0].lower()}risk.example>"
    message["To"] = "submissions@carrier.example"
    message["Subject"] = f"New submission: {spec.insured_name} - Property/GL eff {spec.effective_date}"
    message["Message-ID"] = spec.message_id
    message.set_content(
        "Hi team,\n\n"
        f"Please find attached a new submission for {spec.insured_name}, "
        f"effective {spec.effective_date}. They are looking for property and GL.\n"
        "Application, SOV and loss runs attached.\n\n"
        f"Thanks,\nDana Whitfield\n{spec.broker_name}\n"
    )
    message.add_attachment(
        application_pdf(spec), maintype="application", subtype="pdf", filename="ACORD_application.pdf"
    )
    message.add_attachment(
        sov_xlsx(spec),
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="SOV.xlsx",
    )
    if spec.claims is not None:
        message.add_attachment(loss_run_csv(spec.claims), maintype="text", subtype="csv", filename="loss_runs.csv")
    return message.as_bytes()
