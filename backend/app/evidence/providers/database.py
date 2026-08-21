from __future__ import annotations

import re
import os
from typing import Any
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import yaml
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select

from app.core.security import is_sensitive_key
from app.evidence.protocol import EvidenceContext, EvidenceQuery
from app.models.cases import TestCase
from app.models.evidence import EvidenceFact
from app.models.projects import ProjectSettings
from app.providers.llm import SecretReferenceError, resolve_secret_reference


_FIXTURE_TOKEN = re.compile(
    r"^\$DB_FIXTURE\[(existing|absent|referenced|unreferenced|duplicate):"
    r"([A-Za-z0-9_]+):([A-Za-z0-9_]+)"
    r"(?::([A-Za-z0-9_]+):([A-Za-z0-9_]+))?\]$"
)
_EXACT_FIXTURE_TOKEN = re.compile(
    r"^\$DB_FIXTURE\[(present|missing):([A-Za-z0-9_]+):([A-Za-z0-9_]+):(-?\d+)\]$"
)


class DatabaseSchemaEvidenceProvider:
    provider_type = "database_schema"

    def health(self, context: EvidenceContext) -> tuple[str, str]:
        profile = context.settings.database
        if not profile.enabled:
            return "not_configured", "database schema evidence is disabled"
        if not profile.dsn_ref and not context.settings.source_workspace:
            return "error", "database is enabled but no DSN reference is configured"
        if profile.readonly is not True:
            return "error", "database evidence requires a read-only profile"
        if not profile.allowed_tables:
            return "error", "database schema evidence requires an explicit table allowlist"
        try:
            _resolve_database_dsn(profile.dsn_ref, context.settings.source_workspace)
        except SecretReferenceError:
            return "error", "database DSN reference is not configured"
        return "healthy", "read-only schema inspection and local fixture resolution are available"

    def retrieve(self, context: EvidenceContext, _: EvidenceQuery) -> list[EvidenceFact]:
        profile = context.settings.database
        engine = _create_database_engine(
            profile.dsn_ref,
            context.settings.source_workspace,
        )
        try:
            inspector = inspect(engine)
            existing_tables = set(inspector.get_table_names(schema=profile.schema_name))
            facts: list[EvidenceFact] = []
            for table_name in profile.allowed_tables:
                if table_name not in existing_tables:
                    continue
                columns = inspector.get_columns(table_name, schema=profile.schema_name)
                column_summary = ", ".join(
                    f"{column.get('name')}:{column.get('type')}" for column in columns
                )
                facts.append(
                    EvidenceFact(
                        source_type=self.provider_type,
                        reference=f"schema:{table_name}",
                        operation_id=context.operation.operation_id,
                        fact=f"Allowed table {table_name} has columns: {column_summary}.",
                        metadata={"table": table_name, "read_only": "true"},
                    )
                )
                primary_keys = set(
                    (inspector.get_pk_constraint(table_name, schema=profile.schema_name) or {}).get(
                        "constrained_columns"
                    )
                    or []
                )
                fixture_columns = [
                    column
                    for column in columns
                    if not is_sensitive_key(str(column.get("name", "")))
                    and self._is_identifier_column(
                        str(column.get("name", "")), primary_keys
                    )
                ][:8]
                if fixture_columns:
                    tokens: list[str] = []
                    for column in fixture_columns:
                        column_name = str(column["name"])
                        tokens.append(
                            f"existing {column_name}="
                            f"$DB_FIXTURE[existing:{table_name}:{column_name}]"
                        )
                        try:
                            python_type = column["type"].python_type
                        except (AttributeError, NotImplementedError):
                            python_type = None
                        if python_type is int:
                            tokens.append(
                                f"absent {column_name}="
                                f"$DB_FIXTURE[absent:{table_name}:{column_name}]"
                            )
                    facts.append(
                        EvidenceFact(
                            source_type="database_fixture",
                            reference=f"database-fixture:{table_name}",
                            operation_id=context.operation.operation_id,
                            fact=(
                                f"Allowed table {table_name} supports local read-only fixture "
                                "resolution. The model may place an exact token in a request "
                                "parameter; the backend resolves it after model review, so the "
                                f"real value is never sent to the model. Tokens: {'; '.join(tokens)}."
                            ),
                            metadata={
                                "table": table_name,
                                "read_only": "true",
                                "fixture_columns": ",".join(
                                    str(column["name"]) for column in fixture_columns
                                ),
                            },
                        )
                    )
                relation_tokens = self._relation_fixture_tokens(
                    engine,
                    profile.schema_name,
                    table_name,
                    existing_tables,
                    profile.allowed_tables,
                    inspector,
                )
                if relation_tokens:
                    facts.append(
                        EvidenceFact(
                            source_type="database_fixture",
                            reference=f"database-fixture:{table_name}:relations",
                            operation_id=context.operation.operation_id,
                            fact=(
                                f"Allowed table {table_name} supports deterministic relation/duplicate "
                                "fixture resolution. Tokens: " + "; ".join(relation_tokens) + "."
                            ),
                            metadata={
                                "table": table_name,
                                "read_only": "true",
                                "relation_fixture": "true",
                            },
                        )
                    )
            return facts
        finally:
            engine.dispose()

    @staticmethod
    def _relation_fixture_tokens(
        engine,
        schema: str | None,
        table_name: str,
        existing_tables: set[str],
        allowed_tables: list[str],
        inspector,
    ) -> list[str]:
        """Advertise relation and duplicate fixtures using schema conventions only.

        Foreign-key metadata is preferred.  Some local MySQL dumps omit foreign-key
        constraints, so a conservative ``<entity>_id`` to ``tb_<entity>`` inference
        is also supported.  Neither path depends on a concrete business interface.
        """

        metadata = MetaData()
        parent = Table(table_name, metadata, schema=schema, autoload_with=engine)
        tokens: list[str] = []
        with engine.connect() as connection:
            for column in parent.columns:
                column_name = str(column.name)
                if is_sensitive_key(column_name) or DatabaseSchemaEvidenceProvider._is_identifier_column(
                    column_name,
                    set(),
                ):
                    continue
                try:
                    python_type = column.type.python_type
                except (AttributeError, NotImplementedError):
                    python_type = None
                if python_type is not str:
                    continue
                duplicate = connection.execute(
                    select(column)
                    .where(column.is_not(None))
                    .group_by(column)
                    .having(func.count() > 1)
                    .limit(1)
                ).scalar_one_or_none()
                if duplicate is not None:
                    tokens.append(
                        f"duplicate {column_name}="
                        f"$DB_FIXTURE[duplicate:{table_name}:{column_name}]"
                    )

            relation_pairs: set[tuple[str, str, str]] = set()
            for child_table_name in sorted(set(allowed_tables) & existing_tables):
                child = Table(
                    child_table_name,
                    MetaData(),
                    schema=schema,
                    autoload_with=engine,
                )
                for foreign_key in inspector.get_foreign_keys(
                    child_table_name,
                    schema=schema,
                ):
                    if foreign_key.get("referred_table") != table_name:
                        continue
                    local_columns = foreign_key.get("constrained_columns") or []
                    remote_columns = foreign_key.get("referred_columns") or []
                    if len(local_columns) == len(remote_columns) == 1:
                        relation_pairs.add(
                            (child_table_name, str(local_columns[0]), str(remote_columns[0]))
                        )
                for child_column in child.columns:
                    inferred = DatabaseSchemaEvidenceProvider._infer_relation_column(
                        child_table_name,
                        str(child_column.name),
                        table_name,
                        set(parent.columns.keys()),
                    )
                    if inferred is not None:
                        relation_pairs.add((child_table_name, str(child_column.name), inferred))

            for child_table_name, child_column_name, parent_column_name in sorted(relation_pairs):
                if is_sensitive_key(child_column_name) or is_sensitive_key(parent_column_name):
                    continue
                if child_table_name not in existing_tables or child_table_name not in allowed_tables:
                    continue
                if parent_column_name not in parent.columns:
                    continue
                child = Table(
                    child_table_name,
                    MetaData(),
                    schema=schema,
                    autoload_with=engine,
                )
                if child_column_name not in child.columns:
                    continue
                parent_column = parent.columns[parent_column_name]
                child_column = child.columns[child_column_name]
                references = select(child_column).where(child_column.is_not(None))
                referenced_count = connection.execute(
                    select(func.count()).select_from(parent).where(
                        parent_column.is_not(None),
                        parent_column.in_(references),
                    )
                ).scalar_one()
                if referenced_count:
                    tokens.append(
                        f"referenced {parent_column_name}="
                        f"$DB_FIXTURE[referenced:{table_name}:{parent_column_name}:"
                        f"{child_table_name}:{child_column_name}]"
                    )
                unreferenced_count = connection.execute(
                    select(func.count()).select_from(parent).where(
                        parent_column.is_not(None),
                        ~parent_column.in_(references),
                    )
                ).scalar_one()
                if unreferenced_count:
                    tokens.append(
                        f"unreferenced {parent_column_name}="
                        f"$DB_FIXTURE[unreferenced:{table_name}:{parent_column_name}:"
                        f"{child_table_name}:{child_column_name}]"
                    )
        return tokens

    @staticmethod
    def _infer_relation_column(
        child_table_name: str,
        child_column_name: str,
        parent_table_name: str,
        parent_columns: set[str],
    ) -> str | None:
        """Infer a conventional relation when a dump omitted FK metadata."""

        if not child_column_name.casefold().endswith("_id"):
            return None
        if "id" in parent_columns and child_column_name.casefold() == "id":
            return None
        prefix = child_column_name[:-3].casefold()
        parent_stem = parent_table_name.casefold()
        if parent_stem.startswith("tb_"):
            parent_stem = parent_stem[3:]
        segments = set(parent_stem.split("_"))
        if prefix not in segments and prefix != parent_stem:
            return None
        return "id" if "id" in parent_columns else None

    @staticmethod
    def _is_identifier_column(column_name: str, primary_keys: set[str]) -> bool:
        normalized = column_name.casefold()
        return (
            column_name in primary_keys
            or normalized == "id"
            or normalized.endswith("_id")
            or normalized.endswith("_uuid")
            or normalized.endswith("_code")
        )


