"""Тест модуля ranking: гоняем rank() на мок raw_hypotheses и валидируем
результат по schemas/ranked_hypotheses.schema.json."""
import json
from pathlib import Path

from modules.ranking.rank import rank
from schemas.validate_schema import validate

MOCK_RAW_DIR = Path(__file__).resolve().parents[3] / "mock_data" / "raw_hypotheses"

CONSTRAINTS = {
    "materials": ["лежалые хвосты флотации", "известь", "ксантогенат"],
    "budget": "до 5 млн руб.",
    "equipment": ["шаровая мельница", "флотомашина"],
    "regulatory": [],
}


def test_rank_matches_schema_and_sorts_by_overall():
    raw = json.loads((MOCK_RAW_DIR / "raw_hypotheses_regrind.json").read_text(encoding="utf-8"))

    result = rank(raw, CONSTRAINTS)

    validate(result, "ranked_hypotheses")
    overall_scores = [h["scores"]["overall"] for h in result["hypotheses"]]
    assert overall_scores == sorted(overall_scores, reverse=True)


def test_rank_handles_single_hypothesis():
    raw = {
        "hypotheses": [
            {
                "hyp_id": "dddddddd-0001-4001-8001-000000000001",
                "statement": "Единственная тестовая гипотеза",
                "mechanism": "Тестовый механизм",
                "sources": [],
                "target_property_impact": "+5%",
                "raw_llm_novelty_note": "тест",
            }
        ]
    }

    result = rank(raw, CONSTRAINTS)

    validate(result, "ranked_hypotheses")
    assert len(result["hypotheses"]) == 1
    assert 0.0 <= result["hypotheses"][0]["scores"]["overall"] <= 1.0
