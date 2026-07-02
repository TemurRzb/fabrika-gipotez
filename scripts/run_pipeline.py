"""
Сквозной прогон всего пайплайна: ingestion -> rag_core -> hypothesis_gen -> ranking.

Это и есть интеграционный чекпоинт, который команда прогоняет вечером дня 1
на моках (по умолчанию) и днём дня 2 на реальных данных (--files).

Использование:
    # на мок-документах (mock_data/documents/*.json), USE_MOCK_LLM=true по умолчанию
    python scripts/run_pipeline.py

    # со своей целью и ограничениями
    python scripts/run_pipeline.py --target-property "Повысить извлечение золота на 15%" \\
        --materials "лежалые хвосты" --equipment "флотомашина"

    # на реальных файлах (.docx/.pdf уже поддержаны ingestion)
    python scripts/run_pipeline.py --files "путь/файл1.docx" "путь/файл2.pdf"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from modules.hypothesis_gen.generate import generate_hypotheses  # noqa: E402
from modules.ingestion.ingest import ingest  # noqa: E402
from modules.ranking.rank import rank  # noqa: E402
from modules.rag_core.retrieve import retrieve  # noqa: E402

MOCK_DOCUMENTS_DIR = ROOT_DIR / "mock_data" / "documents"

DEFAULT_TARGET_PROPERTY = "Повысить извлечение золота из лежалых хвостов флотации на 15%"


def _load_mock_documents() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in MOCK_DOCUMENTS_DIR.glob("*.json")]


def _ingest_real_files(file_paths: list[str]) -> list[dict]:
    documents = []
    for file_path in file_paths:
        try:
            documents.append(ingest(file_path))
            print(f"[ingestion] OK: {file_path}", file=sys.stderr)
        except NotImplementedError as e:
            print(f"[ingestion] ПРОПУЩЕН (не реализовано): {file_path} — {e}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"[ingestion] ОШИБКА: {file_path} — {e}", file=sys.stderr)
    return documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-property", default=DEFAULT_TARGET_PROPERTY, help="Целевое технологическое свойство"
    )
    parser.add_argument("--materials", nargs="*", default=[], help="Доступное сырьё/реагенты")
    parser.add_argument("--budget", default=None, help="Бюджетное ограничение")
    parser.add_argument("--equipment", nargs="*", default=[], help="Доступное оборудование")
    parser.add_argument("--regulatory", nargs="*", default=[], help="Регуляторные ограничения")
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Пути к реальным файлам базы знаний (.docx/.pdf). Без этого флага используются mock_data/documents",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print("=== Шаг 1/4: ingestion ===", file=sys.stderr)
    if args.files:
        documents = _ingest_real_files(args.files)
        if not documents:
            print("Ни один файл не был успешно распознан, используем mock_data/documents", file=sys.stderr)
            documents = _load_mock_documents()
    else:
        documents = _load_mock_documents()
        print(f"Загружено {len(documents)} мок-документов из {MOCK_DOCUMENTS_DIR}", file=sys.stderr)

    constraints = {
        "materials": args.materials,
        "budget": args.budget,
        "equipment": args.equipment,
        "regulatory": args.regulatory,
    }
    query = {"target_property": args.target_property, "constraints": constraints}

    print("=== Шаг 2/4: rag_core (retrieve) ===", file=sys.stderr)
    retrieval_result = retrieve(query, documents)
    print(f"Найдено {len(retrieval_result['retrieved_chunks'])} релевантных чанков", file=sys.stderr)

    print("=== Шаг 3/4: hypothesis_gen (generate_hypotheses) ===", file=sys.stderr)
    raw_hypotheses = generate_hypotheses(retrieval_result)
    print(f"Сгенерировано {len(raw_hypotheses['hypotheses'])} гипотез", file=sys.stderr)

    print("=== Шаг 4/4: ranking (rank) ===", file=sys.stderr)
    ranked_hypotheses = rank(raw_hypotheses, constraints)
    print(f"Проранжировано {len(ranked_hypotheses['hypotheses'])} гипотез", file=sys.stderr)

    print("\n=== ИТОГ: ranked_hypotheses ===", file=sys.stderr)
    print(json.dumps(ranked_hypotheses, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
