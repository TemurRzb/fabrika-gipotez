# hypothesis_gen

Генерация гипотез поверх Yandex AI Studio (YandexGPT Pro / Alice AI LLM — единственное
место в пайплайне, где нужна сильная модель). Структурированный JSON-вывод.

**Вход:** `retrieval_result` ([`schemas/retrieval_result.schema.json`](../../schemas/retrieval_result.schema.json)).
**Выход должен соответствовать** [`schemas/raw_hypotheses.schema.json`](../../schemas/raw_hypotheses.schema.json).

## Статус скелета

Функция `generate_hypotheses(retrieval_result: dict) -> dict` в [`generate.py`](generate.py):
- реальный клиент через `openai` python SDK, `base_url=https://ai.api.cloud.yandex.net/v1`;
- модель задаётся `YANDEX_MODEL_URI` (по умолчанию `gpt://<YANDEX_FOLDER_ID>/yandexgpt/latest`);
- промпт просит строго JSON по схеме `raw_hypotheses.schema.json`;
- при невалидном JSON — один retry с уточняющим сообщением;
- **`USE_MOCK_LLM=true` по умолчанию** — без сети и без ключей, детерминированный мок
  на основе `retrieved_chunks`, чтобы вся команда могла тестировать пайплайн без ключей.

## TODO по хронологии

1. **(30 мин)** Прогнать скелет в мок-режиме: `python modules/hypothesis_gen/generate.py` (по умолчанию `USE_MOCK_LLM=true`).
2. **(как только появятся ключи от организаторов)** Заполнить `.env` (`YANDEX_API_KEY`, `YANDEX_FOLDER_ID`), выставить `USE_MOCK_LLM=false`, прогнать `_call_yandex_llm` вручную — проверить, что модель действительно возвращает JSON, а не текст с markdown-обрамлением (обработка ```json уже есть в `_parse_llm_json`, но промпт может потребовать доводки).
3. **(1-2 ч)** Подобрать промпт под реальный домен (обогащение/металлургия, хвосты, флотация — см. `mock_data/` и папку `Задача 1/` для примеров реальных гипотез от организаторов) — сверить стиль и глубину со сгенерированными организаторами `Гипотезы *.docx`.
4. **(1 ч)** Добавить few-shot примеры в промпт на основе реальных `Гипотезы *.docx` из `Задача 1/Пример */` — повышает качество и формат вывода.
5. **(опционально)** Ограничение по токенам/стоимости: обрезать `retrieved_chunks` до top-N по `similarity`, если промпт становится слишком длинным.
6. **(опционально)** Батчинг: генерация нескольких гипотез отдельными вызовами вместо одного большого запроса, если модель плохо держит формат при большом числе гипотез сразу.

## MVP на случай нехватки времени

Мок-режим (`USE_MOCK_LLM=true`) уже даёт валидный по схеме output — этого достаточно, чтобы `ranking` и `orchestrator_ui` работали и показывали сквозной пайплайн, даже если реальную интеграцию с Yandex не успеете доделать или не будет ключей.

## Рекомендованные библиотеки

- `openai` (python SDK, используется как OpenAI-совместимый клиент для Yandex AI Studio)
- `python-dotenv` (опционально, для локальной загрузки `.env`)

## Как тестировать независимо

```bash
pip install -r requirements.txt

# мок-режим (по умолчанию, без ключей)
pytest modules/hypothesis_gen/tests/test_hypothesis_gen.py -v
python modules/hypothesis_gen/generate.py

# с реальным API (когда появятся ключи)
export USE_MOCK_LLM=false
export YANDEX_API_KEY=...
export YANDEX_FOLDER_ID=...
python modules/hypothesis_gen/generate.py
```
