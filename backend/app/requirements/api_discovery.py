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
MARKDOWN_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
HTTP_METHOD_VALUE = re.compile(r"^\s*`?(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b", re.IGNORECASE)
HTTP_PATH_VALUE = re.compile(r"`\s*(/[A-Za-z0-9_./:{}?=&%+\-]+)\s*`|(/[A-Za-z0-9_./:{}?=&%+\-]+)")


@dataclass(frozen=True)
class _OperationMention:
    method: str
    path: str
    start_line: int
    metadata: dict[str, str]


@dataclass(frozen=True)
class _ParameterSpec:
    name: str
    schema_type: str
    format: str | None
    required: bool
    description: str | None
    constraints: dict[str, object]


DEFAULT_PARAMETER_SPEC = _ParameterSpec(
    name="",
    schema_type="string",
    format=None,
    required=True,
    description=None,
    constraints={},
)


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
            parameter_specs = self._markdown_parameter_specs(
                lines[start_line - 1 : next_start - 1],
                path,
            )
            parameters = []
            path_parameter_names = {
                name.casefold() for name in re.findall(r"\{([^{}]+)\}", path)
            }
            for name in re.findall(r"\{([^{}]+)\}", path):
                spec = parameter_specs.get(name.casefold(), DEFAULT_PARAMETER_SPEC)
                parameters.append(
                    OperationParameter(
                        name=name,
                        location="path",
                        required=spec.required,
                        type=spec.schema_type,
                        format=spec.format,
                        description=spec.description,
                        constraints=spec.constraints,
                    )
                )
            for normalized_name, spec in parameter_specs.items():
                if normalized_name in path_parameter_names:
                    continue
                parameters.append(
                    OperationParameter(
                        name=spec.name,
                        location="query",
                        required=spec.required,
                        type=spec.schema_type,
                        format=spec.format,
                        description=spec.description,
                        constraints=spec.constraints,
                    )
                )
            contract_metadata = {
                "discovery": "requirement_document_parser",
                **mention.metadata,
            }
            if parameter_specs:
                contract_metadata["parameter_source"] = "markdown_parameter_table"
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
                    contract_metadata=contract_metadata,
                )
            )
        return operations

    @classmethod
    def _markdown_parameter_specs(
        cls,
        lines: list[str],
        path: str,
    ) -> dict[str, _ParameterSpec]:
        specs: dict[str, _ParameterSpec] = {}
        for headers, rows in cls._markdown_table_blocks(lines):
            name_index = cls._header_index(
                headers,
                {"参数", "参数名", "名称", "name", "parameter", "parametername"},
            )
            type_index = cls._header_index(headers, {"类型", "type", "schema", "数据类型"})
            if name_index is None or type_index is None:
                continue
            required_index = cls._header_index(headers, {"必填", "required", "是否必填"})
            constraint_index = cls._header_index(headers, {"约束", "限制", "constraints", "constraint"})
            for row in rows:
                if max(name_index, type_index) >= len(row):
                    continue
                name = cls._clean_table_value(row[name_index])
                normalized_name = name.casefold()
                if not normalized_name:
                    continue
                raw_type = cls._clean_table_value(row[type_index])
                schema_type, schema_format = cls._schema_type(raw_type)
                required_value = (
                    cls._clean_table_value(row[required_index])
                    if required_index is not None and required_index < len(row)
                    else ""
                )
                constraint_text = (
                    cls._clean_table_value(row[constraint_index])
                    if constraint_index is not None and constraint_index < len(row)
                    else ""
                )
                specs[normalized_name] = _ParameterSpec(
                    name=name,
                    schema_type=schema_type,
                    format=schema_format,
                    required=cls._parse_required(required_value, default=True),
                    description=constraint_text or None,
                    constraints=cls._parse_constraints(constraint_text),
                )
        return specs

    @classmethod
    def _markdown_table_blocks(
        cls,
        lines: list[str],
    ) -> list[tuple[list[str], list[list[str]]]]:
        tables: list[tuple[list[str], list[list[str]]]] = []
        index = 0
        while index + 1 < len(lines):
            headers = cls._split_markdown_table_row(lines[index])
            separator = cls._split_markdown_table_row(lines[index + 1])
            if (
                headers is None
                or separator is None
                or len(headers) != len(separator)
                or not all(cls._is_table_separator(value) for value in separator)
            ):
                index += 1
                continue
            rows: list[list[str]] = []
            cursor = index + 2
            while cursor < len(lines):
                row = cls._split_markdown_table_row(lines[cursor])
                if row is None or len(row) != len(headers):
                    break
                rows.append(row)
                cursor += 1
            if rows:
                tables.append((headers, rows))
            index = max(cursor, index + 1)
        return tables

    @staticmethod
    def _split_markdown_table_row(line: str) -> list[str] | None:
        if not MARKDOWN_TABLE_LINE.match(line):
            return None
        value = line.strip()[1:-1]
        return [item.strip() for item in value.split("|")]

    @staticmethod
    def _is_table_separator(value: str) -> bool:
        return re.fullmatch(r":?-{3,}:?", value.replace(" ", "")) is not None

    @classmethod
    def _header_index(cls, headers: list[str], aliases: set[str]) -> int | None:
        normalized_aliases = {cls._normalize_table_key(alias) for alias in aliases}
        for index, header in enumerate(headers):
            if cls._normalize_table_key(header) in normalized_aliases:
                return index
        return None

    @staticmethod
    def _clean_table_value(value: str) -> str:
        return value.strip().strip("`").strip()

    @staticmethod
    def _parse_required(value: str, *, default: bool) -> bool:
        if not value:
            return default
        folded = re.sub(r"\s+", "", value).casefold()
        if folded in {"否", "no", "false", "可选", "非必填", "optional"}:
            return False
        if folded in {"是", "yes", "true", "必填", "必须", "required"}:
            return True
        return default

    @staticmethod
    def _schema_type(value: str) -> tuple[str, str | None]:
        folded = value.casefold()
        if re.search(r"(?<![a-z])long(?![a-z])|长整型|长整数", folded):
            return "integer", "int64"
        if re.search(r"(?<![a-z])(?:integer|int|short)(?![a-z])|整型|整数", folded):
            return "integer", "int32"
        if re.search(r"(?<![a-z])double(?![a-z])", folded):
            return "number", "double"
        if re.search(r"(?<![a-z])float(?![a-z])", folded):
            return "number", "float"
        if re.search(r"(?<![a-z])boolean(?![a-z])|布尔", folded):
            return "boolean", None
        return "string", None

    @staticmethod
    def _parse_constraints(value: str) -> dict[str, object]:
        if not value:
            return {}
        compact = re.sub(r"\s+", "", value)
        number = r"-?\d+(?:\.\d+)?"

        def numeric(raw: str) -> int | float:
            return float(raw) if "." in raw else int(raw)

        constraints: dict[str, object] = {}
        inclusive_minimum = re.search(
            rf"(?:大于等于|不小于|不少于|至少|>=|≥)({number})",
            compact,
            flags=re.IGNORECASE,
        )
        exclusive_minimum = re.search(
            rf"(?:大于|超过|高于|>)({number})",
            compact,
            flags=re.IGNORECASE,
        )
        inclusive_maximum = re.search(
            rf"(?:不大于|不超过|小于等于|<=|≤)({number})",
            compact,
            flags=re.IGNORECASE,
        )
        exclusive_maximum = re.search(
            rf"(?:小于|低于|少于|<)({number})",
            compact,
            flags=re.IGNORECASE,
        )
        if inclusive_minimum:
            constraints["minimum"] = numeric(inclusive_minimum.group(1))
        elif exclusive_minimum:
            constraints["minimum"] = numeric(exclusive_minimum.group(1))
            constraints["exclusiveMinimum"] = True
        if inclusive_maximum:
            constraints["maximum"] = numeric(inclusive_maximum.group(1))
        elif exclusive_maximum:
            constraints["maximum"] = numeric(exclusive_maximum.group(1))
            constraints["exclusiveMaximum"] = True
        return constraints

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
