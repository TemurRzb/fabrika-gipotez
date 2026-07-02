"""Тест склейки пайплайна (без UI): run_pipeline() на мок-документах должен
вернуть результат, валидный по schemas/ranked_hypotheses.schema.json."""
import os

from modules.orchestrator_ui.mock_pipeline import run_pipeline
from schemas.validate_schema import validate


def test_run_pipeline_on_mock_documents_matches_schema():
    os.environ["USE_MOCK_LLM"] = "true"
    constraints = {
        "materials": ["лежалые хвосты флотации"],
        "budget": None,
        "equipment": [],
        "regulatory": [],
    }

    result = run_pipeline(
        "Повысить извлечение золота из лежалых хвостов флотации на 15%",
        constraints,
    )

    validate(result, "ranked_hypotheses")
    assert len(result["hypotheses"]) > 0
