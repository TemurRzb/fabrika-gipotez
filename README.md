# Фабрика гипотез

Система принимает целевое технологическое свойство (например, "повысить извлечение
золота из лежалых хвостов флотации на 15%"), ограничения (сырьё, бюджет, оборудование)
и базу знаний (xlsx/docx/pdf с текстовым слоем/pdf-сканы/png), а на выходе выдаёт список
проверяемых гипотез с обоснованием, ссылками на источники, оценкой новизны/рисков/ценности
и опциональной дорожной картой проверки.

## Архитектура: 5 модулей, 4 контракта

```
                document.schema.json          retrieval_result.schema.json
                        |                                |
 [ingestion] ---------->|----> [rag_core] -------------->|----> [hypothesis_gen]
  парсинг xlsx/docx/            чанкинг, эмбеддинги,             генерация гипотез
  pdf/png, OCR                  векторный поиск                 через Yandex AI Studio
                                                                          |
                                                     raw_hypotheses.schema.json
                                                                          |
                                                                          v
                                                                    [ranking]
                                                      ранжирование, не-LLM скоринг
                                                                          |
                                                    ranked_hypotheses.schema.json
                                                                          |
                                                                          v
                                                              [orchestrator_ui]
                                                        Streamlit UI, экспорт, деплой
```

Каждый модуль — своя папка в `/modules/`, один человек = один модуль.
Контракты между модулями зафиксированы как JSON Schema (draft-07) в `/schemas/` —
**это единственное, что нельзя менять в одиночку** без согласования с соседними модулями.

| Модуль | Папка | Вход | Выход |
|---|---|---|---|
| ingestion | [`modules/ingestion`](modules/ingestion) | путь к файлу | [`document.schema.json`](schemas/document.schema.json) |
| rag_core | [`modules/rag_core`](modules/rag_core) | query + документы | [`retrieval_result.schema.json`](schemas/retrieval_result.schema.json) |
| hypothesis_gen | [`modules/hypothesis_gen`](modules/hypothesis_gen) | retrieval_result | [`raw_hypotheses.schema.json`](schemas/raw_hypotheses.schema.json) |
| ranking | [`modules/ranking`](modules/ranking) | raw_hypotheses + constraints | [`ranked_hypotheses.schema.json`](schemas/ranked_hypotheses.schema.json) |
| orchestrator_ui | [`modules/orchestrator_ui`](modules/orchestrator_ui) | все предыдущие | Streamlit UI, экспорт |

Каждая папка модуля уже содержит **рабочий скелет**, который прямо сейчас (без ключей,
без готовых соседних модулей) запускается на мок-данных из `/mock_data/` и возвращает
валидный по соответствующей схеме результат. Подробный TODO-план для каждого модуля —
в `modules/<module>/README.md`.

## LLM: только Yandex AI Studio

- Base URL: `https://ai.api.cloud.yandex.net/v1` (OpenAI-совместимый Responses/Completion API).
- **YandexGPT Lite** — дешёвые точечные задачи (классификация, извлечение полей) в `ingestion`/`rag_core`.
- **YandexGPT Pro / Alice AI LLM** — единственное место, где нужна сильная модель: генерация гипотез в `hypothesis_gen`.
- **text-embeddings** — эмбеддинги для RAG в `rag_core` (пока не подключены, TF-IDF заглушка).
- **Vector Store API** — векторное хранилище, своё не поднимаем.
- Ключи конфигурируются через `.env` (см. [`.env.example`](.env.example)): `YANDEX_API_KEY`, `YANDEX_FOLDER_ID`. Без ключей `hypothesis_gen` работает в мок-режиме (`USE_MOCK_LLM=true` по умолчанию) — весь пайплайн запускается и без ключей.

## Быстрый старт

```bash
pip install -r requirements.txt
cp .env.example .env   # заполнить ключи, когда будут готовы; по умолчанию не нужны (USE_MOCK_LLM=true)

# прогнать весь пайплайн одной командой на моках
python scripts/run_pipeline.py
# или (если есть make): make run-pipeline

# прогнать на реальных файлах (.docx/.pdf уже поддержаны)
python scripts/run_pipeline.py --files "путь/файл1.docx" "путь/файл2.pdf"

# UI
streamlit run modules/orchestrator_ui/app.py
# или: make ui

# все тесты всех модулей
pytest -v
# или: make test
```

## Таймлайн команды (5 человек, дедлайн через 2.5 дня)

**День 1 (сегодня)**
- Каждый берёт свой модуль из `/modules/`, читает его `README.md` (TODO-список, MVP на случай нехватки времени).
- Работаем параллельно на мок-данных из `/mock_data/` — не ждём, пока сосед закончит.
- **Вечерний чекпоинт: сквозная интеграция на моках.** Каждый прогоняет `python scripts/run_pipeline.py` — пайплайн должен пройти end-to-end без ошибок (это уже так на моках прямо сейчас).

**День 2**
- Днём: подключаем реальные данные (файлы из `Задача 1/`, реальные ключи Yandex AI Studio) вместо моков. **Чекпоинт: пайплайн проходит на реальных данных.**
- Вечером: **feature freeze** — новые фичи не берём, только стабилизация и баг-фиксы.

**День 3**
- Стабилизация, деплой UI, запись демо-видео, подготовка презентации.
- **Сдача до 23:59.**

## Структура репозитория

```
/schemas/            JSON Schema (draft-07) для всех 4 интерфейсов + validate_schema.py
/modules/
  ingestion/          парсинг xlsx/docx/pdf/png, OCR
  rag_core/           чанкинг, эмбеддинги, векторный поиск
  hypothesis_gen/     генерация гипотез через Yandex AI Studio
  ranking/            ранжирование, не-LLM скоринг
  orchestrator_ui/    Streamlit UI, экспорт, деплой
/mock_data/          мок-примеры для всех 4 шагов пайплайна (видны всем модулям)
/scripts/
  run_pipeline.py     сквозной прогон всего пайплайна одной командой
```

## Правило совместной работы

Меняешь JSON Schema в `/schemas/` — сначала пиши в общий чат: это контракт между
модулями, ломающие изменения блокируют всех. Внутри своего модуля (`/modules/<name>/`)
можно менять что угодно, лишь бы вход/выход соответствовали схеме — проверяется
через `schemas/validate_schema.py` и тесты в `modules/<name>/tests/`.