class DatabaseFixtureResolver:
    """Resolve model-selected fixture tokens locally without disclosing row values to the LLM."""

    def bind_case_fixtures(
        self,
        case: TestCase,
        *,
        operation,
        points,
        evidence,
    ) -> TestCase:
        """Bind ordinary model values to advertised fixtures before execution.

        The Designer is allowed to return a concrete value such as ``1`` even
        when the evidence advertised an existing-row token.  That value is not
        stable across environments.  This pass turns only semantically obvious
        identifiers and duplicate/relation values into local tokens.  It never
        invents a table name and never changes explicit boundary values such as
        zero, negative numbers, or exact present/missing tokens.
        """

        candidates = self._fixture_candidates(evidence)
        if not candidates:
            return case
        points_by_id = {point.point_id: point for point in points}
        linked_points = [
            points_by_id[point_id]
            for point_id in case.test_point_ids
            if point_id in points_by_id
        ]
        semantic_text = "\n".join(
            [
                case.title,
                case.expected_behavior,
                *case.preconditions,
                *case.steps,
                *(item.title for item in linked_points),
                *(item.action for item in linked_points),
                *(item.expected_result for item in linked_points),
            ]
        ).casefold()
        kind = self._semantic_fixture_kind(semantic_text)
        request = case.request
        path_params = dict(request.path_params)
        query_params = dict(request.query_params)
        body = request.body
        changed = False
        parameter_names = {
            (parameter.location, parameter.name): parameter
            for parameter in operation.parameters
        }

        for location, values in (("path", path_params), ("query", query_params)):
            for name, value in list(values.items()):
                parameter = parameter_names.get((location, name))
                if parameter is None:
                    continue
                replacement = self._fixture_for_value(
                    name,
                    value,
                    kind,
                    candidates,
                    operation.path,
                    location,
                )
                if replacement is not None and replacement != value:
                    values[name] = replacement
                    changed = True

        body, body_changed = self._bind_body_fixture(
            body,
            kind,
            candidates,
            operation.path,
        )
        changed = changed or body_changed
        if not changed:
            return case
        return case.model_copy(
            update={
                "request": request.model_copy(
                    update={
                        "path_params": path_params,
                        "query_params": query_params,
                        "body": body,
                    }
                )
            }
        )

    @staticmethod
    def _fixture_candidates(evidence) -> list[tuple[str, str, str, str | None, str | None]]:
        candidates: list[tuple[str, str, str, str | None, str | None]] = []
        if evidence is None:
            return candidates
        for fact in evidence.facts:
            if fact.source_type != "database_fixture":
                continue
            for token in re.findall(r"\$DB_FIXTURE\[[^\]\r\n]+\]", fact.fact):
                match = DatabaseFixtureResolver._match_token(token)
                if not match:
                    continue
                groups = match.groups()
                if len(groups) == 4:
                    kind, table, column, exact = groups
                    related_table = related_column = None
                else:
                    kind, table, column, related_table, related_column = groups
                    exact = None
                candidates.append((kind, table, column, related_table, related_column))
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _semantic_fixture_kind(text: str) -> str:
        if any(
            marker in text
            for marker in (
                "不存在",
                "未找到",
                "not found",
                "not exist",
                "nonexistent",
                "missing",
            )
        ):
            return "absent"
        if any(marker in text for marker in ("重复", "duplicate")):
            return "duplicate"
        if any(marker in text for marker in ("未被引用", "unreferenced")):
            return "unreferenced"
        if any(marker in text for marker in ("被引用", "referenced")):
            return "referenced"
        return "existing"

    def _fixture_for_value(
        self,
        name: str,
        value: Any,
        kind: str,
        candidates: list[tuple[str, str, str, str | None, str | None]],
        operation_path: str,
        location: str,
    ) -> str | None:
        if self._match_token(value) or not self._is_stable_identifier_value(value, kind):
            return None
        matching = [
            item
            for item in candidates
            if item[0] == kind and item[2].casefold() == name.casefold()
        ]
        if not matching and name.casefold() == "id":
            matching = [item for item in candidates if item[0] == kind and item[2].casefold() == "id"]
        selected = self._select_table_candidate(matching, operation_path)
        if selected is None:
            return None
        fixture_kind, table, column, related_table, related_column = selected
        suffix = (
            f":{related_table}:{related_column}"
            if related_table and related_column
            else ""
        )
        return f"$DB_FIXTURE[{fixture_kind}:{table}:{column}{suffix}]"

    def _bind_body_fixture(
        self,
        body: Any,
        kind: str,
        candidates: list[tuple[str, str, str, str | None, str | None]],
        operation_path: str,
    ) -> tuple[Any, bool]:
        if not isinstance(body, dict):
            return body, False
        changed = False
        result = dict(body)
        for name, value in body.items():
            matching = [
                item
                for item in candidates
                if item[0] == kind and item[2].casefold() == str(name).casefold()
            ]
            selected = self._select_table_candidate(matching, operation_path)
            if selected is None:
                continue
            if kind == "duplicate" and isinstance(value, str):
                replacement = self._candidate_token(selected)
            elif kind in {"existing", "absent", "referenced", "unreferenced"} and self._is_stable_identifier_value(
                value,
                kind,
            ):
                replacement = self._candidate_token(selected)
            else:
                continue
            if replacement != value:
                result[name] = replacement
                changed = True
        return result, changed

    @staticmethod
    def _candidate_token(candidate) -> str:
        kind, table, column, related_table, related_column = candidate
        suffix = (
            f":{related_table}:{related_column}"
            if related_table and related_column
            else ""
        )
        return f"$DB_FIXTURE[{kind}:{table}:{column}{suffix}]"

    @staticmethod
    def _select_table_candidate(candidates, operation_path: str):
        if not candidates:
            return None
        path_words = {
            word.casefold()
            for word in re.split(r"[^A-Za-z0-9]+", operation_path)
            if word and word.casefold() not in {"id", "api"}
        }
        ranked = sorted(
            candidates,
            key=lambda item: (
                max(
                    (
                        1
                        for word in path_words
                        if word in item[1].casefold().split("_")
                        or word in item[1].casefold().removeprefix("tb_").split("_")
                    ),
                    default=0,
                ),
                item[1],
            ),
            reverse=True,
        )
        return ranked[0]

    @staticmethod
    def _is_stable_identifier_value(value: Any, kind: str) -> bool:
        if isinstance(value, bool):
            return False
        if kind == "duplicate":
            return isinstance(value, str) and bool(value.strip())
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return False
        return numeric > 0

    def resolve_case(self, case: TestCase, settings: ProjectSettings) -> TestCase:
        payload = case.model_dump(mode="python")
        request = payload["request"]
        has_fixture_token = any(
            self._contains_fixture_token(request[field])
            for field in ("path_params", "query_params", "headers", "body")
        )
        if not has_fixture_token:
            return case
        if not settings.database.enabled:
            raise ValueError("database fixture was requested but database evidence is disabled")
        engine = _create_database_engine(
            settings.database.dsn_ref,
            settings.source_workspace,
        )
        cache: dict[str, Any] = {}
        try:
            request["path_params"] = self._resolve_value(
                request["path_params"], settings, engine, cache
            )
            request["query_params"] = self._resolve_value(
                request["query_params"], settings, engine, cache
            )
            request["body"] = self._resolve_value(
                request["body"], settings, engine, cache
            )
            request["headers"] = {
                key: str(self._resolve_value(value, settings, engine, cache))
                for key, value in request["headers"].items()
            }
            return TestCase.model_validate(payload)
        finally:
            engine.dispose()

    @staticmethod
    def _contains_fixture_token(value: Any) -> bool:
        if isinstance(value, str):
            return DatabaseFixtureResolver._match_token(value) is not None
        if isinstance(value, dict):
            return any(
                DatabaseFixtureResolver._contains_fixture_token(item)
                for item in value.values()
            )
        if isinstance(value, (list, tuple)):
            return any(
                DatabaseFixtureResolver._contains_fixture_token(item)
                for item in value
            )
        return False

    def _resolve_value(self, value: Any, settings, engine, cache: dict[str, Any]) -> Any:
        if isinstance(value, str):
            match = self._match_token(value)
            if not match:
                return value
            if value not in cache:
                cache[value] = self._resolve_token(match, settings, engine)
            return cache[value]
        if isinstance(value, dict):
            return {
                key: self._resolve_value(item, settings, engine, cache)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._resolve_value(item, settings, engine, cache) for item in value]
        return value

    @staticmethod
    def _resolve_token(match, settings, engine) -> Any:
        groups = match.groups()
        if len(groups) == 4:
            fixture_kind, table_name, column_name, exact_value = groups
            related_table = related_column = None
        else:
            fixture_kind, table_name, column_name, related_table, related_column = groups
            exact_value = None
        profile = settings.database
        if table_name not in profile.allowed_tables:
            raise ValueError(f"database fixture table is not allowlisted: {table_name}")
        if is_sensitive_key(column_name):
            raise ValueError(f"database fixture column is sensitive: {column_name}")
        table = Table(
            table_name,
            MetaData(),
            schema=profile.schema_name,
            autoload_with=engine,
        )
        if column_name not in table.columns:
            raise ValueError(f"database fixture column does not exist: {table_name}.{column_name}")
        column = table.columns[column_name]
        with engine.connect() as connection:
            if fixture_kind in {"present", "missing"}:
                exact_value = int(exact_value)
                try:
                    python_type = column.type.python_type
                except (AttributeError, NotImplementedError):
                    python_type = None
                if python_type is not int:
                    raise ValueError(
                        "exact database fixture requires an integer column: "
                        f"{table_name}.{column_name}"
                    )
                found = connection.execute(
                    select(column).where(column == exact_value).limit(1)
                ).scalar_one_or_none()
                exists = found is not None
                if fixture_kind == "present" and not exists:
                    raise ValueError(
                        f"exact database fixture is no longer present: "
                        f"{table_name}.{column_name}={exact_value}"
                    )
                if fixture_kind == "missing" and exists:
                    raise ValueError(
                        f"exact database fixture is no longer missing: "
                        f"{table_name}.{column_name}={exact_value}"
                    )
                return exact_value
            if fixture_kind == "existing":
                value = connection.execute(
                    select(column)
                    .where(column.is_not(None))
                    .order_by(column)
                    .limit(1)
                ).scalar_one_or_none()
                if value is None:
                    raise ValueError(f"no existing database fixture: {table_name}.{column_name}")
                return value
            if fixture_kind == "duplicate":
                value = connection.execute(
                    select(column)
                    .where(column.is_not(None))
                    .group_by(column)
                    .having(func.count() > 1)
                    .order_by(column)
                    .limit(1)
                ).scalar_one_or_none()
                if value is None:
                    raise ValueError(
                        f"no duplicate database fixture: {table_name}.{column_name}"
                    )
                return value
            if fixture_kind in {"referenced", "unreferenced"}:
                if not related_table or not related_column:
                    raise ValueError(
                        f"{fixture_kind} database fixture requires a related table and column"
                    )
                if related_table not in profile.allowed_tables:
                    raise ValueError(
                        f"database fixture related table is not allowlisted: {related_table}"
                    )
                related = Table(
                    related_table,
                    MetaData(),
                    schema=profile.schema_name,
                    autoload_with=engine,
                )
                if related_column not in related.columns:
                    raise ValueError(
                        f"database fixture related column does not exist: "
                        f"{related_table}.{related_column}"
                    )
                related_column_obj = related.columns[related_column]
                matching_values = select(related_column_obj).where(
                    related_column_obj.is_not(None)
                )
                if fixture_kind == "referenced":
                    predicate = column.in_(matching_values)
                else:
                    predicate = ~column.in_(matching_values)
                value = connection.execute(
                    select(column).where(column.is_not(None), predicate).order_by(column).limit(1)
                ).scalar_one_or_none()
                if value is None:
                    raise ValueError(
                        f"no {fixture_kind} database fixture: "
                        f"{table_name}.{column_name} via {related_table}.{related_column}"
                    )
                return value
            try:
                python_type = column.type.python_type
            except (AttributeError, NotImplementedError):
                python_type = None
            if python_type is not int:
                raise ValueError(
                    f"absent database fixture requires an integer column: {table_name}.{column_name}"
                )
            maximum = connection.execute(select(func.max(column))).scalar_one_or_none()
            return 1 if maximum is None else int(maximum) + 1

    @staticmethod
    def _match_token(value: str):
        if not isinstance(value, str):
            return None
        return _FIXTURE_TOKEN.fullmatch(value) or _EXACT_FIXTURE_TOKEN.fullmatch(value)

    def classify_exact_value(
        self,
        settings: ProjectSettings,
        *,
        table_name: str,
        column_name: str,
        value: int,
    ) -> str:
        """Return ``present`` or ``missing`` using an allowlisted read-only query."""

        profile = settings.database
        if not profile.enabled:
            raise ValueError("database evidence is disabled")
        if table_name not in profile.allowed_tables:
            raise ValueError(f"database fixture table is not allowlisted: {table_name}")
        if is_sensitive_key(column_name):
            raise ValueError(f"database fixture column is sensitive: {column_name}")
        engine = _create_database_engine(
            profile.dsn_ref,
            settings.source_workspace,
        )
        try:
            table = Table(
                table_name,
                MetaData(),
                schema=profile.schema_name,
                autoload_with=engine,
            )
            if column_name not in table.columns:
                raise ValueError(
                    f"database fixture column does not exist: {table_name}.{column_name}"
                )
            column = table.columns[column_name]
            try:
                python_type = column.type.python_type
            except (AttributeError, NotImplementedError):
                python_type = None
            if python_type is not int:
                raise ValueError(
                    f"exact database fixture requires an integer column: "
                    f"{table_name}.{column_name}"
                )
            with engine.connect() as connection:
                found = connection.execute(
                    select(column).where(column == value).limit(1)
                ).scalar_one_or_none()
            return "present" if found is not None else "missing"
        finally:
            engine.dispose()


