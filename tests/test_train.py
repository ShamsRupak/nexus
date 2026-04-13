"""Tests for training data generator, LoRA trainer config, and evaluator. (15+ tests)"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("NEXUS_ENV", "test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")

DATA_DIR = Path(__file__).parent.parent / "data" / "sample"


# ===========================================================================
# DATA GENERATOR TESTS
# ===========================================================================


def test_from_csv_deals_returns_pairs():
    from nexus.train.data_generator import TrainingDataGenerator
    gen = TrainingDataGenerator()
    pairs = gen.from_csv(str(DATA_DIR / "deals.csv"), "deals")
    assert len(pairs) > 0
    for p in pairs[:5]:
        assert "instruction" in p
        assert "response" in p
        assert isinstance(p["instruction"], str)
        assert isinstance(p["response"], str)
        assert len(p["instruction"]) > 5


def test_from_csv_customers_returns_pairs():
    from nexus.train.data_generator import TrainingDataGenerator
    gen = TrainingDataGenerator()
    pairs = gen.from_csv(str(DATA_DIR / "customers.csv"), "customers")
    assert len(pairs) > 10


def test_from_csv_generates_count_question():
    from nexus.train.data_generator import TrainingDataGenerator
    gen = TrainingDataGenerator()
    pairs = gen.from_csv(str(DATA_DIR / "deals.csv"), "deals")
    instructions = [p["instruction"].lower() for p in pairs]
    # Should generate a "how many" count question
    assert any("how many" in i or "count" in i or "total" in i for i in instructions)


def test_from_csv_generates_sql_pairs():
    from nexus.train.data_generator import TrainingDataGenerator
    gen = TrainingDataGenerator()
    pairs = gen.from_csv(str(DATA_DIR / "deals.csv"), "deals")
    sql_pairs = [p for p in pairs if "SELECT" in p["response"]]
    assert len(sql_pairs) >= 2  # at least SELECT * and COUNT


def test_from_csv_missing_file_raises():
    from nexus.train.data_generator import TrainingDataGenerator
    gen = TrainingDataGenerator()
    with pytest.raises(FileNotFoundError):
        gen.from_csv("/nonexistent/path/file.csv", "table")


def test_from_csv_empty_csv_returns_empty():
    from nexus.train.data_generator import TrainingDataGenerator
    gen = TrainingDataGenerator()
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        f.write("id,name,value\n")  # header only, no rows
        tmp = f.name
    try:
        pairs = gen.from_csv(tmp, "empty_table")
        assert pairs == []
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_from_text_policies_returns_pairs():
    from nexus.train.data_generator import TrainingDataGenerator
    gen = TrainingDataGenerator()
    pairs = gen.from_text(str(DATA_DIR / "policies.md"), "Nexus Platform Policies")
    assert len(pairs) > 0
    for p in pairs[:3]:
        assert "instruction" in p
        assert "response" in p


def test_from_text_produces_policy_questions():
    from nexus.train.data_generator import TrainingDataGenerator
    gen = TrainingDataGenerator()
    pairs = gen.from_text(str(DATA_DIR / "policies.md"), "Platform Policies")
    instructions = [p["instruction"].lower() for p in pairs]
    assert any("policy" in i or "what" in i or "how" in i for i in instructions)


def test_from_schema_returns_pairs():
    from nexus.train.data_generator import TrainingDataGenerator
    gen = TrainingDataGenerator()
    schema = {
        "table": "deals",
        "columns": [
            {"name": "deal_value", "type": "float", "description": "deal value in USD"},
            {"name": "stage", "type": "text", "description": "pipeline stage"},
        ],
    }
    pairs = gen.from_schema(schema)
    assert len(pairs) >= 4  # at least 2 per numeric col (def + total + avg) + 1 text col def


def test_from_schema_includes_definition_question():
    from nexus.train.data_generator import TrainingDataGenerator
    gen = TrainingDataGenerator()
    schema = {
        "table": "customers",
        "columns": [{"name": "mrr", "type": "float", "description": "monthly recurring revenue"}],
    }
    pairs = gen.from_schema(schema)
    # Should have a definition question
    defs = [p for p in pairs if "represent" in p["instruction"] or "field" in p["instruction"]]
    assert len(defs) >= 1


def test_export_jsonl_writes_valid_file():
    from nexus.train.data_generator import TrainingDataGenerator
    gen = TrainingDataGenerator()
    pairs = [
        {"instruction": "How many deals exist?", "response": "There are 50 deals."},
        {"instruction": "What is the total deal value?", "response": "The total is $1.5M."},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "train.jsonl"
        count = gen.export_jsonl(pairs, str(out))
        assert count == 2
        assert out.exists()
        lines = out.read_text().strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert "instruction" in obj
            assert "response" in obj


def test_export_jsonl_skips_invalid_pairs():
    from nexus.train.data_generator import TrainingDataGenerator
    gen = TrainingDataGenerator()
    pairs = [
        {"instruction": "valid question?", "response": "valid answer"},
        {"question": "old format", "answer": "old answer"},   # missing instruction/response keys
        {"instruction": "another valid?", "response": "another answer"},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "train.jsonl"
        count = gen.export_jsonl(pairs, str(out))
        assert count == 2  # skips the invalid entry


def test_generate_all_produces_200_plus_pairs():
    from nexus.train.data_generator import TrainingDataGenerator
    gen = TrainingDataGenerator()
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "all_train.jsonl"
        count = gen.generate_all(str(DATA_DIR), str(out))
        assert count >= 200, f"Expected 200+ pairs, got {count}"
        assert out.exists()


# ===========================================================================
# TRAINING CONFIG TESTS
# ===========================================================================


def test_training_config_defaults():
    from nexus.train.lora_trainer import TrainingConfig
    cfg = TrainingConfig()
    assert cfg.model_name == "Qwen/Qwen2.5-3B-Instruct"
    assert cfg.lora_r == 16
    assert cfg.lora_alpha == 32
    assert cfg.target_modules == ["q_proj", "v_proj"]
    assert cfg.epochs == 3
    assert cfg.batch_size == 4
    assert abs(cfg.learning_rate - 2e-4) < 1e-9
    assert cfg.warmup_steps == 10


def test_training_config_custom_values():
    from nexus.train.lora_trainer import TrainingConfig
    cfg = TrainingConfig(
        model_name="meta-llama/Llama-3.1-8B",
        lora_r=32,
        epochs=5,
        batch_size=8,
    )
    assert cfg.model_name == "meta-llama/Llama-3.1-8B"
    assert cfg.lora_r == 32
    assert cfg.epochs == 5
    assert cfg.batch_size == 8


def test_training_result_serializes():
    from nexus.train.lora_trainer import TrainingResult
    result = TrainingResult(
        model_name="Qwen/Qwen2.5-3B-Instruct",
        adapter_path="/models/adapter_v1",
        epochs_completed=3,
        final_loss=0.2341,
        eval_loss=0.2891,
        training_time_seconds=120.5,
        num_training_samples=250,
    )
    data = result.model_dump()
    assert data["model_name"] == "Qwen/Qwen2.5-3B-Instruct"
    assert data["epochs_completed"] == 3
    assert data["final_loss"] == 0.2341
    assert data["num_training_samples"] == 250


def test_lora_trainer_init_stores_config():
    from nexus.train.lora_trainer import LoRATrainer, TrainingConfig
    cfg = TrainingConfig(lora_r=32, epochs=5)
    trainer = LoRATrainer(config=cfg)
    assert trainer.config.lora_r == 32
    assert trainer.config.epochs == 5


def test_lora_trainer_init_by_model_name():
    from nexus.train.lora_trainer import LoRATrainer
    trainer = LoRATrainer(model_name="Qwen/Qwen2.5-3B-Instruct")
    assert trainer.config.model_name == "Qwen/Qwen2.5-3B-Instruct"


@pytest.mark.asyncio
async def test_prepare_dataset_loads_jsonl():
    from nexus.train.lora_trainer import LoRATrainer
    trainer = LoRATrainer()
    with tempfile.TemporaryDirectory() as tmpdir:
        data_file = Path(tmpdir) / "train.jsonl"
        records = [
            {"instruction": f"Question {i}?", "response": f"Answer {i}."}
            for i in range(10)
        ]
        data_file.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        ds = await trainer.prepare_dataset(str(data_file))
        assert len(ds) == 10
        assert ds[0]["instruction"] == "Question 0?"


@pytest.mark.asyncio
async def test_train_dry_run_returns_result():
    """Train uses dry-run path when torch/transformers unavailable (always in CI)."""
    from nexus.train.lora_trainer import Dataset, LoRATrainer, TrainingConfig
    cfg = TrainingConfig(epochs=2)
    trainer = LoRATrainer(config=cfg)
    records = [{"instruction": f"Q{i}?", "response": f"A{i}."} for i in range(20)]
    ds = Dataset(records)
    with tempfile.TemporaryDirectory() as tmpdir:
        result = await trainer.train(ds, tmpdir)
        assert result.epochs_completed == 2
        assert result.num_training_samples == 20
        assert result.final_loss > 0
        assert result.training_time_seconds >= 0


@pytest.mark.asyncio
async def test_evaluate_keyword_returns_result():
    from nexus.train.lora_trainer import LoRATrainer
    trainer = LoRATrainer()
    test_data = [
        {"instruction": "How many deals?", "response": "There are 50 deals total."},
        {"instruction": "Write SQL to count deals.", "response": "SELECT COUNT(*) FROM deals;"},
    ]
    result = await trainer.evaluate("models/fake_adapter", test_data)
    assert result.num_samples == 2
    assert 0.0 <= result.accuracy <= 1.0
    assert result.avg_latency_ms >= 0.0


# ===========================================================================
# BENCHMARK REPORT TESTS
# ===========================================================================


def test_benchmark_report_improvement_pct():
    from nexus.train.evaluator import BenchmarkReport
    report = BenchmarkReport(
        base_model="base",
        adapter_path="/adapter",
        base_model_accuracy=0.50,
        finetuned_accuracy=0.65,
        improvement_pct=15.0,
    )
    assert report.improvement_pct == 15.0


def test_benchmark_report_build_from_results():
    from nexus.train.evaluator import BenchmarkReport

    base_results = [
        {"score": 0.4, "latency_ms": 100.0, "category": "data_queries"},
        {"score": 0.3, "latency_ms": 120.0, "category": "policy_questions"},
    ]
    ft_results = [
        {"score": 0.6, "latency_ms": 95.0, "category": "data_queries"},
        {"score": 0.55, "latency_ms": 110.0, "category": "policy_questions"},
    ]
    report = BenchmarkReport.build("base_model", "/adapter", base_results, ft_results)
    assert report.finetuned_accuracy > report.base_model_accuracy
    assert report.improvement_pct > 0
    assert "data_queries" in report.category_breakdown
    assert "policy_questions" in report.category_breakdown


@pytest.mark.asyncio
async def test_model_evaluator_benchmark_returns_report():
    from nexus.train.evaluator import ModelEvaluator
    evaluator = ModelEvaluator()
    test_cases = [
        {"instruction": "How many deals?", "response": "50 deals.", "category": "data_queries"},
        {"instruction": "What is the refund policy?", "response": "30 days.", "category": "policy_questions"},
        {"instruction": "Write SQL to count deals.", "response": "SELECT COUNT(*) FROM deals;", "category": "sql_generation"},
    ]
    report = await evaluator.benchmark("base_model", "/mock/adapter", test_cases)
    assert report.num_test_cases == 3
    assert 0.0 <= report.base_model_accuracy <= 1.0
    assert 0.0 <= report.finetuned_accuracy <= 1.0
    assert report.finetuned_accuracy >= report.base_model_accuracy  # fine-tuned should be better


@pytest.mark.asyncio
async def test_model_evaluator_empty_cases():
    from nexus.train.evaluator import ModelEvaluator
    evaluator = ModelEvaluator()
    report = await evaluator.benchmark("base_model", "/adapter", [])
    assert report.num_test_cases == 0
    assert report.base_model_accuracy == 0.0
