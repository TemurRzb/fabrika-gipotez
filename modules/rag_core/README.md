# rag_core

База знаний / RAG-ядро: чанкинг, эмбеддинги, векторный поиск, извлечение сущностей.

**Вход:** `query` (см. `retrieval_result.schema.json` -> `query`) + список документов (`document.schema.json`).
**Выход должен соответствовать** [`schemas/retrieval_result.schema.json`](../../schemas/retrieval_result.schema.json).

## Статус скелета

Функция `retrieve(query: dict, documents: list[dict]) -> dict` в [`retrieve.py`](retrieve.py):
- чанкинг по абзацам внутри `sections[].text` каждого документа;
- похожесть через **TF-IDF + косинусная близость** (scikit-learn) — работает офлайн, без скачивания моделей и без реального вызова Yandex API;
- `entities` — примитивный regex по числам с единицами измерения (%, мкм, г/л, г/т, pH...);
- `graph_context` всегда пустой.

## TODO по хронологии

1. **(30 мин)** Прогнать `python modules/rag_core/retrieve.py` на `mock_data/documents/*.json` — убедиться, что результат валиден по схеме.
2. **(2-4 ч) Реальные эмбеддинги**: заменить TF-IDF на Yandex AI Studio text-embeddings API.
   - `base_url = https://ai.api.cloud.yandex.net/v1`, ключ/folder_id из `YANDEX_API_KEY`/`YANDEX_FOLDER_ID` (см. `.env.example` в корне).
   - Эмбеддинги чанков считать один раз при загрузке базы, не при каждом запросе.
3. **(2-3 ч) Vector Store API**: залить эмбеддинги в Yandex Vector Store вместо пересчёта в памяти на каждый вызов — не поднимаем своё векторное хранилище.
4. **(1-2 ч)** Улучшить извлечение `entities`: заменить regex-заглушку вызовом YandexGPT Lite (дешёвая модель) с промптом на структурированное извлечение сущностей (material/process/parameter/equipment).
5. **(опционально, если останется время) graph_context**: построить простой граф "сущность -> документ" по извлечённым entities для доп. контекста генерации гипотез.
6. **(опционально)** Гибридный поиск: TF-IDF + эмбеддинги (RRF/взвешенная сумма) для более устойчивого ранжирования.

## MVP на случай нехватки времени

TF-IDF-заглушка — это уже рабочий MVP. Если не успеваете подключить реальные эмбеддинги Yandex — оставляйте как есть, `hypothesis_gen` и дальше по пайплайну не увидят разницы в контракте (только в качестве ранжирования).

## Рекомендованные библиотеки

- `scikit-learn` (TfidfVectorizer, cosine_similarity) — уже используется
- `openai` python sdk (для вызова Yandex AI Studio text-embeddings, OpenAI-совместимый API) — при переходе на реальные эмбеддинги
- `numpy` — векторные операции

## Как тестировать независимо

```bash
pip install -r requirements.txt
pytest modules/rag_core/tests/test_rag_core.py -v

# ручной прогон на мок-документах
python modules/rag_core/retrieve.py "Повысить извлечение золота при цианировании упорных хвостов на 15%"
```