def _create_database_engine(dsn_ref: str | None, source_workspace: str | None = None):
    """Create a read-only evidence engine with a portable MySQL driver URL.

    SQLAlchemy's ``mysql://`` alias defaults to the optional mysqlclient
    package. The platform ships PyMySQL instead, so normalize that alias at
    the boundary without exposing or rewriting the configured secret value.
    """

    dsn = _resolve_database_dsn(dsn_ref, source_workspace)
    if dsn.startswith("mysql://"):
        dsn = "mysql+pymysql://" + dsn[len("mysql://") :]
    return create_engine(dsn, pool_pre_ping=True)


def _resolve_database_dsn(
    dsn_ref: str | None,
    source_workspace: str | None,
) -> str:
    """Resolve the configured DSN, with a safe Spring datasource fallback.

    The platform process is separate from the IntelliJ-launched SUT process.  A
    DSN configured only in the SUT's ``application.yml`` therefore used to be
    invisible to fixture retrieval.  We may reuse that configuration only when
    credentials are environment references; inline passwords are deliberately
    ignored and still require an explicit platform ``dsn_ref``.
    """

    configured_error: SecretReferenceError | None = None
    if dsn_ref:
        try:
            return resolve_secret_reference(dsn_ref)
        except SecretReferenceError as exc:
            configured_error = exc
    discovered = _discover_spring_database_dsn(source_workspace)
    if discovered:
        return discovered
    if configured_error is not None:
        raise configured_error
    raise SecretReferenceError("database DSN reference is not configured")


