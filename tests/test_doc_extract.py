"""Tests for binary document extraction."""

from pathlib import Path

import pytest

from open_agent.utils.doc_extract import (
    is_binary_doc,
    read_file_content,
    extract_pdf_text,
    extract_docx_text,
    extract_xlsx_text,
    _truncate,
    MAX_FILE_CONTENT,
)


class TestBinaryDocExts:
    def test_pdf_is_binary(self):
        assert is_binary_doc(Path("test.pdf"))

    def test_docx_is_binary(self):
        assert is_binary_doc(Path("report.docx"))

    def test_xlsx_is_binary(self):
        assert is_binary_doc(Path("data.xlsx"))

    def test_xls_is_binary(self):
        assert is_binary_doc(Path("old.xls"))

    def test_txt_not_binary(self):
        assert not is_binary_doc(Path("readme.txt"))

    def test_py_not_binary(self):
        assert not is_binary_doc(Path("script.py"))


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello") == "hello"

    def test_long_text_truncated(self):
        long_text = "x" * (MAX_FILE_CONTENT + 100)
        result = _truncate(long_text)
        assert len(result) < len(long_text)
        assert "截断" in result

    def test_exact_limit_unchanged(self):
        exact = "x" * MAX_FILE_CONTENT
        assert _truncate(exact) == exact


class TestExtractors:
    """Test extractors — graceful degradation when libs not installed."""

    def test_pdf_missing_file(self):
        result = extract_pdf_text(Path("/nonexistent/file.pdf"))
        assert "失败" in result or "PyMuPDF" in result

    def test_docx_missing_file(self):
        result = extract_docx_text(Path("/nonexistent/file.docx"))
        assert "失败" in result or "python-docx" in result

    def test_xlsx_missing_file(self):
        result = extract_xlsx_text(Path("/nonexistent/file.xlsx"))
        assert "失败" in result or "openpyxl" in result

    def test_read_file_content_text(self, tmp_path):
        text_file = tmp_path / "test.txt"
        text_file.write_text("Hello, World!", encoding="utf-8")
        result = read_file_content(text_file)
        assert result == "Hello, World!"

    def test_read_file_content_pdf_dispatches(self, tmp_path):
        # Even with missing lib, dispatch should work
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"not a real pdf")
        result = read_file_content(pdf_file)
        # Should either extract or return a helpful message
        assert isinstance(result, str)
        assert len(result) > 0

    def test_read_file_content_doc_dispatches(self, tmp_path):
        doc_file = tmp_path / "old.doc"
        doc_file.write_bytes(b"not a real doc")
        result = read_file_content(doc_file)
        assert "暂不支持" in result


class TestReadToolIntegration:
    """Test ReadTool integration with binary document extraction."""

    @pytest.mark.asyncio
    async def test_read_text_file_still_works(self, tmp_path):
        from open_agent.tools.file_tools import ReadTool

        text_file = tmp_path / "test.txt"
        text_file.write_text("line1\nline2\nline3")

        tool = ReadTool(workspace_dir=str(tmp_path))
        result = await tool.execute(path="test.txt")
        assert result.success
        assert "line1" in result.content
        assert "line2" in result.content

    @pytest.mark.asyncio
    async def test_read_pdf_with_offset_limit(self, tmp_path):
        from open_agent.tools.file_tools import ReadTool

        # Create a fake PDF (will return a message, but the offset/limit logic runs)
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"fake pdf content")

        tool = ReadTool(workspace_dir=str(tmp_path))
        result = await tool.execute(path="test.pdf", offset=1, limit=5)
        # Should succeed (returns helpful message as content)
        assert result.success
