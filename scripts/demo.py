#!/usr/bin/env python3
"""Run demo scenarios against the Nexus agent pipeline."""

import asyncio
import os

os.environ.setdefault("NEXUS_ENV", "development")

DEMO_PROMPTS = [
    "Show me all deals closed in Q4 over $100k",
    "Analyze revenue trends across customer segments",
    "Create a new customer record for Initech with plan Pro",
    "Onboard new Enterprise customer Stark Industries",
    "Who has the most open support tickets?",
    "Compare MRR between Enterprise and Pro tier customers",
]


async def run_demo():
    from nexus.core.intent import IntentClassifier
    from nexus.core.planner import PlanDecomposer
    from nexus.core.executor import PlanExecutor, ApprovalRequiredError

    classifier = IntentClassifier()
    planner = PlanDecomposer()
    executor = PlanExecutor()

    for prompt in DEMO_PROMPTS:
        print(f"\n{'='*60}")
        print(f"PROMPT: {prompt}")
        print("="*60)

        intent = await classifier.classify(prompt)
        print(f"Intent: {intent.intent_type.value} (confidence={intent.confidence:.2f})")
        print(f"Risk:   {intent.risk_level.value}")
        print(f"Entities: {intent.entities}")

        plan = await planner.decompose(intent)
        print(f"Plan:   {len(plan.steps)} steps, approval_required={plan.requires_approval}")
        for step in plan.steps:
            deps = f" [deps: {step.depends_on}]" if step.depends_on else ""
            print(f"  - [{step.id}] {step.tool}: {step.description}{deps}")

        try:
            response = await executor.execute(plan)
            print(f"Answer: {response.answer}")
            print(f"Latency: {response.latency_ms:.1f}ms")
        except ApprovalRequiredError:
            print("=> PAUSED: Awaiting human approval")


if __name__ == "__main__":
    asyncio.run(run_demo())