def _discover_spring_database_dsn(source_workspace: str | None) -> str | None:
    if not source_workspace:
        return None
    root = Path(source_workspace).expanduser()
    candidates = [
        root / "src" / "main" / "resources" / "application.yml",
        root / "src" / "main" / "resources" / "application.yaml",
        root / "src" / "main" / "resources" / "application.properties",
        root / "application.yml",
        root / "application.yaml",
        root / "application.properties",
    ]
    for candidate in candidates:
        if not candidate.is_file() or candidate.stat().st_size > 1_000_000:
            continue
        try:
            raw = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        config = _extract_spring_datasource(raw, candidate.suffix.casefold())
        if not config:
            continue
        url = _resolve_config_placeholders(config.get("url"))
        username = _resolve_config_secret(config.get("username"))
        password = _resolve_config_secret(config.get("password"))
        if not url or username is None or password is None:
            continue
        return _build_database_url(url, username, password)
    return None


def _extract_spring_datasource(content: str, suffix: str) -> dict[str, str]:
    if suffix == ".properties":
        result: dict[str, str] = {}
        for line in content.splitlines():
            match = re.match(
                r"\s*(?:spring\.datasource\.)?(url|username|password)\s*[:=]\s*(.*?)\s*$",
                line,
                re.IGNORECASE,
            )
            if match and not line.lstrip().startswith("#"):
                result[match.group(1).casefold()] = match.group(2).strip()
        return result
    try:
        value = yaml.safe_load(content)
    except yaml.YAMLError:
        return {}
    if not isinstance(value, dict):
        return {}
    spring = value.get("spring")
    if not isinstance(spring, dict):
        return {}
    datasource = spring.get("datasource")
    if not isinstance(datasource, dict):
        return {}
    return {
        str(key).casefold(): str(item).strip()
        for key, item in datasource.items()
        if str(key).casefold() in {"url", "username", "password"}
        and item is not None
    }


def _resolve_config_placeholders(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().strip("'\"")

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        resolved = os.getenv(name)
        if not resolved:
            raise SecretReferenceError("database source configuration is incomplete")
        return resolved

    try:
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, value)
    except SecretReferenceError:
        return None


def _resolve_config_secret(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().strip("'\"")
    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value)
    if match:
        try:
            return resolve_secret_reference(f"env:{match.group(1)}")
        except SecretReferenceError:
            return None
    if value.startswith("env:"):
        try:
            return resolve_secret_reference(value)
        except SecretReferenceError:
            return None
    return None


def _build_database_url(url: str, username: str, password: str) -> str | None:
    normalized = url[5:] if url.startswith("jdbc:") else url
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"mysql", "mysql+pymysql"} or not parsed.hostname:
        return None
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunsplit(("mysql+pymysql", netloc, parsed.path, parsed.query, parsed.fragment))
