"""Generates a labelled set of varied submissions: names, date formats, SOV layouts, loss histories, conflicts."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from .factory import Claim, Location, Spec

COMPANIES = [
    ("Harbor Point Logistics", "LLC"),
    ("Bluefin Seafoods", "Inc"),
    ("Granite Ridge Builders", "Corp"),
    ("Sunset Valley Orchards", "LLC"),
    ("Northwind Cold Storage", "Inc"),
    ("Copper Kettle Restaurants", "LLC"),
    ("Meridian Medical Supply", "Co"),
    ("Old Mill Lofts", "LP"),
]
BROKERS = ["Atlas Risk Partners", "Keystone Insurance Brokers", "Bridgewater & Lane", "Summit Commercial Insurance"]
STREETS = ["Wharf Rd", "Pier Ave", "Main St", "Industrial Pkwy", "Commerce Dr", "Mill St", "Harbor Blvd"]
CITIES = ["Baltimore, MD 21224", "Norfolk, VA 23510", "Savannah, GA 31401", "Tacoma, WA 98421", "Duluth, MN 55802"]
DATE_FORMATS = ["%m/%d/%Y", "%B %d, %Y", "%d %B %Y", "%Y-%m-%d"]
SOV_LAYOUTS = [
    ("Loc #", "Address", "Building Value", "Contents", "Business Income", "TIV"),
    ("No.", "Location Address", "Bldg", "BPP", "BI"),
    ("Location", "Street Address", "Building", "Contents", "Rents / BI", "Total Insured Value"),
]
CAUSES = ["Water damage", "Wind", "Theft", "Fire", "Slip and fall", "Hail", "Vandalism"]


@dataclass(frozen=True)
class Case:
    name: str
    spec: Spec
    expected: dict[str, object]
    expected_status: str


def generate(n: int = 40, seed: int = 7) -> list[Case]:
    rng = random.Random(seed)
    cases: list[Case] = []
    for i in range(n):
        base, suffix = COMPANIES[i % len(COMPANIES)]
        insured = f"{base}, {suffix}" if rng.random() < 0.5 else f"{base} {suffix}"
        effective = date(2026, 10, 1) + timedelta(days=rng.randint(15, 120))
        conflict = i % 8 == 5
        reformatted = i % 8 == 2
        application_name = None
        if conflict:
            application_name = f"{base.split()[0]} {rng.choice(['Holdings', 'Group', 'Enterprises'])} {suffix}"
        elif reformatted:
            application_name = f"{base.upper()} {suffix.upper()}."
        locations = [
            Location(
                f"{rng.randint(10, 9999)} {rng.choice(STREETS)}, {rng.choice(CITIES)}",
                rng.randrange(500_000, 20_000_000, 50_000),
                rng.randrange(50_000, 3_000_000, 10_000),
                rng.randrange(0, 1_500_000, 10_000),
            )
            for _ in range(rng.randint(1, 8))
        ]
        claims: list[Claim] | None = None
        expected_losses: dict[str, object] = {}
        if i % 6 != 4:
            claims = []
            for _ in range(rng.randint(0, 6)):
                when = effective - timedelta(days=rng.randint(30, 7 * 365))
                claims.append(Claim(when.isoformat(), rng.choice(CAUSES), rng.randrange(1_000, 250_000, 50)))
            window = [
                c for c in claims if effective - timedelta(days=5 * 365 + 1) <= date.fromisoformat(c.date_of_loss)
            ]
            expected_losses = {"loss_count_5y": len(window), "total_incurred_5y": sum(c.incurred for c in window)}
        broker = rng.choice(BROKERS)
        spec = Spec(
            insured_name=insured,
            application_name=application_name,
            broker_name=broker,
            effective_date=effective.isoformat(),
            application_date_format=rng.choice(DATE_FORMATS),
            mailing_address=locations[0].address,
            locations=locations,
            sov_headers=SOV_LAYOUTS[i % len(SOV_LAYOUTS)],
            claims=claims,
            message_id=f"<eval-{i}@{broker.split()[0].lower()}.example>",
        )
        expected: dict[str, object] = {
            "insured_name": application_name or insured,
            "broker_name": broker,
            "effective_date": effective,
            "mailing_address": locations[0].address,
            "locations_count": len(locations),
            "total_insured_value": sum(loc.tiv for loc in locations),
            **expected_losses,
        }
        cases.append(Case(f"case-{i:02d}", spec, expected, "needs_review" if conflict else "ready"))
    return cases
