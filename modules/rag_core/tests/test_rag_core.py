"""Тест модуля rag_core: гоняем retrieve() на мок-документах из mock_data/documents
и валидируем результат по schemas/retrieval_result.schema.json."""
import json
from pathlib import Path

from modules.rag_core.retrieve import retrieve
from schemas.validate_schema import validate

MOCK_DOCS_DIR = Path(__file__).resolve().parents[3] / "mock_data" / "documents"


def _load_mock_documents() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in MOCK_DOCS_DIR.glob("*.json")]


def test_retrieve_matches_schema_and_finds_relevant_chunks():
    documents = _load_mock_documents()
    query = {
        "target_property": "Повысить извлечение золота из лежалых хвостов флотации на 15%",
        "constraints": {
            "materials": ["лежалые хвосты флотации"],
            "budget": None,
            "equipment": [],
            "regulatory": [],
        },
    }

    result = retrieve(query, documents)

    validate(result, "retrieval_result")
    assert len(result["retrieved_chunks"]) > 0
    # Отчёт про доизмельчение хвостов должен оказаться среди найденных документов
    found_doc_ids = {c["doc_id"] for c in result["retrieved_chunks"]}
    assert "11111111-1111-4111-8111-111111111111" in found_doc_ids


def test_retrieve_handles_empty_documents():
    query = {
        "target_property": "любой запрос",
        "constraints": {"materials": [], "budget": None, "equipment": [], "regulatory": []},
    }

    result = retrieve(query, [])

    validate(result, "retrieval_result")
    assert result["retrieved_chunks"] == []
