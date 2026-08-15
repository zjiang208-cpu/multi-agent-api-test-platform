from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.models.contracts import OperationContract, OperationParameter, ResponseContract, SourceReference
from app.models.documents import StoredRequirementDocument


HTTP_OPERATION = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(`?/[A-Za-z0-9_./:{}?=&%+\-]+`?)\s*$"
)
HEADING = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$|^\s*((?:\d+\.)+\d*)[.)、]?\s+(.+?)\s*$")
MARKDOWN_TABLE_ROW = re.compile(r"^\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")
HTTP_METHOD_VALUE = re.compile(r"^\s*`?(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b", re.IGNORECASE)
HTTP_PATH_VALUE = re.compile(r"`\s*(/[A-Za-z0-9_./:{}?=&%+\-]+)\s*`|(/[A-Za-z0-9_./:{}?=&%+\-]+)")


@dataclass(frozen=True)
class _OperationMention:
    method: str
    path: str
    start_line: int
    metadata: dict[str, str]


class ApiDiscoveryService:
    """Deterministically indexes API mentions while preserving original text."""

    def discover(self, document: StoredRequirementDocument) -> list[OperationContract]:
        lines = document.content.splitlines()
        mentions = self._operation_mentions(document.content, lines)
        operations: list[OperationContract] = []
        used_ids: set[str] = set()
        heading_lines = self._heading_lines(lines)
        for index, mention in enumerate(mentions):
            method = mention.method
            path = mention.path
            start_line = mention.start_line
            next_start = mentions[index + 1].start_line if index + 1 < len(mentions) else len(lines) + 1
            heading = self._nearest_heading(heading_lines, start_line)
            end_line = max(start_line, next_start - 1)
            if heading is not None:
                next_heading = next((line for line, _ in heading_lines if line > start_line), None)
                if next_heading is not None:
                    end_line = min(end_line, next_heading - 1)
            source_text = "\n".join(lines[start_line - 1 : end_line]).strip()
            operation_id = self._operation_id(method, path, used_ids)
            used_ids.add(operation_id)
            parameters = [
                OperationParameter(name=name, location="path", required=True, type="string")
                for name in re.findall(r"\{([^{}]+)\}", path)
            ]
            operations.append(
                OperationContract(
                    operation_id=operation_id,
                    method=method,
                    path=path,
                    summary=heading[1] if heading else f"{method} {path}",
                    parameters=parameters,
                    responses=[ResponseContract(status_code=200, description="需求文档未明确 HTTP 状态")],
                    source_document_id=document.document_id,
                    source_refs=[
                        SourceReference(
                            source_document_id=document.document_id,
                            section=heading[1] if heading else None,
                            start_line=start_line,
                            end_line=end_line,
                            heading=heading[1] if heading else None,
                            source_text=source_text[:20_000],
                            reference=f"document:{document.document_id}:lines:{start_line}-{end_line}",
                        )
                    ],
                    confidence="confirmed",
                    contract_metadata={
                        "discovery": "requirement_document_parser",
                        **mention.metadata,
                    },
                )
            )
        return operations

    def _operation_mentions(self, content: str, lines: list[str]) -> list[_OperationMention]:
        mentions = [
            _OperationMention(
                method=match.group(1).upper(),
                path=match.group(2).strip("`"),
                start_line=content[: match.start()].count("\n") + 1,
                metadata={"source_format": "method_path_line"},
            )
            for match in HTTP_OPERATION.finditer(content)
        ]
        mentions.extend(self._markdown_table_mentions(lines))
        mentions.sort(key=lambda item: item.start_line)

        unique: list[_OperationMention] = []
        seen: set[tuple[str, str]] = set()
        table_operation_keys = {
            (mention.method, mention.path.split("?", 1)[0])
            for mention in mentions
            if mention.metadata.get("source_format") == "markdown_table"
        }
        for mention in mentions:
            if (
                mention.metadata.get("source_format") == "method_path_line"
                and "?" in mention.path
                and (mention.method, mention.path.split("?", 1)[0]) in table_operation_keys
            ):
                continue
            key = (mention.method, mention.path)
            if key in seen:
                continue
            seen.add(key)
            unique.append(mention)
        return unique

    @classmethod
    def _markdown_table_mentions(cls, lines: list[str]) -> list[_OperationMention]:
        mentions: list[_OperationMention] = []
        fields: dict[str, tuple[str, int]] = {}

        def flush() -> None:
            if not fields:
                return
            method_field = cls._field(fields, {"方法", "请求方法", "method", "httpmethod"})
            path_field = cls._field(fields, {"路径", "接口路径", "请求路径", "path"})
            if method_field is None or path_field is None:
                fields.clear()
                return
            method_match = HTTP_METHOD_VALUE.search(method_field[0])
            path_match = HTTP_PATH_VALUE.search(path_field[0])
            if method_match is None or path_match is None:
                fields.clear()
                return
            metadata = {"source_format": "markdown_table"}
            identifier = cls._field(fields, {"接口编号", "接口id", "operationid", "operation_id"})
            if identifier is not None:
                value = identifier[0].strip().strip("`").strip()
                if value:
                    metadata["document_operation_id"] = value
            mentions.append(
                _OperationMention(
                    method=method_match.group(1).upper(),
                    path=path_match.group(1) or path_match.group(2),
                    start_line=min(line_number for _, line_number in fields.values()),
                    metadata=metadata,
                )
            )
            fields.clear()

        for line_number, line in enumerate(lines, start=1):
            row = MARKDOWN_TABLE_ROW.match(line)
            if row is None:
                flush()
                continue
            key = cls._normalize_table_key(row.group(1))
            if key and not set(key) <= {"-", ":"}:
                fields[key] = (row.group(2).strip(), line_number)
        flush()
        return mentions

    @staticmethod
    def _normalize_table_key(value: str) -> str:
        return re.sub(r"[\s`_*]+", "", value).casefold()

    @classmethod
    def _field(
        cls,
        fields: dict[str, tuple[str, int]],
        aliases: set[str],
    ) -> tuple[str, int] | None:
        normalized_aliases = {cls._normalize_table_key(alias) for alias in aliases}
        return next((value for key, value in fields.items() if key in normalized_aliases), None)

    @staticmethod
    def _heading_lines(lines: list[str]) -> list[tuple[int, str]]:
        values: list[tuple[int, str]] = []
        for line_number, line in enumerate(lines, start=1):
            match = HEADING.match(line)
            if match:
                values.append((line_number, (match.group(2) or match.group(4) or "").strip()))
        return values

    @staticmethod
    def _nearest_heading(headings: list[tuple[int, str]], line_number: int) -> tuple[int, str] | None:
        values = [item for item in headings if item[0] <= line_number]
        return values[-1] if values else None

    @staticmethod
    def _operation_id(method: str, path: str, used: set[str]) -> str:
        value = re.sub(r"[^A-Za-z0-9]+", "-", path.strip("/"))
        value = re.sub(r"-+", "-", value).strip("-").lower() or "root"
        base = f"{method.lower()}-{value}"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate
