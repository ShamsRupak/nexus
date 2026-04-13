"""Tests for the intent classifier (10+ tests)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("NEXUS_ENV", "test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")

from nexus.core.intent import IntentClassifier
from nexus.core.types import IntentType, RiskLevel


@pytest.fixture
def classifier():
    return IntentClassifier()


# --------------------------------------------------------------------------
# Basic intent classification (keyword fallback — no LLM required)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_query_show_deals(classifier):
    result = await classifier.classify("show me all deals")
    assert result.intent_type == IntentType.QUERY


@pytest.mark.asyncio
async def test_classify_query_list(classifier):
    result = await classifier.classify("list all customers in Q4")
    assert result.intent_type == IntentType.QUERY


@pytest.mark.asyncio
async def test_classify_query_what(classifier):
    result = await classifier.classify("what are the open support tickets?")
    assert result.intent_type == IntentType.QUERY


@pytest.mark.asyncio
async def test_classify_query_how_many(classifier):
    result = await classifier.classify("how many deals closed this quarter")
    assert result.intent_type == IntentType.QUERY


@pytest.mark.asyncio
async def test_classify_action_create(classifier):
    result = await classifier.classify("create a new customer record for Acme")
    assert result.intent_type == IntentType.ACTION


@pytest.mark.asyncio
async def test_classify_action_delete(classifier):
    result = await classifier.classify("delete the deal D007 from the pipeline")
    assert result.intent_type == IntentType.ACTION


@pytest.mark.asyncio
async def test_classify_analysis(classifier):
    result = await classifier.classify("analyze revenue trends across segments")
    assert result.intent_type == IntentType.ANALYSIS


@pytest.mark.asyncio
async def test_classify_workflow_onboard(classifier):
    result = await classifier.classify("onboard new customer Acme Corp")
    assert result.intent_type == IntentType.WORKFLOW


@pytest.mark.asyncio
async def test_keyword_fallback_used_when_no_llm(classifier):
    """With sk-test key, LLM is unavailable — must use keyword fallback."""
    result = await classifier.classify("show me all active customers")
    # Keyword fallback should still return a valid ClassifiedIntent
    assert result.intent_type in IntentType.__members__.values()
    assert 0.0 <= result.confidence <= 1.0
    assert result.original_prompt == "show me all active customers"


@pytest.mark.asyncio
async def test_risk_level_high_for_delete(classifier):
    result = await classifier.classify("delete all records from the customer table")
    assert result.risk_level == RiskLevel.HIGH


@pytest.mark.asyncio
async def test_risk_level_medium_for_create(classifier):
    result = await classifier.classify("create a new customer record")
    assert result.risk_level == RiskLevel.MEDIUM


@pytest.mark.asyncio
async def test_risk_level_low_for_query(classifier):
    result = await classifier.classify("show me the dashboard")
    assert result.risk_level == RiskLevel.LOW


@pytest.mark.asyncio
async def test_entity_extraction(classifier):
    result = await classifier.classify("show deals for Acme Corp and Globex")
    # Should extract capitalised entities
    assert any("Acme" in e for e in result.entities)


@pytest.mark.asyncio
async def test_empty_prompt_raises(classifier):
    with pytest.raises(ValueError, match="empty"):
        await classifier.classify("")


@pytest.mark.asyncio
async def test_whitespace_only_prompt_raises(classifier):
    with pytest.raises(ValueError, match="empty"):
        await classifier.classify("   ")


@pytest.mark.asyncio
async def test_very_long_prompt_handled(classifier):
    long_prompt = "show me all deals " + ("word " * 2000)
    result = await classifier.classify(long_prompt)
    # Should not raise, should return a valid result
    assert result.intent_type in IntentType.__members__.values()
