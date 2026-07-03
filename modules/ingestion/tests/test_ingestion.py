"""Тест модуля ingestion на моках: создаём временные .docx/.pdf/.png/.xlsx и
проверяем, что ingest() возвращает объект, валидный по schemas/document.schema.json.
png и pdf-сканы проверяются через реальный OCR (Tesseract), тесты пропускаются,
если Tesseract не установлен в системе — см. README.md модуля, раздел "OCR".
"""
import docx
import openpyxl
import pytesseract
import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas

from modules.ingestion.ingest import ingest
from schemas.validate_schema import validate


def _tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


requires_tesseract = pytest.mark.skipif(
    not _tesseract_available(),
    reason="Tesseract OCR не установлен в системе (см. modules/ingestion/README.md, раздел OCR)",
)


def _make_text_image(text: str, path):
    image = Image.new("RGB", (700, 150), color="white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=60)
    draw.text((20, 30), text, fill="black", font=font)
    image.save(str(path))


def test_ingest_docx_matches_schema(tmp_path):
    file_path = tmp_path / "sample.docx"
    document = docx.Document()
    document.add_heading("Вещественный состав хвостов", level=1)
    document.add_paragraph("Хвосты содержат тонковкрапленное золото, ассоциированное с сульфидами.")
    document.save(str(file_path))

    result = ingest(str(file_path))

    validate(result, "document")
    assert result["metadata"]["file_type"] == "docx"
    assert "тонковкрапленное" in result["full_text"]


def test_ingest_pdf_matches_schema(tmp_path):
    # Латиница: базовый шрифт Helvetica в reportlab не содержит глифов кириллицы,
    # это ограничение тестовой фикстуры, а не ingest() — pdfplumber одинаково
    # извлекает текст любого реального PDF независимо от языка.
    file_path = tmp_path / "sample.pdf"
    c = canvas.Canvas(str(file_path))
    c.drawString(100, 750, "Regrinding tailings increases sulfide liberation.")
    c.save()

    result = ingest(str(file_path))

    validate(result, "document")
    assert result["metadata"]["file_type"] == "pdf"
    assert "Regrinding" in result["full_text"]


def test_ingest_xlsx_matches_schema(tmp_path):
    file_path = tmp_path / "sample.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Хвосты"
    sheet.append(["Класс крупности, мкм", "Выход, %", "Содержание Ni, %"])
    sheet.append(["-125+71", "24.5", "0.46"])
    sheet.append(["-71+45", "18.2", "0.31"])
    workbook.save(str(file_path))

    result = ingest(str(file_path))

    validate(result, "document")
    assert result["metadata"]["file_type"] == "xlsx"
    assert result["metadata"]["extra"]["sheet_count"] == 1
    assert len(result["tables"]) == 1
    assert result["tables"][0]["caption"] == "Хвосты"
    assert result["tables"][0]["data"][0] == ["Класс крупности, мкм", "Выход, %", "Содержание Ni, %"]
    assert "24.5" in result["full_text"]


@requires_tesseract
def test_ingest_png_matches_schema_and_runs_ocr(tmp_path):
    file_path = tmp_path / "sample.png"
    _make_text_image("ZOLOTO TAILINGS", file_path)

    result = ingest(str(file_path))

    validate(result, "document")
    assert result["metadata"]["file_type"] == "png"
    assert result["metadata"]["ocr_confidence"] is not None
    assert 0.0 <= result["metadata"]["ocr_confidence"] <= 1.0
    assert "ZOLOTO" in result["full_text"].upper()


@requires_tesseract
def test_ingest_pdf_scan_triggers_ocr(tmp_path):
    # PDF-страница без текстового слоя, только вставленное изображение —
    # имитирует "фото учебника/статьи" из реальной задачи.
    image_path = tmp_path / "page_image.png"
    _make_text_image("SULFIDE OXIDATION", image_path)

    file_path = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(file_path), pagesize=(700, 150))
    c.drawImage(str(image_path), 0, 0, width=700, height=150)
    c.save()

    result = ingest(str(file_path))

    validate(result, "document")
    assert result["metadata"]["ocr_confidence"] is not None
    assert "SULFIDE" in result["full_text"].upper()
