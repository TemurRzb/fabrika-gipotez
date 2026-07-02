# orchestrator_ui

Оркестрация пайплайна, Streamlit UI, экспорт в PDF/DOCX/CSV/JSON, деплой.

**Собирает воедино** все 4 схемы: `document` -> `retrieval_result` -> `raw_hypotheses` -> `ranked_hypotheses`
(см. [`/schemas`](../../schemas)).

## Статус скелета

- [`mock_pipeline.py`](mock_pipeline.py) — склейка `ingest -> retrieve -> generate_hypotheses -> rank` через реальные функции модулей (которые сегодня уже работают "на моках": TF-IDF вместо эмбеддингов, `USE_MOCK_LLM=true` вместо реального Yandex API). Функция `run_pipeline(target_property, constraints, documents=None)`.
- [`app.py`](app.py) — Streamlit-приложение: форма ввода (целевое свойство, ограничения, загрузка файлов) -> вызов `run_pipeline` -> список гипотез в читаемом виде -> кнопка экспорта в JSON.

## TODO по хронологии

1. **(15 мин)** Запустить `streamlit run modules/orchestrator_ui/app.py` из корня репозитория, прогнать форму без загрузки файлов (сработает на мок-документах) — проверить, что показывается список гипотез.
2. **(30 мин)** Прогнать с загрузкой реального `.docx`/`.pdf` из `Задача 1/` — проверить, что `ingest()` не падает и warning для `.xlsx`/`.png` показывается корректно (пока `NotImplementedError`).
3. **(2-3 ч) Экспорт в PDF/DOCX/CSV**: сейчас есть только JSON-экспорт. Добавить:
   - CSV — `pandas.DataFrame(hypotheses).to_csv()`, самое быстрое.
   - DOCX — `python-docx`, по одной секции на гипотезу.
   - PDF — `reportlab` или рендер DOCX -> PDF при наличии времени (не приоритет).
4. **(1-2 ч)** Индикация прогресса по стадиям пайплайна (retrieval / генерация / ранжирование) вместо одного общего спиннера — полезно, когда реальный Yandex API станет медленнее мока.
5. **(2-4 ч, день 3) Деплой**: поднять Streamlit (Streamlit Community Cloud / Docker + любой VPS) — как только пайплайн стабилен после feature freeze (см. таймлайн в корневом [README.md](../../README.md)).
6. **(опционально)** Сохранение истории запросов (простой JSON-лог в файл) для демонстрации на защите.

## MVP на случай нехватки времени

Текущий JSON-экспорт + отображение гипотез в `st.expander` — уже рабочий MVP для демо. PDF/DOCX/CSV-экспорт можно урезать до одного самого простого формата (CSV) или вовсе показать вручную через JSON, если времени не останется.

## Рекомендованные библиотеки

- `streamlit` (уже используется)
- `pandas` — для CSV-экспорта
- `python-docx` — для DOCX-экспорта (тот же пакет, что и в `ingestion`)
- `reportlab` — для PDF-экспорта (тот же пакет, что и в тестах `ingestion`)

## Как тестировать независимо

```bash
pip install -r requirements.txt

# юнит-тест склейки пайплайна (без UI)
pytest modules/orchestrator_ui/tests/test_orchestrator_ui.py -v

# реальный UI на мок-документах
streamlit run modules/orchestrator_ui/app.py
```
