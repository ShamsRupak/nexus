#!/usr/bin/env python3
"""Populate Postgres with sample data from data/sample/."""

import asyncio
import csv
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "sample"

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS deals (
    id TEXT PRIMARY KEY,
    company TEXT,
    contact TEXT,
    stage TEXT,
    amount NUMERIC,
    quarter TEXT,
    close_date DATE,
    owner TEXT
);

CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT,
    company TEXT,
    plan TEXT,
    mrr NUMERIC,
    created_at DATE,
    status TEXT
);

CREATE TABLE IF NOT EXISTS support_tickets (
    id TEXT PRIMARY KEY,
    customer_id TEXT,
    subject TEXT,
    priority TEXT,
    status TEXT,
    created_at DATE,
    resolved_at DATE,
    agent TEXT
);
"""


async def seed():
    import asyncpg

    conn = await asyncpg.connect("postgresql://nexus:nexus@localhost:5432/nexus")
    await conn.execute(CREATE_TABLES)

    for table, file in [
        ("deals", "deals.csv"),
        ("customers", "customers.csv"),
        ("support_tickets", "support_tickets.csv"),
    ]:
        rows = list(csv.DictReader(open(DATA_DIR / file)))
        await conn.execute(f"TRUNCATE {table}")
        for row in rows:
            cols = ", ".join(row.keys())
            placeholders = ", ".join(f"${i+1}" for i in range(len(row)))
            vals = [v if v else None for v in row.values()]
            await conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", *vals)
        print(f"Seeded {len(rows)} rows into {table}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())
