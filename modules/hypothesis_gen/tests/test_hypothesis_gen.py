"""Тест модуля hypothesis_gen в мок-режиме (USE_MOCK_LLM=true по умолчанию,
без сети и без ключей Yandex): гоняем generate_hypotheses() на мок-retrieval_result
и валидируем результат по schemas/raw_hypotheses.schema.json."""
import json
import os
from pathlib import Path

from modules.hypothesis_gen.generate import generate_hypotheses
from schemas.validate_schema import validate

MOCK_RETRIEVAL_DIR = Path(__file__).resolve().parents[3] / "mock_data" / "retrieval_results"


def test_generate_hypotheses_mock_matches_schema():
    os.environ["USE_MOCK_LLM"] = "true"
    retrieval_result = json.loads(
        (MOCK_RETRIEVAL_DIR / "retrieval_regrind.json").read_text(encoding="utf-8")
    )

    result = generate_hypotheses(retrieval_result)

    validate(result, "raw_hypotheses")
    assert len(result["hypotheses"]) > 0


def test_generate_hypotheses_mock_handles_empty_chunks():
    os.environ["USE_MOCK_LLM"] = "true"
    retrieval_result = {
        "query": {
            "target_property": "цель без найденных источников",
            "constraints": {"materials": [], "budget": None, "equipment": [], "regulatory": []},
        },
        "retrieved_chunks": [],
        "graph_context": {"nodes": [], "edges": []},
    }

    result = generate_hypotheses(retrieval_result)

    validate(result, "raw_hypotheses")
    assert len(result["hypotheses"]) == 1
