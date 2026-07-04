"""
Модуль hypothesis_gen: генерация гипотез поверх Yandex AI Studio.

Вход: retrieval_result (dict, валидный по schemas/retrieval_result.schema.json).
Выход: dict, валидный по schemas/raw_hypotheses.schema.json.

Единственный модуль пайплайна, где используется "сильная" модель (YandexGPT Pro /
Alice AI LLM) — генерация гипотез. Всё остальное (классификация, извлечение полей)
должно уходить на YandexGPT Lite в других модулях.

Режим работы управляется переменной окружения USE_MOCK_LLM (по умолчанию "true"):
  - USE_MOCK_LLM=true  -> без сети и без ключей, детерминированный мок на основе
                          retrieved_chunks. Так можно разрабатывать/тестировать
                          весь пайплайн без ключей Yandex.
  - USE_MOCK_LLM=false -> реальный вызов Yandex AI Studio (OpenAI-совместимый API).
                          Требует YANDEX_API_KEY и YANDEX_FOLDER_ID в окружении.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

from dotenv import load_dotenv

load_dotenv()  # подхватывает .env из корня репозитория, если он есть; иначе no-op

YANDEX_BASE_URL = "https://ai.api.cloud.yandex.net/v1"

SYSTEM_PROMPT = (
    "Ты — эксперт по обогащению и металлургии, помогаешь генерировать проверяемые "
    "научно-технические гипотезы по улучшению целевого технологического свойства "
    "на основе предоставленных фрагментов базы знаний. Отвечай СТРОГО валидным JSON "
    "без markdown-обрамления, без комментариев, без пояснений вне JSON."
)

RESPONSE_FORMAT_HINT = """
Верни JSON строго такой структуры:
{
  "hypotheses": [
    {
      "hyp_id": "<uuid строка>",
      "statement": "<формулировка гипотезы, 1-2 предложения>",
      "mechanism": "<предполагаемый механизм действия>",
      "sources": [{"doc_id": "<uuid>", "chunk_id": "<uuid>", "citation": "<текст ссылки>"}],
      "target_property_impact": "<ожидаемое влияние на целевое свойство>",
      "raw_llm_novelty_note": "<краткий комментарий о новизне>"
    }
  ]
}
Используй только doc_id/chunk_id, которые реально присутствуют в предоставленных чанках.
Сгенерируй от 2 до 5 гипотез.
"""


def _new_id() -> str:
    return str(uuid.uuid4())


def _build_user_prompt(retrieval_result: dict[str, Any]) -> str:
    query = retrieval_result["query"]
    chunks = retrieval_result["retrieved_chunks"]

    chunks_text = "\n".join(
        f"- chunk_id={c['chunk_id']} doc_id={c['doc_id']} "
        f"(similarity={c['similarity']}): {c['text']} [{c['source_citation']}]"
        for c in chunks
    )

    return (
        f"Целевое свойство: {query['target_property']}\n"
        f"Ограничения: {json.dumps(query['constraints'], ensure_ascii=False)}\n\n"
        f"Найденные релевантные фрагменты базы знаний:\n{chunks_text}\n\n"
        f"{RESPONSE_FORMAT_HINT}"
    )


def _mock_generate(retrieval_result: dict[str, Any]) -> dict[str, Any]:
    """Детерминированный мок без сети: по одной гипотезе на каждый из первых
    трёх чанков, чтобы можно было тестировать весь пайплайн без ключей Yandex."""
    query = retrieval_result["query"]
    chunks = retrieval_result["retrieved_chunks"][:3]

    hypotheses = []
    for chunk in chunks:
        hypotheses.append(
            {
                "hyp_id": _new_id(),
                "statement": (
                    f"[MOCK] Применение подхода из источника позволит продвинуться "
                    f"к цели: {query['target_property']}"
                ),
                "mechanism": f"[MOCK] Механизм основан на фрагменте: {chunk['text'][:120]}",
                "sources": [
                    {
                        "doc_id": chunk["doc_id"],
                        "chunk_id": chunk["chunk_id"],
                        "citation": chunk["source_citation"],
                    }
                ],
                "target_property_impact": "[MOCK] Оценка эффекта появится после интеграции реальной LLM",
                "raw_llm_novelty_note": "[MOCK] Заглушка USE_MOCK_LLM=true, реальная оценка новизны не считалась",
            }
        )

    if not hypotheses:
        hypotheses.append(
            {
                "hyp_id": _new_id(),
                "statement": f"[MOCK] Гипотеза-заглушка для цели: {query['target_property']}",
                "mechanism": "[MOCK] Нет найденных чанков — механизм не может быть обоснован источниками.",
                "sources": [],
                "target_property_impact": "[MOCK] Неизвестно",
                "raw_llm_novelty_note": "[MOCK] Сгенерировано без retrieved_chunks",
            }
        )

    return {"hypotheses": hypotheses}


def _parse_llm_json(raw_content: str) -> dict[str, Any]:
    content = raw_content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:]
    return json.loads(content)


def _call_yandex_llm(prompt: str) -> str:
    from openai import OpenAI  # локальный импорт, чтобы мок-режим не требовал пакета openai

    api_key = os.environ["YANDEX_API_KEY"]
    folder_id = os.environ["YANDEX_FOLDER_ID"]
    # or, а не .get(key, default) — в .env часто остаётся "YANDEX_MODEL_URI="
    # (переменная существует, но пустая строка), .get() в этом случае вернул
    # бы "" вместо дефолта.
    model_uri = os.environ.get("YANDEX_MODEL_URI") or f"gpt://{folder_id}/yandexgpt/latest"

    client = OpenAI(api_key=api_key, base_url=YANDEX_BASE_URL)

    completion = client.chat.completions.create(
        model=model_uri,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    return completion.choices[0].message.content


def generate_hypotheses(retrieval_result: dict[str, Any]) -> dict[str, Any]:
    """Генерирует гипотезы по retrieval_result. См. модульный docstring про USE_MOCK_LLM."""
    use_mock = os.environ.get("USE_MOCK_LLM", "true").lower() in ("1", "true", "yes")

    if use_mock:
        return _mock_generate(retrieval_result)

    prompt = _build_user_prompt(retrieval_result)

    last_error: Exception | None = None
    for attempt in range(2):  # первая попытка + один retry при невалидном JSON
        raw_content = _call_yandex_llm(prompt)
        try:
            parsed = _parse_llm_json(raw_content)
            if "hypotheses" not in parsed:
                raise ValueError("В ответе LLM отсутствует ключ 'hypotheses'")
            return parsed
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            prompt = (
                prompt
                + f"\n\nПредыдущий ответ был невалидным JSON ({e}). "
                + "Верни ТОЛЬКО валидный JSON без каких-либо пояснений."
            )

    raise RuntimeError(f"Yandex LLM не вернула валидный JSON после retry: {last_error}")


if __name__ == "__main__":
    import sys
    from pathlib import Path

    mock_retrieval_path = (
        Path(__file__).resolve().parents[2]
        / "mock_data"
        / "retrieval_results"
        / "retrieval_regrind.json"
    )
    if len(sys.argv) > 1:
        mock_retrieval_path = Path(sys.argv[1])

    retrieval_result = json.loads(mock_retrieval_path.read_text(encoding="utf-8"))
    print(json.dumps(generate_hypotheses(retrieval_result), ensure_ascii=False, indent=2))
