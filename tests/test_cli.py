from pathlib import Path

import pytest

from samples.factory import Spec, email
from submission_intake.cli import main


def test_prints_fields_with_their_source(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "s.eml"
    path.write_bytes(email(Spec(application_name="Harbor Point Freight Inc")))
    assert main(["process", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Total insured value   $14,450,000" in out
    assert "[SOV.xlsx, parser]" in out
    assert (
        "! insured_name: 'Harbor Point Freight Inc' (ACORD_application.pdf) vs 'Harbor Point Logistics, LLC' (email body)"
        in out
    )
    assert "NEEDS REVIEW: documents disagree on insured_name" in out
