"""
Runs the pipeline over a generated, labelled set of submissions and reports field accuracy and routing.

    python -m evals.run_evals            # print the report
    python -m evals.run_evals 0.98       # also exit 1 if field accuracy drops below 98%
"""

from __future__ import annotations

import sys
import time
from collections import Counter

from samples.factory import email
from samples.generate import generate
from submission_intake.email_parser import parse_email
from submission_intake.merge import same_value
from submission_intake.pipeline import Pipeline


def main(argv: list[str]) -> int:
    threshold = float(argv[0]) if argv else None
    pipeline = Pipeline()
    cases = generate()
    correct: Counter[str] = Counter()
    total: Counter[str] = Counter()
    routing_ok = 0
    misses: list[str] = []
    started = time.perf_counter()

    for case in cases:
        _, result = pipeline.process(parse_email(email(case.spec)))
        for field, want in case.expected.items():
            total[field] += 1
            got = result.fields.get(field)
            if got is not None and same_value(field, got.value, want):  # type: ignore[arg-type]
                correct[field] += 1
            else:
                misses.append(f"{case.name} {field}: expected {want!r}, got {got.value if got else None!r}")
        if result.status == case.expected_status:
            routing_ok += 1
        else:
            misses.append(
                f"{case.name} routing: expected {case.expected_status}, got {result.status} {result.review_reasons}"
            )

    elapsed = time.perf_counter() - started
    accuracy = sum(correct.values()) / sum(total.values())
    print(f"{len(cases)} submissions, {elapsed / len(cases) * 1000:.0f} ms each\n")
    print(f"{'field':<22}{'correct':>10}")
    for field in total:
        print(f"{field:<22}{correct[field]:>5}/{total[field]:<4}")
    print(f"\nfield accuracy  {accuracy:.1%}")
    print(f"routing         {routing_ok}/{len(cases)} (ready vs needs_review)")
    if misses:
        print("\nmisses:")
        for miss in misses:
            print(f"  {miss}")
    if threshold is not None and (accuracy < threshold or routing_ok < len(cases)):
        print(f"\nFAILED: below {threshold:.0%} or routing mistakes")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
