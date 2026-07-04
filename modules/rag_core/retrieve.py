"""
Модуль rag_core: база знаний / RAG-ядро.

Вход: query (target_property + constraints) и список документов
(каждый — dict, валидный по schemas/document.schema.json).
Выход: dict, валидный по schemas/retrieval_result.schema.json.

Статус на сейчас:
  - Чанкинг: по абзацам внутри sections[].text.
  - Похожесть: реальные семантические эмбеддинги через sentence-transformers
    (intfloat/multilingual-e5-small) + косинусная близость. Модель полностью
    локальная — качается один раз при первом запуске, дальше работает офлайн,
    без обращений к Yandex API (доступ к нему закрыт для этого проекта, см.
    решение перейти на локальные модели вместо Yandex AI Studio).
  - graph_context: всегда пустой ({"nodes": [], "edges": []}) — построение
    графа сущностей не входит в MVP.

Модель E5 обучена специально под retrieval (асимметричные query/passage
эмбеддинги) — тексты нужно эмбеддить с префиксами "query: "/"passage: ",
это существенно для качества и уже учтено в коде ниже.

Важная находка на реальных данных (31 документ из data/parsed_documents/):
наивный чанкинг по одиночным строкам (было раньше) даёт ~27 000 чанков по
~80 символов на OCR-тексте (там почти нет пустых строк-абзацев, каждая строка
Tesseract превращалась в отдельный чанк) — retrieve() занимал ~15 минут.
Чанки теперь группируются до целевого размера (см. _CHUNK_TARGET_CHARS),
это на порядок сокращает их число (2863 вместо 27000).

Даже после этого эмбеддинг всей реальной базы с нуля занимает ~5-10 минут —
железо разработки слабое (2-ядерный CPU без GPU, см. README модуля). Поэтому
эмбеддинги кэшируются НЕ ТОЛЬКО в памяти процесса, но и на диске
(_EMBEDDING_CACHE_PATH) — дорогой пересчёт всей базы происходит один раз
(мы это уже сделали и закоммитили готовый кэш), а не при каждом запуске
пайплайна/тестов/UI у каждого, кто клонирует репозиторий.

TODO:
  - Извлечение entities сейчас пустое/примитивное (простые regex по числам с
    единицами измерения) — заменить на NER через локальную модель, если
    останется время.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

TOP_K = 5
_EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"
# Целевой размер чанка в символах — компромисс между контекстом (больше =
# лучше смысл) и локализацией источника (меньше = точнее цитата).
_CHUNK_TARGET_CHARS = 600
# Файл с закэшированными эмбеддингами (npz — компактный бинарный формат numpy).
# Коммитится в git вместе с data/parsed_documents/, чтобы дорогой пересчёт на
# слабом железе не повторялся у каждого, кто клонирует репозиторий.
_EMBEDDING_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "embedding_cache.npz"

_UNIT_ENTITY_PATTERN = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:%|мкм|г/л|г/т|pH|мм|мин|ч)\b", re.IGNORECASE
)

_model: SentenceTransformer | None = None
# Кэш эмбеддингов чанков, ключ — sha256 текста чанка. Заполняется из
# _EMBEDDING_CACHE_PATH при первом обращении (см. _load_embedding_cache) и
# дополняется в памяти процесса при вызовах retrieve() на новых текстах;
# обновления сохраняются обратно на диск (см. _save_embedding_cache).
_embedding_cache: dict[str, np.ndarray] = {}
_embedding_cache_loaded = False


def _get_model() -> SentenceTransformer:
    """Лениво загружает модель эмбеддингов (один раз на процесс), чтобы импорт
    rag_core.retrieve не тянул за собой загрузку модели там, где эмбеддинги
    не нужны (например, в тестах других модулей, импортирующих mock_pipeline)."""
    global _model
    if _model is None:
        _model = SentenceTransformer(_EMBEDDING_MODEL_NAME)
    return _model


def _new_id() -> str:
    return str(uuid.uuid4())


def _split_into_paragraphs(text: str, target_chars: int = _CHUNK_TARGET_CHARS) -> list[str]:
    """Группирует текст секции в чанки примерно по target_chars символов.

    Сначала пробуем разбить по настоящим абзацам (пустая строка) — работает
    для докс/статей с нормальной вёрсткой. Если пустых строк нет (типично для
    OCR-текста, где Tesseract отдаёт одну строку на элемент) — просто копим
    соседние строки, пока не наберём целевой размер, вместо того чтобы
    возвращать каждую строку отдельным чанком (на реальных данных это давало
    ~27000 чанков по ~80 символов вместо разумных нескольких сотен)."""
    raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not raw_paragraphs:
        raw_paragraphs = [text.strip()] if text.strip() else []

    lines: list[str] = []
    for para in raw_paragraphs:
        lines.extend(line.strip() for line in para.split("\n") if line.strip())

    if not lines:
        return []

    chunks: list[str] = []
    current = ""
    for line in lines:
        if current and len(current) + len(line) + 1 > target_chars:
            chunks.append(current)
            current = line
        else:
            current = f"{current} {line}" if current else line
    if current:
        chunks.append(current)
    return chunks


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


def _load_embedding_cache() -> None:
    """Подгружает закэшированные эмбеддинги с диска в _embedding_cache (один раз
    на процесс). Если файла ещё нет (например, свежий чекаут без предпосчитанного
    кэша) — просто продолжаем с пустым кэшем, он посчитается и сохранится заново."""
    global _embedding_cache_loaded
    if _embedding_cache_loaded:
        return
    _embedding_cache_loaded = True

    if not _EMBEDDING_CACHE_PATH.exists():
        return
    data = np.load(_EMBEDDING_CACHE_PATH)
    for key, vector in zip(data["keys"], data["vectors"]):
        _embedding_cache[str(key)] = vector


def _save_embedding_cache() -> None:
    _EMBEDDING_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    keys = list(_embedding_cache.keys())
    vectors = np.stack([_embedding_cache[k] for k in keys])
    np.savez(_EMBEDDING_CACHE_PATH, keys=np.array(keys), vectors=vectors)


def _embed_passages(texts: list[str], model: SentenceTransformer) -> np.ndarray:
    """Кодирует тексты чанков с кэшированием по хэшу текста — сначала на диске
    (_EMBEDDING_CACHE_PATH, коммитится в git для реальной базы знаний), затем в
    памяти процесса. Считает эмбеддинги только для текстов, которых нет ни там,
    ни там, и дописывает новые результаты обратно на диск."""
    _load_embedding_cache()

    keys = [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]

    missing_texts = [t for t, k in zip(texts, keys) if k not in _embedding_cache]
    missing_keys = [k for k in keys if k not in _embedding_cache]

    if missing_texts:
        new_embeddings = model.encode(
            [f"passage: {t}" for t in missing_texts], normalize_embeddings=True
        )
        for key, embedding in zip(missing_keys, new_embeddings):
            _embedding_cache[key] = embedding
        _save_embedding_cache()

    return np.array([_embedding_cache[k] for k in keys])


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

    query_text = query["target_property"]
    model = _get_model()

    # У E5 асимметричные эмбеддинги: документы кодируются с префиксом "passage: ",
    # запрос — с префиксом "query: ". Без этих префиксов качество поиска заметно хуже.
    corpus_embeddings = _embed_passages([c["text"] for c in chunks], model)
    query_embedding = model.encode([f"query: {query_text}"], normalize_embeddings=True)

    similarities = cosine_similarity(query_embedding, corpus_embeddings)[0]

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

    mock_docs_dir = Path(__file__).resolve().parents[2] / "mock_data" / "documents"
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in mock_docs_dir.glob("*.json")]

    demo_query = {
        "target_property": "Повысить извлечение золота из лежалых хвостов флотации на 15%",
        "constraints": {"materials": [], "budget": None, "equipment": [], "regulatory": []},
    }
    if len(sys.argv) > 1:
        demo_query["target_property"] = sys.argv[1]

    print(json.dumps(retrieve(demo_query, docs), ensure_ascii=False, indent=2))
