"""Тест склейки пайплайна (без UI): run_pipeline() на мок-документах должен
вернуть результат, валидный по schemas/ranked_hypotheses.schema.json.

Документы передаются явно (load_mock_documents()), а не через дефолтный
load_default_documents() — иначе тест незаметно начинает гонять реальные
эмбеддинги по всему закэшированному data/parsed_documents/ (десятки
документов, включая распознанную книгу на сотни страниц), что превращает
быстрый юнит-тест в многоминутный. За поведение "документы не переданы ->
берём реальный кэш" отвечает отдельная логика в mock_pipeline.py, здесь же
проверяется только сама склейка retrieve -> generate_hypotheses -> rank."""
import os

from modules.orchestrator_ui.mock_pipeline import load_mock_documents, run_pipeline
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
        documents=load_mock_documents(),
    )

    validate(result, "ranked_hypotheses")
    assert len(result["hypotheses"]) > 0
