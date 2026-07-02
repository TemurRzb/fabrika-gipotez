"""
Модуль ingestion: приём и предобработка данных базы знаний.

Вход: путь к файлу (.docx, .pdf, .xlsx, .png/.jpg).
Выход: dict, валидный по schemas/document.schema.json.

Статус на сейчас:
  - .docx: работает (python-docx)
  - .pdf с текстовым слоем: работает (pdfplumber)
  - .xlsx: заглушка (TODO)
  - .png/.jpg сканы (OCR): заглушка (TODO)
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import docx  # python-docx
import pdfplumber


def _new_id() -> str:
    return str(uuid.uuid4())


def _ingest_docx(file_path: Path) -> dict[str, Any]:
    document = docx.Document(str(file_path))

    sections: list[dict[str, Any]] = []
    current_heading = ""
    current_text_parts: list[str] = []

    def flush_section() -> None:
        if current_text_parts:
            sections.append(
                {
                    "heading": current_heading,
                    "text": "\n".join(current_text_parts).strip(),
                    # У .docx нет постраничной разбивки без рендеринга — кладём [1, 1]
                    # как заглушку. TODO: посчитать реальные страницы через рендер в PDF при необходимости.
                    "page_range": [1, 1],
                }
            )

    for para in document.paragraphs:
        style_name = (para.style.name if para.style else "") or ""
        text = para.text.strip()
        if not text:
            continue
        if style_name.lower().startswith("heading"):
            flush_section()
            current_heading = text
            current_text_parts = []
        else:
            current_text_parts.append(text)
    flush_section()

    if not sections:
        sections = [{"heading": "", "text": "", "page_range": [1, 1]}]

    full_text = "\n\n".join(s["text"] for s in sections if s["text"])

    tables: list[dict[str, Any]] = []
    for table in document.tables:
        data = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        tables.append({"caption": "", "data": data, "page": None})

    return {
        "doc_id": _new_id(),
        "source_type": "other",
        "title": file_path.stem,
        "authors": [],
        "date": None,
        "language": "ru",
        "full_text": full_text,
        "sections": sections,
        "tables": tables,
        "metadata": {
            "file_name": file_path.name,
            "file_type": "docx",
            "ocr_confidence": None,
            "extra": {},
        },
    }


def _ingest_pdf(file_path: Path) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []

    with pdfplumber.open(str(file_path)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                sections.append(
                    {
                        "heading": f"Страница {page_number}",
                        "text": text,
                        "page_range": [page_number, page_number],
                    }
                )
            for extracted_table in page.extract_tables():
                rows = [[str(cell) if cell is not None else "" for cell in row] for row in extracted_table]
                tables.append({"caption": "", "data": rows, "page": page_number})

    if not sections:
        # Текстового слоя нет — вероятно, скан. Это НЕ ошибка ingestion как такового,
        # но за пределами MVP: см. NotImplementedError в _ingest_scan для явного OCR-пути.
        sections = [{"heading": "", "text": "", "page_range": [1, 1]}]

    full_text = "\n\n".join(s["text"] for s in sections if s["text"])

    return {
        "doc_id": _new_id(),
        "source_type": "other",
        "title": file_path.stem,
        "authors": [],
        "date": None,
        "language": "ru",
        "full_text": full_text,
        "sections": sections,
        "tables": tables,
        "metadata": {
            "file_name": file_path.name,
            "file_type": "pdf",
            "ocr_confidence": None,
            "extra": {"pages_total": len(sections)},
        },
    }


def _ingest_xlsx(file_path: Path) -> dict[str, Any]:
    raise NotImplementedError(
        "xlsx ingestion ещё не реализован. TODO: читать через openpyxl "
        "(лист -> tables[].data, caption = имя листа), page=None для xlsx. "
        "Смотри пример структуры в mock_data/documents/doc_report_tailings.json."
    )


def _ingest_scan(file_path: Path) -> dict[str, Any]:
    raise NotImplementedError(
        "OCR для сканов (png/jpg) ещё не реализован. TODO: подключить pytesseract "
        "или Yandex OCR API, заполнить metadata.ocr_confidence реальным значением "
        "(не null), сложить распознанный текст в один section с heading=''. "
        "Смотри пример структуры в mock_data/documents/doc_patent_flotation_reagent.json."
    )


def ingest(file_path: str) -> dict[str, Any]:
    """Парсит файл и возвращает dict, валидный по document.schema.json."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {file_path}")

    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _ingest_docx(path)
    if suffix == ".pdf":
        return _ingest_pdf(path)
    if suffix == ".xlsx":
        return _ingest_xlsx(path)
    if suffix in (".png", ".jpg", ".jpeg"):
        return _ingest_scan(path)

    raise ValueError(f"Неподдерживаемый тип файла: {suffix}")


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) != 2:
        print("Использование: python ingest.py <path_to_file>")
        raise SystemExit(2)

    result = ingest(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
