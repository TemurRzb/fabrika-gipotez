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
CACHED_DOCUMENTS_DIR = ROOT_DIR / "data" / "parsed_documents"


def load_mock_documents() -> list[dict[str, Any]]:
    """Загружает игрушечные мок-документы из mock_data/documents — подстраховка
    на случай, если реального закэшированного кэша (см. load_cached_documents)
    ещё нет в этом окружении."""
    return [json.loads(p.read_text(encoding="utf-8")) for p in MOCK_DOCUMENTS_DIR.glob("*.json")]


def load_cached_documents() -> list[dict[str, Any]]:
    """Загружает реальные документы, заранее распарсенные ingest_folder() и
    закэшированные в data/parsed_documents/ (см. modules/ingestion/README.md).
    Возвращает пустой список, если кэша ещё нет — тогда run_pipeline
    откатывается на load_mock_documents()."""
    if not CACHED_DOCUMENTS_DIR.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in CACHED_DOCUMENTS_DIR.glob("*.json")]


def load_default_documents() -> list[dict[str, Any]]:
    """База знаний по умолчанию: реальный кэш, если он есть, иначе игрушечные моки."""
    return load_cached_documents() or load_mock_documents()


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
    load_default_documents() (реальный кэш data/parsed_documents/, либо
    mock_data/documents, если кэша ещё нет).
    """
    if documents is None:
        documents = load_default_documents()

    query = {"target_property": target_property, "constraints": constraints}
    retrieval_result = retrieve(query, documents)
    raw_hypotheses = generate_hypotheses(retrieval_result)
    ranked_hypotheses = rank(raw_hypotheses, constraints)
    return ranked_hypotheses
