"""
Общая утилита валидации JSON-объектов по схемам проекта "Фабрика гипотез".

Использование как библиотека:

    from schemas.validate_schema import validate

    validate(document_dict, "document")
    validate(retrieval_result_dict, "retrieval_result")
    validate(raw_hypotheses_dict, "raw_hypotheses")
    validate(ranked_hypotheses_dict, "ranked_hypotheses")

Использование как CLI:

    python schemas/validate_schema.py document mock_data/documents/doc_1.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

SCHEMAS_DIR = Path(__file__).resolve().parent

SCHEMA_FILES = {
    "document": "document.schema.json",
    "retrieval_result": "retrieval_result.schema.json",
    "raw_hypotheses": "raw_hypotheses.schema.json",
    "ranked_hypotheses": "ranked_hypotheses.schema.json",
}

_validator_cache: dict[str, Draft7Validator] = {}


def _load_validator(schema_name: str) -> Draft7Validator:
    if schema_name not in SCHEMA_FILES:
        raise ValueError(
            f"Неизвестная схема '{schema_name}'. Доступные: {sorted(SCHEMA_FILES)}"
        )
    if schema_name not in _validator_cache:
        schema_path = SCHEMAS_DIR / SCHEMA_FILES[schema_name]
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        _validator_cache[schema_name] = Draft7Validator(schema)
    return _validator_cache[schema_name]


def validate(instance: dict[str, Any], schema_name: str) -> None:
    """Валидирует instance по схеме schema_name.

    Собирает все ошибки и бросает ValueError с полным списком, чтобы не
    приходилось перезапускать валидацию по одной ошибке за раз.
    """
    validator = _load_validator(schema_name)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        details = "\n".join(
            f"  - [{'/'.join(str(p) for p in e.path) or '<root>'}] {e.message}"
            for e in errors
        )
        raise ValueError(
            f"Объект не соответствует схеме '{schema_name}' ({len(errors)} ошибок):\n{details}"
        )


def is_valid(instance: dict[str, Any], schema_name: str) -> bool:
    try:
        validate(instance, schema_name)
        return True
    except ValueError:
        return False


def _main() -> int:
    if len(sys.argv) != 3:
        print("Использование: python validate_schema.py <schema_name> <path_to_json>")
        print(f"schema_name один из: {sorted(SCHEMA_FILES)}")
        return 2

    schema_name, json_path = sys.argv[1], sys.argv[2]
    with open(json_path, "r", encoding="utf-8") as f:
        instance = json.load(f)

    try:
        validate(instance, schema_name)
    except ValueError as e:
        print(f"НЕВАЛИДНО: {e}")
        return 1

    print(f"OK: {json_path} соответствует схеме '{schema_name}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
