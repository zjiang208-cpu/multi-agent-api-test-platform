from __future__ import annotations

import re
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select

from app.core.security import is_sensitive_key
from app.evidence.protocol import EvidenceContext, EvidenceQuery
from app.models.cases import TestCase
from app.models.evidence import EvidenceFact
from app.models.projects import ProjectSettings
from app.providers.llm import SecretReferenceError, resolve_secret_reference


_FIXTURE_TOKEN = re.compile(
    r"^\$DB_FIXTURE\[(existing|absent):([A-Za-z0-9_]+):([A-Za-z0-9_]+)\]$"
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
        if not profile.dsn_ref:
            return "error", "database is enabled but no DSN reference is configured"
        if profile.readonly is not True:
            return "error", "database evidence requires a read-only profile"
        if not profile.allowed_tables:
            return "error", "database schema evidence requires an explicit table allowlist"
        try:
            resolve_secret_reference(profile.dsn_ref)
        except SecretReferenceError:
            return "error", "database DSN reference is not configured"
        return "healthy", "read-only schema inspection and local fixture resolution are available"

    def retrieve(self, context: EvidenceContext, _: EvidenceQuery) -> list[EvidenceFact]:
        profile = context.settings.database
        dsn = resolve_secret_reference(profile.dsn_ref)
        engine = create_engine(dsn, pool_pre_ping=True)
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
                            metadata={"table": table_name, "read_only": "true"},
                        )
                    )
            return facts
        finally:
            engine.dispose()

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
        engine = create_engine(
            resolve_secret_reference(settings.database.dsn_ref),
            pool_pre_ping=True,
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
        fixture_kind, table_name, column_name = groups[:3]
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
                exact_value = int(groups[3])
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
        engine = create_engine(
            resolve_secret_reference(profile.dsn_ref),
            pool_pre_ping=True,
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
