from __future__ import annotations

import hashlib
import html.parser
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import yaml

from app.models.documents import DocumentSection, ParsedRequirementDocument


MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
SUPPORTED_FORMATS = {"txt", "md", "markdown", "rst", "html", "htm", "json", "yaml", "yml", "docx", "pdf"}


class DocumentParseError(ValueError):
    pass


class _HtmlTextParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self.skip_depth += 1
        elif tag in {"p", "div", "br", "li", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template"} and self.skip_depth:
            self.skip_depth -= 1
        elif tag in {"p", "div", "li", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def parse_requirement_document(
    *,
    filename: str,
    data: bytes,
    media_type: str | None = None,
) -> ParsedRequirementDocument:
    if not filename.strip():
        raise DocumentParseError("requirement document filename is required")
    if not data:
        raise DocumentParseError("requirement document is empty")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentParseError("requirement document exceeds 10 MB")

    extension = Path(filename).suffix.lower().lstrip(".")
    if extension == "markdown":
        extension = "md"
    if extension == "htm":
        extension = "html"
    if extension not in SUPPORTED_FORMATS:
        raise DocumentParseError(
            "unsupported requirement document format; supported formats: PDF, DOCX, Markdown, TXT, HTML, JSON and YAML"
        )

    warnings: list[str] = []
    detected_kind = _detect_document_kind(extension, data)
    if extension == "pdf":
        text = _parse_pdf(data)
    elif extension == "docx":
        text = _parse_docx(data)
    elif extension == "html":
        text = _parse_html(data)
    elif extension == "json":
        text = _parse_json(data)
    elif extension in {"yaml", "yml"}:
        try:
            text = _parse_yaml(data)
        except DocumentParseError:
            # A requirement document may use YAML-like notation while also
            # containing prose, lists, or legacy contract fragments that are
            # not strict YAML. Keep the source text usable for the Requirement
            # Agent instead of rejecting the whole document at ingestion time.
            text = _decode_text(data)
            warnings.append("YAML 未通过严格语法校验，已保留原文并按文本内容继续解析。")
    else:
        text = _decode_text(data)

    content = _normalize_text(text)
    if not content:
        raise DocumentParseError("requirement document contains no readable text")
    if len(content) > 500_000:
        raise DocumentParseError("parsed requirement document exceeds 500,000 characters")

    sections = _extract_sections(content)
    if detected_kind == "operation_contract":
        warnings.insert(0, "检测到这是 API Operation 契约，不是业务需求文档；可导入接口目录后再运行 Workflow。")
    elif not sections:
        warnings.append("未识别到明确的标题层级，后续 Agent 将按全文理解需求。")
    digest = hashlib.sha256(data).hexdigest()
    return ParsedRequirementDocument(
        document_id=f"reqdoc-{digest[:16]}",
        filename=filename,
        format=extension,  # type: ignore[arg-type]
        detected_kind=detected_kind,  # type: ignore[arg-type]
        media_type=media_type or _media_type_for(extension),
        content=content,
        char_count=len(content),
        line_count=len(content.splitlines()),
        sha256=digest,
        sections=sections,
        warnings=warnings,
    )


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _parse_html(data: bytes) -> str:
    parser = _HtmlTextParser()
    try:
        parser.feed(_decode_text(data))
        parser.close()
    except Exception as exc:
        raise DocumentParseError(f"invalid HTML requirement document: {exc}") from exc
    return "".join(parser.parts)


def _parse_json(data: bytes) -> str:
    try:
        value = json.loads(_decode_text(data))
    except json.JSONDecodeError as exc:
        raise DocumentParseError(f"invalid JSON requirement document: {exc.msg}") from exc
    return json.dumps(value, ensure_ascii=False, indent=2)


def _parse_yaml(data: bytes) -> str:
    try:
        value = yaml.safe_load(_decode_text(data))
    except yaml.YAMLError as exc:
        raise DocumentParseError(f"invalid YAML requirement document: {exc}") from exc
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False)


def _parse_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            xml_data = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml_data)
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise DocumentParseError("invalid DOCX requirement document") from exc

    lines: list[str] = []
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body = root.find(f".//{namespace}body")
    if body is None:
        raise DocumentParseError("DOCX requirement document has no document body")
    for child in list(body):
        if child.tag == f"{namespace}p":
            text = "".join(node.text or "" for node in child.iter(f"{namespace}t")).strip()
            if not text:
                continue
            style = next((node.attrib.get(f"{namespace}val", "") for node in child.iter(f"{namespace}pStyle")), "")
            heading_match = re.search(r"heading(\d)", style, re.IGNORECASE)
            lines.append(f"{'#' * int(heading_match.group(1))} {text}" if heading_match else text)
        elif child.tag == f"{namespace}tbl":
            rows: list[str] = []
            for row in child.findall(f"{namespace}tr"):
                cells = ["".join(node.text or "" for node in cell.iter(f"{namespace}t")).strip() for cell in row.findall(f"{namespace}tc")]
                if any(cells):
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                lines.extend(rows)
    return "\n".join(lines)


def _parse_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentParseError("PDF parsing requires the pypdf package in the pytorch environment") from exc
    try:
        reader = PdfReader(BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise DocumentParseError("invalid or unreadable PDF requirement document") from exc
    return "\n\n".join(pages)


def _normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    # Keep leading indentation: YAML, Markdown lists, code blocks, and
    # structured API contracts depend on it. Only trim trailing whitespace.
    lines = [re.sub(r"[ \t]+$", "", line) for line in value.split("\n")]
    normalized: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if not blank:
                normalized.append("")
            blank = True
        else:
            normalized.append(line.rstrip())
            blank = False
    return "\n".join(normalized).strip()


def _extract_sections(content: str) -> list[DocumentSection]:
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    lines = content.splitlines()
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = heading_pattern.match(line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))
    sections: list[DocumentSection] = []
    for position, (line_index, level, title) in enumerate(headings[:200]):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        section_content = "\n".join(lines[line_index + 1:end]).strip()
        sections.append(
            DocumentSection(
                section_id=f"section-{position + 1}",
                title=title,
                level=level,
                content=section_content[:100_000],
                line_start=line_index + 1,
            )
        )
    return sections


def _detect_document_kind(extension: str, data: bytes) -> str:
    if extension not in {"yaml", "yml"}:
        return "unknown"
    text = _decode_text(data)
    if re.search(r"(?m)^\s*operation\s*:\s*$", text) and re.search(r"(?m)^\s+method\s*:", text) and re.search(r"(?m)^\s+path\s*:", text):
        return "operation_contract"
    return "unknown"


def _media_type_for(extension: str) -> str:
    return {
        "txt": "text/plain",
        "md": "text/markdown",
        "rst": "text/x-rst",
        "html": "text/html",
        "json": "application/json",
        "yaml": "application/yaml",
        "yml": "application/yaml",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
    }.get(extension, "application/octet-stream")
