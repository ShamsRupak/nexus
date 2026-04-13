"""Tests for the evaluation framework — scorer, citation, regression. (15+ tests)"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("NEXUS_ENV", "test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")

from nexus.eval.citation import CitationReport, verify_citations
from nexus.eval.regression import (
    CaseResult,
    CaseStatus,
    RegressionReport,
    RegressionRunner,
)
from nexus.eval.scorer import accuracy_score, completeness_score, format_score, score_response

# ===========================================================================
# SCORER TESTS
# ===========================================================================


def test_accuracy_identical_strings():
    assert accuracy_score("hello world", "hello world") == 1.0


def test_accuracy_empty_strings():
    assert accuracy_score("", "") == 1.0


def test_accuracy_one_empty():
    assert accuracy_score("", "something") == 0.0
    assert accuracy_score("something", "") == 0.0


def test_accuracy_completely_different():
    score = accuracy_score("apple orange banana", "car truck bicycle")
    assert score == 0.0


def test_accuracy_partial_overlap():
    score = accuracy_score("the quick brown fox", "the quick red fox")
    # "the", "quick", "fox" overlap = 3; union = 5 → Jaccard = 0.6
    assert 0.0 < score < 1.0


def test_accuracy_case_insensitive():
    assert accuracy_score("Hello World", "hello world") == 1.0


def test_completeness_all_fields_present():
    response = "The deal has company Acme, value 100000, and stage Negotiation."
    fields = ["company", "value", "stage"]
    assert completeness_score(response, fields) == 1.0


def test_completeness_no_fields():
    assert completeness_score("anything", []) == 1.0


def test_completeness_missing_fields_reduce_score():
    response = "The deal has company Acme."
    fields = ["company", "value", "stage", "owner"]
    score = completeness_score(response, fields)
    assert score == 0.25  # only 1/4 fields present


def test_format_score_valid_json():
    assert format_score('{"key": "value"}', "json") == 1.0


def test_format_score_invalid_json():
    score = format_score("not json at all", "json")
    assert score < 1.0


def test_format_score_json_like_partial_credit():
    score = format_score('{"incomplete":', "json")
    # Starts with { but invalid → partial credit (0.3)
    assert score == 0.3


def test_format_score_text_non_empty():
    assert format_score("any text here", "text") == 1.0


def test_format_score_empty_string():
    assert format_score("", "json") == 0.0
    assert format_score("", "text") == 0.0


def test_format_score_list_format():
    response = "- Item one\n- Item two\n- Item three"
    score = format_score(response, "list")
    assert score > 0.5


def test_score_response_aggregates():
    result = score_response(
        response="The deal value is 150000 in stage Negotiation",
        ground_truth="The deal value is 150000 in stage Negotiation",
        expected_fields=["deal value", "Negotiation"],
        expected_format="text",
    )
    assert result.accuracy == 1.0
    assert result.completeness == 1.0
    assert result.format_score == 1.0
    assert result.overall == 1.0


# ===========================================================================
# CITATION TESTS
# ===========================================================================


def test_citation_no_claims_in_empty_response():
    report = verify_citations("", ["some source"])
    assert report.total_claims == 0
    assert report.hallucination_rate == 0.0


def test_citation_no_sources_all_ungrounded():
    response = "The refund window is 30 days. All plans have uptime SLAs."
    report = verify_citations(response, [])
    assert report.total_claims > 0
    assert report.grounded == 0
    assert report.hallucination_rate == 1.0


def test_citation_identical_source_grounds_claim():
    claim = "The refund period is 30 days for all customers."
    source = "The refund period is 30 days for all customers. No exceptions apply."
    report = verify_citations(claim, [source])
    # Jaccard overlap should be very high → grounded
    assert report.grounded == 1
    assert report.hallucination_rate == 0.0


def test_citation_unrelated_source_ungrounds_claim():
    claim = "The system uses quantum entanglement for data storage."
    source = "Our refund policy covers 30 days from the purchase date."
    report = verify_citations(claim, [source])
    assert report.ungrounded >= 1


def test_citation_report_fields_populated():
    claim = "Enterprise plan has 99.9% uptime guarantee."
    source = "Enterprise customers receive 99.9 percent uptime SLA guarantee."
    report = verify_citations(claim, [source])
    assert isinstance(report, CitationReport)
    assert report.total_claims >= 1
    assert report.hallucination_rate >= 0.0
    assert report.hallucination_rate <= 1.0


def test_citation_details_populated():
    response = "Refunds take 30 days. Data is retained 7 years."
    sources = ["Refunds are processed within 30 days.", "Data retention is 7 years per SOC2."]
    report = verify_citations(response, sources)
    assert len(report.details) >= 1
    for d in report.details:
        assert d.claim
        assert 0.0 <= d.score <= 1.0
        assert d.best_source != "" or not d.grounded


def test_citation_hallucination_rate_calculation():
    report = verify_citations(
        "A is true. B is true. C is true.",
        ["A is true."],  # only first claim grounded
    )
    # 3 claims, 1 grounded → rate should be > 0
    assert report.hallucination_rate > 0.0


# ===========================================================================
# REGRESSION RUNNER TESTS
# ===========================================================================


@pytest.mark.asyncio
async def test_regression_runner_passing_case():
    runner = RegressionRunner()
    runner.add_case(
        "query_deals",
        "show me all deals",
        {"intent": "query", "requires_approval": False},
    )
    report = await runner.run_all()
    assert report.total == 1
    assert report.passed == 1
    assert report.results[0].status == CaseStatus.PASSED


@pytest.mark.asyncio
async def test_regression_runner_failing_case():
    runner = RegressionRunner()
    runner.add_case(
        "wrong_intent",
        "show me all deals",
        {"intent": "action"},  # wrong expected intent → should fail
    )
    report = await runner.run_all()
    assert report.total == 1
    assert report.failed == 1
    assert report.results[0].status == CaseStatus.FAILED


@pytest.mark.asyncio
async def test_regression_runner_multiple_cases():
    runner = RegressionRunner()
    runner.add_case("q1", "show me all deals", {"intent": "query"})
    runner.add_case("q2", "list all customers", {"intent": "query"})
    runner.add_case("a1", "create a new customer", {"intent": "action"})
    report = await runner.run_all()
    assert report.total == 3
    assert report.passed >= 2


@pytest.mark.asyncio
async def test_regression_runner_pass_rate():
    runner = RegressionRunner()
    runner.add_case("ok", "show me all deals", {"intent": "query"})
    runner.add_case("fail", "show me all deals", {"intent": "action"})  # wrong
    report = await runner.run_all()
    assert 0.0 <= report.pass_rate <= 1.0


@pytest.mark.asyncio
async def test_regression_compare_detects_regression():
    """A case passing in baseline but failing in current = regression."""
    passing_result = CaseResult(
        name="query_case",
        prompt="show deals",
        status=CaseStatus.PASSED,
        expected={"intent": "query"},
        actual={"intent": "query"},
    )
    failing_result = CaseResult(
        name="query_case",
        prompt="show deals",
        status=CaseStatus.FAILED,
        expected={"intent": "query"},
        actual={"intent": "action"},
    )

    baseline = RegressionReport.from_results("run-A", [passing_result])
    current = RegressionReport.from_results("run-B", [failing_result])

    diff = RegressionRunner.compare_to_baseline(current, baseline)
    assert "query_case" in diff.regressed


@pytest.mark.asyncio
async def test_regression_compare_detects_improvement():
    """A case failing in baseline but passing in current = improvement."""
    failing_result = CaseResult(
        name="action_case",
        prompt="create customer",
        status=CaseStatus.FAILED,
        expected={"intent": "action"},
    )
    passing_result = CaseResult(
        name="action_case",
        prompt="create customer",
        status=CaseStatus.PASSED,
        expected={"intent": "action"},
        actual={"intent": "action"},
    )

    baseline = RegressionReport.from_results("run-A", [failing_result])
    current = RegressionReport.from_results("run-B", [passing_result])

    diff = RegressionRunner.compare_to_baseline(current, baseline)
    assert "action_case" in diff.improved


def test_regression_diff_net_change():
    from nexus.eval.regression import RegressionDiff

    diff = RegressionDiff(
        baseline_run_id="A",
        current_run_id="B",
        regressed=["case1"],
        improved=["case2", "case3"],
        stable_pass=[],
        stable_fail=[],
    )
    assert diff.net_change == 1  # 2 improved - 1 regressed
