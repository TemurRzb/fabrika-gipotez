"""Тест модуля ingestion на моках: создаём временные .docx/.pdf и проверяем,
что ingest() возвращает объект, валидный по schemas/document.schema.json,
а неподдерживаемые пока форматы (xlsx, png) явно кидают NotImplementedError.
"""
import docx
import pytest
from reportlab.pdfgen import canvas

from modules.ingestion.ingest import ingest
from schemas.validate_schema import validate


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


def test_ingest_xlsx_not_implemented_yet(tmp_path):
    file_path = tmp_path / "sample.xlsx"
    file_path.write_bytes(b"")

    with pytest.raises(NotImplementedError):
        ingest(str(file_path))


def test_ingest_scan_not_implemented_yet(tmp_path):
    file_path = tmp_path / "sample.png"
    file_path.write_bytes(b"")

    with pytest.raises(NotImplementedError):
        ingest(str(file_path))
