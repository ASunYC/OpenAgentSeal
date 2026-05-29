"""Best-effort parsing for chat file attachments."""

from __future__ import annotations

import base64
import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_CHARS = 30000

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".csv",
    ".tsv",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".css",
    ".scss",
    ".html",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".log",
    ".sql",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".php",
    ".rb",
    ".sh",
    ".ps1",
}


def attachment_to_context(attachment: Any) -> str:
    """Convert a non-image frontend attachment into text context."""
    if not isinstance(attachment, dict):
        return ""

    name = str(attachment.get("name") or "uploaded-file")
    mime_type = str(
        attachment.get("mime_type")
        or attachment.get("mimeType")
        or attachment.get("type")
        or "application/octet-stream"
    )
    if mime_type.startswith("image/"):
        return ""

    data = str(attachment.get("data") or attachment.get("base64") or "")
    if not data:
        return _format_context(name, mime_type, "未收到文件内容。")

    try:
        raw = _decode_base64_data(data)
    except ValueError as exc:
        return _format_context(name, mime_type, f"文件解码失败：{exc}")

    if len(raw) > MAX_FILE_BYTES:
        return _format_context(
            name,
            mime_type,
            f"文件过大，当前限制为 {MAX_FILE_BYTES // 1024 // 1024}MB，未解析。",
        )

    text = parse_file_bytes(name, mime_type, raw)
    return _format_context(name, mime_type, text)


def parse_file_bytes(name: str, mime_type: str, raw: bytes) -> str:
    suffix = Path(name).suffix.lower()
    lowered_mime = mime_type.lower()

    if suffix == ".docx" or lowered_mime.endswith("wordprocessingml.document"):
        return _truncate(_parse_docx(raw))
    if suffix == ".xlsx" or lowered_mime.endswith("spreadsheetml.sheet"):
        return _truncate(_parse_xlsx(raw))
    if suffix == ".pdf" or lowered_mime == "application/pdf":
        return _truncate(_parse_pdf(raw))
    if suffix == ".csv" or lowered_mime in {"text/csv", "application/csv"}:
        return _truncate(_parse_csv(raw))
    if suffix == ".json" or lowered_mime == "application/json":
        return _truncate(_parse_json(raw))
    if lowered_mime.startswith("text/") or suffix in TEXT_EXTENSIONS:
        return _truncate(_decode_text(raw))

    return "暂不支持解析该文件类型。请转换为 txt、md、csv、json、docx、xlsx 或 pdf 后再试。"


def _decode_base64_data(data: str) -> bytes:
    payload = data
    if data.startswith("data:"):
        _, _, payload = data.partition(",")
    try:
        return base64.b64decode(payload, validate=False)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def _format_context(name: str, mime_type: str, text: str) -> str:
    return (
        f"\n\n[上传文件]\n"
        f"文件名：{name}\n"
        f"文件类型：{mime_type}\n"
        f"解析内容：\n{text.strip() or '未提取到可用文本。'}"
    )


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_json(raw: bytes) -> str:
    text = _decode_text(raw)
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return text


def _parse_csv(raw: bytes) -> str:
    text = _decode_text(raw)
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return ""
    return "\n".join(" | ".join(cell.strip() for cell in row) for row in rows[:200])


def _parse_docx(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as docx:
            xml = docx.read("word/document.xml")
    except Exception as exc:
        return f"DOCX 解析失败：{exc}"

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return f"DOCX XML 解析失败：{exc}"

    paragraphs: list[str] = []
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for paragraph in root.findall(".//w:p", ns):
        parts: list[str] = []
        for node in paragraph.iter():
            tag = _strip_namespace(node.tag)
            if tag == "t" and node.text:
                parts.append(node.text)
            elif tag in {"tab", "br"}:
                parts.append("\n" if tag == "br" else "\t")
        line = "".join(parts).strip()
        if line:
            paragraphs.append(line)
    return "\n".join(paragraphs)


def _parse_xlsx(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as workbook:
            shared_strings = _xlsx_shared_strings(workbook)
            sheets = [
                name
                for name in workbook.namelist()
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            ]
            lines: list[str] = []
            for sheet_name in sheets[:5]:
                lines.append(f"# {Path(sheet_name).stem}")
                lines.extend(_xlsx_sheet_lines(workbook.read(sheet_name), shared_strings))
            return "\n".join(lines)
    except Exception as exc:
        return f"XLSX 解析失败：{exc}"


def _xlsx_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    try:
        xml = workbook.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(xml)
    values: list[str] = []
    for item in root:
        texts = [node.text or "" for node in item.iter() if _strip_namespace(node.tag) == "t"]
        values.append("".join(texts))
    return values


def _xlsx_sheet_lines(xml: bytes, shared_strings: list[str]) -> list[str]:
    root = ET.fromstring(xml)
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    lines: list[str] = []
    for row in root.findall(".//x:row", ns)[:200]:
        values: list[str] = []
        for cell in row.findall("x:c", ns):
            value_node = cell.find("x:v", ns)
            if value_node is None or value_node.text is None:
                values.append("")
                continue
            value = value_node.text
            if cell.attrib.get("t") == "s":
                try:
                    value = shared_strings[int(value)]
                except (ValueError, IndexError):
                    pass
            values.append(value)
        if any(values):
            lines.append(" | ".join(values))
    return lines


def _parse_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return "PDF 解析需要安装 pypdf，当前环境暂不支持直接提取 PDF 文本。"

    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = []
        for index, page in enumerate(reader.pages[:50], start=1):
            pages.append(f"# 第 {index} 页\n{page.extract_text() or ''}")
        return "\n\n".join(pages)
    except Exception as exc:
        return f"PDF 解析失败：{exc}"


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _truncate(text: str) -> str:
    if len(text) <= MAX_EXTRACTED_CHARS:
        return text
    return text[:MAX_EXTRACTED_CHARS] + f"\n\n[内容过长，已截取前 {MAX_EXTRACTED_CHARS} 字符]"
