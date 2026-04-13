#!/usr/bin/env python3
"""Populate Postgres with sample data from data/sample/."""

import asyncio
import csv
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "sample"

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS deals (
    id          INTEGER PRIMARY KEY,
    company     TEXT,
    deal_value  NUMERIC,
    stage       TEXT,
    owner       TEXT,
    created_date DATE,
    close_date  DATE,
    probability NUMERIC,
    region      TEXT
);

CREATE TABLE IF NOT EXISTS customers (
    id           INTEGER PRIMARY KEY,
    name         TEXT,
    industry     TEXT,
    plan         TEXT,
    mrr          NUMERIC,
    signup_date  DATE,
    health_score NUMERIC,
    region       TEXT,
    status       TEXT
);

CREATE TABLE IF NOT EXISTS support_tickets (
    id              INTEGER PRIMARY KEY,
    customer_id     INTEGER,
    subject         TEXT,
    priority        TEXT,
    status          TEXT,
    category        TEXT,
    created_at      DATE,
    resolved_at     DATE,
    satisfaction    INTEGER,
    assigned_agent  TEXT
);
"""


async def seed() -> None:
    import asyncpg

    conn = await asyncpg.connect("postgresql://nexus:nexus@localhost:5432/nexus")
    await conn.execute(CREATE_TABLES)

    totals: dict[str, int] = {}
    for table, filename in [
        ("deals", "deals.csv"),
        ("customers", "customers.csv"),
        ("support_tickets", "support_tickets.csv"),
    ]:
        rows = list(csv.DictReader(open(DATA_DIR / filename, encoding="utf-8")))
        await conn.execute(f"TRUNCATE {table} RESTART IDENTITY CASCADE")
        for row in rows:
            cols = ", ".join(row.keys())
            placeholders = ", ".join(f"${i + 1}" for i in range(len(row)))
            vals = [v if v != "" else None for v in row.values()]
            await conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", *vals)
        totals[table] = len(rows)

    await conn.close()
    print(
        f"Seeded {totals['deals']} deals, "
        f"{totals['customers']} customers, "
        f"{totals['support_tickets']} tickets"
    )


if __name__ == "__main__":
    asyncio.run(seed())
