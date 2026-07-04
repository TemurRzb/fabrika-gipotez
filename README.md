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

| Модуль | Папка | Вход | Выход |
|---|---|---|---|
| ingestion | [`modules/ingestion`](modules/ingestion) | путь к файлу/папке | [`document.schema.json`](schemas/document.schema.json) |
| rag_core | [`modules/rag_core`](modules/rag_core) | query + документы | [`retrieval_result.schema.json`](schemas/retrieval_result.schema.json) |
| hypothesis_gen | [`modules/hypothesis_gen`](modules/hypothesis_gen) | retrieval_result | [`raw_hypotheses.schema.json`](schemas/raw_hypotheses.schema.json) |
| ranking | [`modules/ranking`](modules/ranking) | raw_hypotheses + constraints | [`ranked_hypotheses.schema.json`](schemas/ranked_hypotheses.schema.json) |
| orchestrator_ui | [`modules/orchestrator_ui`](modules/orchestrator_ui) | все предыдущие | Streamlit UI, экспорт |

Контракты между модулями зафиксированы как JSON Schema (draft-07) в `/schemas/` —
**это единственное, что нельзя менять в одиночку** без согласования с соседними модулями.
Подробности и TODO по каждому модулю — в `modules/<module>/README.md`.

## LLM и эмбеддинги

- **Эмбеддинги** (`rag_core`, и `ranking` для оценки новизны) — локальная модель
  `intfloat/multilingual-e5-small` через `sentence-transformers`, без внешних API.
  Модель скачивается один раз (~470 МБ) при первом запуске.
- **Генерация гипотез** (`hypothesis_gen`) — через **Yandex AI Studio**
  (OpenAI-совместимый API). Нужны `YANDEX_API_KEY` и `YANDEX_FOLDER_ID` в `.env` +
  `USE_MOCK_LLM=false`. Без ключей модуль работает в мок-режиме (`USE_MOCK_LLM=true`,
  значение по умолчанию) — пайплайн не падает, просто гипотезы шаблонные.

## Как запустить

### 1. Установка

```bash
git clone <URL репозитория>
cd fabrika-gipotez
python -m venv .venv
source .venv/Scripts/activate   # Windows git-bash; на PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. OCR (нужен для сканов/фото в ingestion)

```bash
# Windows:
winget install --id UB-Mannheim.TesseractOCR
# Codespaces/Debian:
sudo apt-get update && sudo apt-get install -y tesseract-ocr tesseract-ocr-rus
```

### 3. Ключи Yandex AI Studio (по желанию — без них тоже работает, в мок-режиме)

```bash
cp .env.example .env
```
В `.env` заполнить `YANDEX_API_KEY`, `YANDEX_FOLDER_ID`, поставить `USE_MOCK_LLM=false`.

### 4. Запуск всего пайплайна одной командой

```bash
python scripts/run_pipeline.py --target-property "Повысить извлечение золота из упорных сульфидных руд при цианировании на 15%"
```

По умолчанию используется база знаний из `data/parsed_documents/` (31 документ, уже
распарсен и закэширован — ничего дополнительно парсить не нужно).

### 5. UI

```bash
streamlit run modules/orchestrator_ui/app.py
# если команда "streamlit" не находится (PATH):
python -m streamlit run modules/orchestrator_ui/app.py
```

Форма: целевое свойство, ограничения, необязательная загрузка своих файлов (добавятся
к готовой базе знаний, а не заменят её).

### 6. Тесты

```bash
pytest -v
```

### Если видите `HTTP Error 429` от HuggingFace Hub

Это лимит на анонимные запросы (актуально в Codespaces), не ошибка кода — см.
[`modules/rag_core/README.md`](modules/rag_core/README.md#если-видите-ошибки-http-error-429-от-huggingface-hub).

## Структура репозитория

```
/schemas/            JSON Schema (draft-07) для всех 4 интерфейсов + validate_schema.py
/modules/
  ingestion/          парсинг xlsx/docx/pdf/png, OCR
  rag_core/           чанкинг, эмбеддинги, векторный поиск
  hypothesis_gen/     генерация гипотез через Yandex AI Studio
  ranking/            ранжирование, не-LLM скоринг
  orchestrator_ui/    Streamlit UI, экспорт, деплой
/mock_data/          мок-примеры для всех 4 шагов пайплайна (для тестов, не для демо)
/data/
  parsed_documents/   закэшированная база знаний (закоммичена в git)
  embedding_cache.npz предпосчитанные эмбеддинги для неё (закоммичен в git)
/scripts/
  run_pipeline.py     сквозной прогон всего пайплайна одной командой
```

## Правило совместной работы

Меняешь JSON Schema в `/schemas/` — сначала пиши в общий чат: это контракт между
модулями, ломающие изменения блокируют всех. Внутри своего модуля (`/modules/<name>/`)
можно менять что угодно, лишь бы вход/выход соответствовали схеме — проверяется
через `schemas/validate_schema.py` и тесты в `modules/<name>/tests/`.
