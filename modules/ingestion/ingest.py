"""
Модуль ingestion: приём и предобработка данных базы знаний.

Вход: путь к файлу (.docx, .pdf, .xlsx, .png/.jpg).
Выход: dict, валидный по schemas/document.schema.json.

Статус на сейчас:
  - .docx: работает (python-docx)
  - .pdf с текстовым слоем: работает (pdfplumber)
  - .pdf-сканы/фото (нет текстового слоя): работает через OCR постранично
    (pypdfium2 рендерит страницу в изображение, Tesseract распознаёт текст)
  - .png/.jpg сканы/схемы: работает через OCR (pytesseract)
  - .xlsx: работает (openpyxl) — каждый лист становится одной таблицей в
    tables[] с сырыми данными ячеек; для полнотекстового поиска все непустые
    ячейки листа также собираются в один section.text

Также есть ingest_folder(folder_path, cache_dir) — обрабатывает всю папку
рекурсивно с кэшированием результата на диске (см. докстринг функции), чтобы
не перепарсивать (и не перезапускать OCR) одни и те же файлы при повторных
запусках пайплайна.

OCR требует системный движок Tesseract:
  - Windows: winget install --id UB-Mannheim.TesseractOCR
  - Codespaces/Debian: sudo apt-get install -y tesseract-ocr tesseract-ocr-rus
См. README.md модуля, раздел "OCR", если Tesseract не находится автоматически.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

import docx  # python-docx
import openpyxl
import pdfplumber
import pytesseract
from PIL import Image

_SUPPORTED_EXTENSIONS = {".docx", ".pdf", ".xlsx", ".png", ".jpg", ".jpeg"}
_DEFAULT_CACHE_DIR = "data/parsed_documents"

# Порог: если на странице pdf извлечено меньше символов текста, чем это значение,
# считаем страницу сканом/фото (а не набранным текстом) и запускаем OCR.
_MIN_TEXT_CHARS_PER_PAGE = 20
# DPI рендеринга страницы pdf в изображение перед OCR — компромисс между
# качеством распознавания и скоростью.
_PDF_OCR_RESOLUTION = 200
_TESSERACT_LANG = "rus+eng"

# На Windows winget-инсталлятор Tesseract не всегда кладёт исполняемый файл в PATH.
# Если tesseract не найден в PATH, но стоит в дефолтную папку — используем её явно.
_DEFAULT_WINDOWS_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if shutil.which("tesseract") is None and os.path.exists(_DEFAULT_WINDOWS_TESSERACT_CMD):
    pytesseract.pytesseract.tesseract_cmd = _DEFAULT_WINDOWS_TESSERACT_CMD


def _new_id() -> str:
    return str(uuid.uuid4())


def _ocr_image(image: "Image.Image") -> tuple[str, float]:
    """Распознаёт текст на изображении через Tesseract OCR.

    Возвращает (распознанный_текст, средняя_уверенность 0..1). Уверенность
    считается по словам с conf >= 0 (Tesseract отдаёт -1 для служебных блоков).
    """
    data = pytesseract.image_to_data(image, lang=_TESSERACT_LANG, output_type=pytesseract.Output.DICT)

    words: list[str] = []
    confidences: list[float] = []
    for word, conf_raw in zip(data["text"], data["conf"]):
        word = word.strip()
        try:
            conf = float(conf_raw)
        except ValueError:
            continue
        if word and conf >= 0:
            words.append(word)
            confidences.append(conf)

    text = " ".join(words)
    avg_confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    return text, avg_confidence


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


def _ingest_pdf(file_path: Path, max_pages: int | None = None) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    ocr_confidences: list[float] = []

    with pdfplumber.open(str(file_path)) as pdf:
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        for page_number, page in enumerate(pages, start=1):
            text = (page.extract_text() or "").strip()

            if len(text) < _MIN_TEXT_CHARS_PER_PAGE:
                # Текстового слоя почти нет — вероятно, страница это фото/скан
                # (см. "Дополнительные материалы" в задаче), а не набранный текст.
                # Рендерим страницу в изображение (pypdfium2, без системных
                # зависимостей вроде poppler) и распознаём через Tesseract.
                rendered_image = page.to_image(resolution=_PDF_OCR_RESOLUTION).original
                text, confidence = _ocr_image(rendered_image)
                ocr_confidences.append(confidence)

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
        sections = [{"heading": "", "text": "", "page_range": [1, 1]}]

    full_text = "\n\n".join(s["text"] for s in sections if s["text"])
    avg_ocr_confidence = (
        round(sum(ocr_confidences) / len(ocr_confidences), 4) if ocr_confidences else None
    )

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
            "ocr_confidence": avg_ocr_confidence,
            "extra": {"pages_total": len(sections), "ocr_pages": len(ocr_confidences)},
        },
    }


def _format_xlsx_cell(cell: Any) -> str:
    if cell is None:
        return ""
    if isinstance(cell, float):
        # 6 значащих цифр вместо полной точности float (например, вместо
        # "4.9191001807039534e-05" — "4.9191e-05"). Реальные xlsx отчётов
        # часто содержат формулы вроде "=B2/B10*100", которые openpyxl
        # (data_only=True) отдаёт как посчитанный float с длинным хвостом.
        return f"{cell:.6g}"
    return str(cell)


def _ingest_xlsx(file_path: Path) -> dict[str, Any]:
    """Каждый лист становится одной таблицей в tables[] (caption = имя листа,
    page=None — у xlsx нет страниц). Непустые ячейки листа также собираются в
    section.text для полнотекстового поиска (см. rag_core)."""
    workbook = openpyxl.load_workbook(str(file_path), data_only=True, read_only=True)

    sections: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []

    for sheet in workbook.worksheets:
        rows: list[list[str]] = []
        sheet_text_parts: list[str] = []
        for row in sheet.iter_rows(values_only=True):
            cells = [_format_xlsx_cell(cell) for cell in row]
            rows.append(cells)
            sheet_text_parts.extend(c for c in cells if c)

        tables.append({"caption": sheet.title, "data": rows, "page": None})
        sections.append(
            {
                "heading": sheet.title,
                "text": " ".join(sheet_text_parts),
                "page_range": [1, 1],
            }
        )

    if not sections:
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
            "file_type": "xlsx",
            "ocr_confidence": None,
            "extra": {"sheet_count": len(workbook.worksheets)},
        },
    }


def _ingest_scan(file_path: Path) -> dict[str, Any]:
    """OCR для png/jpg — схемы, регламенты, списки оборудования и т.п.
    Основной ценный контент таких файлов часто графический (схема флотации),
    а OCR извлекает подписи/текстовые блоки, которые на ней есть."""
    image = Image.open(file_path).convert("RGB")
    text, confidence = _ocr_image(image)

    suffix = file_path.suffix.lower()
    file_type = "jpg" if suffix in (".jpg", ".jpeg") else "png"

    return {
        "doc_id": _new_id(),
        "source_type": "other",
        "title": file_path.stem,
        "authors": [],
        "date": None,
        "language": "ru",
        "full_text": text,
        "sections": [{"heading": "", "text": text, "page_range": [1, 1]}],
        "tables": [],
        "metadata": {
            "file_name": file_path.name,
            "file_type": file_type,
            "ocr_confidence": round(confidence, 4),
            "extra": {"ocr_engine": "tesseract"},
        },
    }


def ingest(file_path: str, max_pages: int | None = None) -> dict[str, Any]:
    """Парсит файл и возвращает dict, валидный по document.schema.json.

    max_pages: ограничить число обрабатываемых страниц pdf (полезно для быстрой
    проверки на больших сканированных pdf, где OCR всех страниц может быть долгим).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {file_path}")

    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _ingest_docx(path)
    if suffix == ".pdf":
        return _ingest_pdf(path, max_pages=max_pages)
    if suffix == ".xlsx":
        return _ingest_xlsx(path)
    if suffix in (".png", ".jpg", ".jpeg"):
        return _ingest_scan(path)

    raise ValueError(f"Неподдерживаемый тип файла: {suffix}")


def _cache_key(file_path: Path) -> str:
    """Ключ кэша на основе пути+mtime+размера файла (без чтения содержимого —
    быстро даже для больших сканов). Меняется, если файл изменился/переместился,
    что автоматически инвалидирует старый кэш для этого файла."""
    stat = file_path.stat()
    raw = f"{file_path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def ingest_folder(
    folder_path: str,
    cache_dir: str = _DEFAULT_CACHE_DIR,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    """Рекурсивно обрабатывает все поддерживаемые файлы в папке, с кэшированием
    результата на диске в cache_dir (один JSON-файл на исходный документ).

    Кэш-ключ строится из пути+времени изменения+размера файла: если файл не
    менялся с прошлого запуска — результат берётся из кэша без повторного
    парсинга/OCR, что критично для больших сканированных pdf. Если исходный
    файл изменился (или это первый запуск) — файл парсится через ingest() и
    результат сохраняется в кэш.

    Файлы неподдерживаемых форматов и временные Excel-локи (~$...) пропускаются
    молча. Ошибки парсинга отдельных файлов не прерывают обработку остальных —
    печатаются в stderr и пропускаются.

    Возвращает список dict, валидных по document.schema.json (порядок — по
    отсортированному пути файла, для стабильности между запусками).
    """
    folder = Path(folder_path)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    documents: list[dict[str, Any]] = []

    for file_path in sorted(folder.rglob("*")):
        if not file_path.is_file() or file_path.name.startswith("~$"):
            continue
        if file_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            continue

        cache_file = cache / f"{_cache_key(file_path)}.json"

        if cache_file.exists():
            documents.append(json.loads(cache_file.read_text(encoding="utf-8")))
            continue

        try:
            result = ingest(str(file_path), max_pages=max_pages)
        except Exception as e:  # noqa: BLE001 - не должно прерывать обработку остальной папки
            print(f"[ingest_folder] пропуск {file_path.name}: {e}", file=sys.stderr)
            continue

        cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        documents.append(result)

    return documents


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Парсинг файла или папки в document.schema.json")
    parser.add_argument("path", help="Путь к файлу или папке")
    parser.add_argument("--folder", action="store_true", help="Обработать path как папку (ingest_folder)")
    parser.add_argument("--cache-dir", default=_DEFAULT_CACHE_DIR, help="Папка кэша (только для --folder)")
    parser.add_argument("--max-pages", type=int, default=None, help="Ограничение страниц pdf")
    args = parser.parse_args()

    if args.folder:
        docs = ingest_folder(args.path, cache_dir=args.cache_dir, max_pages=args.max_pages)
        print(f"Обработано документов: {len(docs)} (кэш: {args.cache_dir})", file=sys.stderr)
        print(json.dumps(docs, ensure_ascii=False, indent=2))
    else:
        result = ingest(args.path, max_pages=args.max_pages)
        print(json.dumps(result, ensure_ascii=False, indent=2))
