"""
mock_pipeline.py — склейка всех 4 модулей пайплайна для оркестратора/UI.

Сегодня (день 1) все 4 функции уже работают "на моках":
  - ingest()              — реальный парсинг .docx/.pdf, xlsx/OCR — NotImplementedError
  - retrieve()             — TF-IDF заглушка вместо реальных эмбеддингов
  - generate_hypotheses()  — USE_MOCK_LLM=true по умолчанию, без реального Yandex API
  - rank()                 — rule-based + псевдо-эмбеддинги

По мере готовности реальных частей других модулей эта склейка не меняется —
меняется только то, что происходит "под капотом" внутри импортируемых функций.
TODO: когда ingestion/rag_core/hypothesis_gen/ranking подключат реальные бэкенды
(Yandex API, реальные эмбеддинги), этот файл трогать не придётся — контракт
между модулями (JSON Schemas в /schemas) остаётся неизменным.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modules.hypothesis_gen.generate import generate_hypotheses
from modules.ingestion.ingest import ingest
from modules.ranking.rank import rank
from modules.rag_core.retrieve import retrieve

ROOT_DIR = Path(__file__).resolve().parents[2]
MOCK_DOCUMENTS_DIR = ROOT_DIR / "mock_data" / "documents"


def load_mock_documents() -> list[dict[str, Any]]:
    """Загружает мок-документы из mock_data/documents (используется, когда
    пользователь не загрузил свои файлы)."""
    return [json.loads(p.read_text(encoding="utf-8")) for p in MOCK_DOCUMENTS_DIR.glob("*.json")]


def ingest_uploaded_files(file_paths: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Прогоняет ingest() по списку путей к файлам.
    Возвращает (успешно распарсенные документы, сообщения об ошибках/заглушках)."""
    documents: list[dict[str, Any]] = []
    warnings: list[str] = []
    for file_path in file_paths:
        try:
            documents.append(ingest(file_path))
        except NotImplementedError as e:
            warnings.append(f"{Path(file_path).name}: {e}")
        except Exception as e:  # noqa: BLE001 - показываем пользователю любую ошибку парсинга
            warnings.append(f"{Path(file_path).name}: ошибка парсинга — {e}")
    return documents, warnings


def run_pipeline(
    target_property: str,
    constraints: dict[str, Any],
    documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Прогоняет весь пайплайн rag_core -> hypothesis_gen -> ranking.

    documents: список документов (document.schema.json). Если None — берём
    mock_data/documents (демо-режим без загрузки файлов).
    """
    if documents is None:
        documents = load_mock_documents()

    query = {"target_property": target_property, "constraints": constraints}
    retrieval_result = retrieve(query, documents)
    raw_hypotheses = generate_hypotheses(retrieval_result)
    ranked_hypotheses = rank(raw_hypotheses, constraints)
    return ranked_hypotheses
