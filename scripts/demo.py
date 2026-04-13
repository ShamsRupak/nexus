#!/usr/bin/env python3
"""
Nexus Demo — 4 enterprise scenarios, no LLM or database required.

Uses:
  - Keyword-fallback intent classifier + template planner
  - FileIngestConnector for CSV data
  - VectorStoreConnector (EphemeralClient + stub embeddings) for RAG
  - Rich for coloured terminal output
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Force test mode so no LLM calls are made
os.environ.setdefault("NEXUS_ENV", "test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")

DATA_DIR = Path(__file__).parent.parent / "data" / "sample"

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    RICH = True
except ImportError:
    RICH = False

console = Console() if RICH else None


def print_header(title: str) -> None:
    if RICH and console:
        console.print(Panel(f"[bold cyan]{title}[/bold cyan]", expand=False))
    else:
        print(f"\n{'='*60}\n{title}\n{'='*60}")


def print_intent(intent) -> None:
    if RICH and console:
        console.print(
            f"  [bold]Intent:[/bold]  [green]{intent.intent_type.value}[/green]"
            f"  (confidence={intent.confidence:.2f})"
            f"  risk=[yellow]{intent.risk_level.value}[/yellow]"
        )
    else:
        print(f"  Intent: {intent.intent_type.value}  confidence={intent.confidence:.2f}")


def print_plan(plan) -> None:
    if RICH and console:
        t = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE)
        t.add_column("Step", style="dim")
        t.add_column("Tool", style="cyan")
        t.add_column("Description")
        t.add_column("Deps", style="dim")
        for s in plan.steps:
            t.add_row(s.id, s.tool, s.description, ", ".join(s.depends_on) or "—")
        console.print(t)
    else:
        for s in plan.steps:
            deps = ", ".join(s.depends_on) or "—"
            print(f"  [{s.id}] {s.tool}: {s.description}  deps={deps}")


def print_result(label: str, value) -> None:
    if RICH and console:
        console.print(f"  [bold]Result:[/bold] {value}")
    else:
        print(f"  Result: {value}")


# ---------------------------------------------------------------------------
# Demo helpers
# ---------------------------------------------------------------------------


def load_csv(filename: str) -> list[dict]:
    import csv
    path = DATA_DIR / filename
    if not path.exists():
        return []
    return list(csv.DictReader(open(path, encoding="utf-8")))


def demo_separator() -> None:
    if RICH and console:
        console.print()
    else:
        print()


# ---------------------------------------------------------------------------
# Scenario implementations
# ---------------------------------------------------------------------------


async def scenario_1() -> None:
    """Show me all deals over $100K"""
    from nexus.core.intent import IntentClassifier
    from nexus.core.planner import PlanDecomposer

    prompt = "Show me all deals over $100K"
    print_header(f'Scenario 1 — "{prompt}"')

    classifier = IntentClassifier()
    planner = PlanDecomposer()

    intent = await classifier.classify(prompt)
    plan = await planner.decompose(intent)

    print_intent(intent)
    print_plan(plan)

    # Execute: filter deals.csv
    deals = load_csv("deals.csv")
    big_deals = [d for d in deals if float(d.get("deal_value", 0)) > 100_000]
    big_deals_sorted = sorted(big_deals, key=lambda d: float(d["deal_value"]), reverse=True)

    if RICH and console:
        t = Table(show_header=True, box=box.SIMPLE)
        for col in ("id", "company", "deal_value", "stage", "owner"):
            t.add_column(col)
        for d in big_deals_sorted[:8]:
            t.add_row(d["id"], d["company"], f"${float(d['deal_value']):,.0f}", d["stage"], d["owner"])
        console.print(t)
    else:
        for d in big_deals_sorted[:8]:
            print(f"  {d['company']}: ${float(d['deal_value']):,.0f}  ({d['stage']})")

    print_result("Total", f"{len(big_deals)} deals > $100K  "
                          f"(pipeline value: ${sum(float(d['deal_value']) for d in big_deals):,.0f})")


async def scenario_2() -> None:
    """How many high priority support tickets are open?"""
    from nexus.core.intent import IntentClassifier
    from nexus.core.planner import PlanDecomposer

    prompt = "How many high priority support tickets are open?"
    print_header(f'Scenario 2 — "{prompt}"')

    classifier = IntentClassifier()
    planner = PlanDecomposer()

    intent = await classifier.classify(prompt)
    plan = await planner.decompose(intent)

    print_intent(intent)
    print_plan(plan)

    tickets = load_csv("support_tickets.csv")
    open_high = [
        t for t in tickets
        if t.get("priority", "").lower() == "high"
        and t.get("status", "").lower() in ("open", "in_progress")
    ]
    critical_open = [
        t for t in tickets
        if t.get("priority", "").lower() == "critical"
        and t.get("status", "").lower() in ("open", "in_progress")
    ]

    print_result(
        "Count",
        f"{len(open_high)} high-priority open tickets  |  "
        f"{len(critical_open)} critical open tickets",
    )

    if RICH and console:
        t = Table(show_header=True, box=box.SIMPLE)
        for col in ("id", "subject", "priority", "status", "assigned_agent"):
            t.add_column(col)
        for tk in (open_high + critical_open)[:6]:
            t.add_row(
                tk["id"], tk["subject"][:40], tk["priority"],
                tk["status"], tk.get("assigned_agent", "—")
            )
        console.print(t)


async def scenario_3() -> None:
    """Analyze customer health scores by region"""
    from nexus.core.intent import IntentClassifier
    from nexus.core.planner import PlanDecomposer
    from collections import defaultdict

    prompt = "Analyze customer health scores by region"
    print_header(f'Scenario 3 — "{prompt}"')

    classifier = IntentClassifier()
    planner = PlanDecomposer()

    intent = await classifier.classify(prompt)
    plan = await planner.decompose(intent)

    print_intent(intent)
    print_plan(plan)

    customers = load_csv("customers.csv")
    by_region: dict[str, list[float]] = defaultdict(list)
    for c in customers:
        region = c.get("region", "Unknown")
        try:
            hs = float(c.get("health_score", 0))
            by_region[region].append(hs)
        except ValueError:
            pass

    if RICH and console:
        t = Table(show_header=True, box=box.SIMPLE)
        t.add_column("Region")
        t.add_column("Customers", justify="right")
        t.add_column("Avg Health", justify="right")
        t.add_column("Min", justify="right")
        t.add_column("Max", justify="right")

        for region, scores in sorted(by_region.items()):
            avg = sum(scores) / len(scores)
            bar = "█" * int(avg * 10)
            t.add_row(
                region,
                str(len(scores)),
                f"{avg:.2f} {bar}",
                f"{min(scores):.2f}",
                f"{max(scores):.2f}",
            )
        console.print(t)
    else:
        for region, scores in sorted(by_region.items()):
            avg = sum(scores) / len(scores)
            print(f"  {region}: n={len(scores)}  avg_health={avg:.2f}")

    best_region = max(by_region, key=lambda r: sum(by_region[r]) / len(by_region[r]))
    print_result("Insight", f"Healthiest region: [bold]{best_region}[/bold]" if RICH else f"Healthiest region: {best_region}")


async def scenario_4() -> None:
    """What is our refund policy? (RAG from policies.md)"""
    from nexus.core.intent import IntentClassifier
    from nexus.core.planner import PlanDecomposer
    from nexus.connect.vector_store import Document, VectorStoreConnector

    prompt = "What is our refund policy?"
    print_header(f'Scenario 4 — "{prompt}" (RAG)')

    classifier = IntentClassifier()
    planner = PlanDecomposer()

    intent = await classifier.classify(prompt)
    plan = await planner.decompose(intent)

    print_intent(intent)
    print_plan(plan)

    # Build ephemeral vector store from policies.md
    import chromadb
    client = chromadb.EphemeralClient()
    vs = VectorStoreConnector(
        chroma_client=client,
        embed_fn=lambda texts: [
            [float(sum(ord(c) for c in t[:32]) % 100) / 100.0] * 8 for t in texts
        ],
    )

    policy_path = DATA_DIR / "policies.md"
    if policy_path.exists():
        text = policy_path.read_text(encoding="utf-8")
        doc = Document(content=text, source="policies.md", document_type="markdown")
        n_chunks = await vs.ingest([doc], collection="policies")
        if RICH and console:
            console.print(f"  [dim]Ingested {n_chunks} chunks from policies.md[/dim]")

    results = await vs.search("refund policy money-back guarantee", collection="policies", top_k=3)

    if results:
        top = results[0]
        if RICH and console:
            console.print(
                Panel(
                    top.content[:500] + ("…" if len(top.content) > 500 else ""),
                    title="[bold]Top RAG Result[/bold]",
                    subtitle=f"score={top.score:.3f}  source={top.source}",
                    border_style="green",
                )
            )
        else:
            print(f"\n  Top result (score={top.score:.3f}):")
            print(f"  {top.content[:300]}...")
    else:
        print_result("RAG", "No results found (policies not ingested)")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_demo() -> None:
    if RICH and console:
        console.print(
            Panel(
                "[bold white]NEXUS[/bold white] — Enterprise AI Agent Orchestration\n"
                "[dim]4 scenarios  •  keyword fallback  •  no LLM required[/dim]",
                style="bold blue",
                expand=False,
            )
        )

    await scenario_1()
    demo_separator()
    await scenario_2()
    demo_separator()
    await scenario_3()
    demo_separator()
    await scenario_4()

    if RICH and console:
        console.print("\n[bold green]✓ Demo complete[/bold green]\n")
    else:
        print("\n✓ Demo complete\n")


if __name__ == "__main__":
    asyncio.run(run_demo())
