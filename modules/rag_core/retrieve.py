"""
Модуль rag_core: база знаний / RAG-ядро.

Вход: query (target_property + constraints) и список документов
(каждый — dict, валидный по schemas/document.schema.json).
Выход: dict, валидный по schemas/retrieval_result.schema.json.

Статус на сейчас (скелет):
  - Чанкинг: по абзацам внутри sections[].text.
  - Похожесть: TF-IDF + косинусная близость (scikit-learn). Быстро поднимается,
    не требует скачивания моделей эмбеддингов и работы без интернета.
  - graph_context: всегда пустой ({"nodes": [], "edges": []}) — построение
    графа сущностей не входит в MVP.

TODO (реальная интеграция вместо TF-IDF-заглушки):
  - Заменить TF-IDF на Yandex AI Studio text-embeddings API
    (base_url=os.environ["YANDEX_EMBEDDINGS_BASE_URL"] или тот же base_url,
    что и для LLM — см. hypothesis_gen/generate.py про паттерн клиента).
  - Заливать чанки в Yandex Vector Store API вместо пересчёта TF-IDF на лету
    при каждом вызове retrieve() — сейчас это in-memory заглушка.
  - Извлечение entities сейчас пустое/примитивное (простые regex по числам с
    единицами измерения) — заменить на NER через YandexGPT Lite (дешёвая
    модель под точечные задачи извлечения полей).
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

TOP_K = 5

_UNIT_ENTITY_PATTERN = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:%|мкм|г/л|г/т|pH|мм|мин|ч)\b", re.IGNORECASE
)


def _new_id() -> str:
    return str(uuid.uuid4())


def _split_into_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    return paragraphs if paragraphs else ([text.strip()] if text.strip() else [])


def _chunk_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Разбивает документы на чанки по абзацам секций."""
    chunks: list[dict[str, Any]] = []
    for doc in documents:
        doc_id = doc["doc_id"]
        title = doc.get("title", "")
        for section in doc.get("sections", []):
            for paragraph in _split_into_paragraphs(section.get("text", "")):
                chunks.append(
                    {
                        "chunk_id": _new_id(),
                        "doc_id": doc_id,
                        "text": paragraph,
                        "heading": section.get("heading", ""),
                        "doc_title": title,
                    }
                )
    return chunks


def _extract_entities(text: str) -> list[dict[str, str]]:
    """Простейшее извлечение сущностей-заглушка: числа с единицами измерения.
    TODO: заменить вызовом YandexGPT Lite с промптом на структурированное извлечение.
    """
    return [{"type": "parameter", "value": m.group(0)} for m in _UNIT_ENTITY_PATTERN.finditer(text)]


def retrieve(query: dict[str, Any], documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Ищет наиболее релевантные чанки документов по запросу.

    query: {"target_property": str, "constraints": {...}} (см. retrieval_result.schema.json)
    documents: список dict, валидных по document.schema.json
    """
    chunks = _chunk_documents(documents)

    if not chunks:
        return {
            "query": query,
            "retrieved_chunks": [],
            "graph_context": {"nodes": [], "edges": []},
        }

    corpus = [c["text"] for c in chunks]
    query_text = query["target_property"]

    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(corpus + [query_text])
    doc_vectors = tfidf_matrix[:-1]
    query_vector = tfidf_matrix[-1]

    similarities = cosine_similarity(query_vector, doc_vectors)[0]

    ranked_indices = similarities.argsort()[::-1][:TOP_K]

    retrieved_chunks = []
    for idx in ranked_indices:
        chunk = chunks[idx]
        similarity = float(similarities[idx])
        if similarity <= 0:
            continue
        retrieved_chunks.append(
            {
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "text": chunk["text"],
                "similarity": round(similarity, 4),
                "entities": _extract_entities(chunk["text"]),
                "source_citation": f"{chunk['doc_title']} — {chunk['heading']}".strip(" —"),
            }
        )

    return {
        "query": query,
        "retrieved_chunks": retrieved_chunks,
        "graph_context": {"nodes": [], "edges": []},
    }


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    mock_docs_dir = Path(__file__).resolve().parents[2] / "mock_data" / "documents"
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in mock_docs_dir.glob("*.json")]

    demo_query = {
        "target_property": "Повысить извлечение золота из лежалых хвостов флотации на 15%",
        "constraints": {"materials": [], "budget": None, "equipment": [], "regulatory": []},
    }
    if len(sys.argv) > 1:
        demo_query["target_property"] = sys.argv[1]

    print(json.dumps(retrieve(demo_query, docs), ensure_ascii=False, indent=2))
