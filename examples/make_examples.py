"""Writes example .eml submissions to examples/: python -m examples.make_examples"""

from pathlib import Path

from samples.factory import Spec, email

HERE = Path(__file__).parent
(HERE / "harbor-point.eml").write_bytes(email(Spec()))
(HERE / "harbor-point-conflict.eml").write_bytes(
    email(Spec(application_name="Harbor Point Freight Inc", message_id="<conflict@atlasrisk.example>"))
)
print("wrote", ", ".join(p.name for p in sorted(HERE.glob("*.eml"))))
