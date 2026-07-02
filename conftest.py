"""Корневой conftest.py: делает возможными абсолютные импорты вида
`from schemas.validate_schema import validate` и
`from modules.ingestion.ingest import ingest` из любого тестового файла в репозитории,
независимо от того, откуда запущен pytest.
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
