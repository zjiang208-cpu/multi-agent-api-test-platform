from __future__ import annotations

import sqlite3

import pytest

from app.evidence.providers.database import DatabaseFixtureResolver, DatabaseSchemaEvidenceProvider
from app.evidence.protocol import EvidenceContext, EvidenceQuery
from app.evidence.registry import EvidenceRegistry
from app.models.cases import TestCase as CaseModel
from app.models.contracts import OperationContract
from app.models.projects import ProjectSettings


def test_database_schema_provider_is_read_only_and_allowlisted(tmp_path, monkeypatch):
    database = tmp_path / "schema.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        create table items (id integer primary key, name text not null);
        insert into items (id, name) values (7, 'fixture item');
        insert into items (id, name) values (11, 'second fixture');
        create table private_values (value text);
        """
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("PHASE10_DSN", f"sqlite:///{database.as_posix()}")
    settings = ProjectSettings(
        sut_target={"base_url": "http://127.0.0.1:8081"},
        database={
            "enabled": True,
            "dialect": "sqlite",
            "dsn_ref": "env:PHASE10_DSN",
            "readonly": True,
            "allowed_tables": ["items"],
        },
    )
    context = EvidenceContext(
        project_id="project-1",
        operation=OperationContract(
            operation_id="get-item",
            method="GET",
            path="/items/{id}",
            responses=[{"status_code": 200}],
        ),
        settings=settings,
    )
    provider = DatabaseSchemaEvidenceProvider()
    assert provider.health(context)[0] == "healthy"
    facts = provider.retrieve(context, EvidenceQuery())
    assert len(facts) == 2
    assert facts[0].reference == "schema:items"
    fixture_fact = facts[1]
    assert fixture_fact.reference == "database-fixture:items"
    assert "$DB_FIXTURE[existing:items:id]" in fixture_fact.fact
    assert "$DB_FIXTURE[absent:items:id]" in fixture_fact.fact
    assert "fixture item" not in fixture_fact.fact
    assert all("private_values" not in fact.fact for fact in facts)
    assert all("PHASE10_DSN" not in fact.fact for fact in facts)
    assert all("sqlite:///" not in fact.fact for fact in facts)

    case = CaseModel.model_validate(
        {
            "case_id": "case-db-fixture",
            "requirement_id": "req-1",
            "test_point_ids": ["tp-1"],
            "title": "resolve fixture locally",
            "category": "positive",
            "priority": "high",
            "preconditions": [],
            "steps": ["send request"],
            "expected_behavior": "request is executable",
            "request": {
                "method": "GET",
                "path": "/items/{id}",
                "path_params": {"id": "$DB_FIXTURE[existing:items:id]"},
                "query_params": {"missing": "$DB_FIXTURE[absent:items:id]"},
                "headers": {},
                "body": None,
            },
            "assertions": [
                {
                    "assertion_id": "assert-status",
                    "type": "status_code",
                    "expected": 200,
                    "operator": "eq",
                    "evidence_refs": [fixture_fact.evidence_id],
                }
            ],
            "evidence_refs": [fixture_fact.evidence_id],
            "source": "initial",
            "side_effect": False,
        }
    )
    resolved = DatabaseFixtureResolver().resolve_case(case, settings)
    assert resolved.request.path_params["id"] == 7
    assert resolved.request.query_params["missing"] == 12

    resolver = DatabaseFixtureResolver()
    assert resolver.classify_exact_value(
        settings,
        table_name="items",
        column_name="id",
        value=7,
    ) == "present"
    assert resolver.classify_exact_value(
        settings,
        table_name="items",
        column_name="id",
        value=1,
    ) == "missing"
    exact_case = case.model_copy(
        update={
            "request": case.request.model_copy(
                update={
                    "path_params": {"id": "$DB_FIXTURE[present:items:id:7]"},
                    "query_params": {"missing": "$DB_FIXTURE[missing:items:id:1]"},
                }
            )
        }
    )
    exact_resolved = resolver.resolve_case(exact_case, settings)
    assert exact_resolved.request.path_params["id"] == 7
    assert exact_resolved.request.query_params["missing"] == 1
    stale_exact_case = exact_case.model_copy(
        update={
            "request": exact_case.request.model_copy(
                update={"path_params": {"id": "$DB_FIXTURE[present:items:id:1]"}}
            )
        }
    )
    with pytest.raises(ValueError, match="no longer present"):
        resolver.resolve_case(stale_exact_case, settings)

    bundle = EvidenceRegistry([provider]).collect(
        context,
        EvidenceQuery(include_optional=False),
    )
    assert any(fact.source_type == "database_fixture" for fact in bundle.facts)

    fixed_value_case = case.model_copy(
        update={
            "request": case.request.model_copy(
                update={"path_params": {"id": 0}, "query_params": {}}
            )
        }
    )
    monkeypatch.delenv("PHASE10_DSN")
    unchanged = DatabaseFixtureResolver().resolve_case(fixed_value_case, settings)
    assert unchanged.request.path_params["id"] == 0


def test_database_relation_fixtures_resolve_referenced_unreferenced_and_duplicate_rows(
    tmp_path, monkeypatch
):
    database = tmp_path / "relations.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        create table tb_shop_type (id integer primary key, name text not null);
        create table tb_shop (id integer primary key, type_id integer not null);
        insert into tb_shop_type (id, name) values (1, 'Tea'), (2, 'Tea'), (3, 'Coffee');
        insert into tb_shop (id, type_id) values (10, 1);
        """
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("RELATION_DSN", f"sqlite:///{database.as_posix()}")
    settings = ProjectSettings(
        sut_target={"base_url": "http://127.0.0.1:8081"},
        database={
            "enabled": True,
            "dialect": "sqlite",
            "dsn_ref": "env:RELATION_DSN",
            "readonly": True,
            "allowed_tables": ["tb_shop_type", "tb_shop"],
        },
    )
    context = EvidenceContext(
        project_id="project-relations",
        operation=OperationContract(
            operation_id="delete-shop-type",
            method="DELETE",
            path="/shop-type/{id}",
            responses=[{"status_code": 200}],
        ),
        settings=settings,
    )

    facts = DatabaseSchemaEvidenceProvider().retrieve(context, EvidenceQuery())
    relation_fact = next(
        fact for fact in facts if fact.reference == "database-fixture:tb_shop_type:relations"
    )
    assert "$DB_FIXTURE[duplicate:tb_shop_type:name]" in relation_fact.fact
    assert "$DB_FIXTURE[referenced:tb_shop_type:id:tb_shop:type_id]" in relation_fact.fact
    assert "$DB_FIXTURE[unreferenced:tb_shop_type:id:tb_shop:type_id]" in relation_fact.fact

    case = CaseModel.model_validate(
        {
            "case_id": "case-relations",
            "requirement_id": "req-relations",
            "test_point_ids": ["tp-relations"],
            "title": "resolve relation fixtures locally",
            "category": "negative",
            "priority": "high",
            "steps": ["send request"],
            "expected_behavior": "request is executable",
            "request": {
                "method": "DELETE",
                "path": "/shop-type/{id}",
                "path_params": {
                    "id": "$DB_FIXTURE[referenced:tb_shop_type:id:tb_shop:type_id]"
                },
                "query_params": {},
                "headers": {},
                "body": None,
            },
            "assertions": [
                {
                    "assertion_id": "assert-status",
                    "type": "status_code",
                    "expected": 200,
                    "evidence_refs": [relation_fact.evidence_id],
                }
            ],
            "evidence_refs": [relation_fact.evidence_id],
            "source": "initial",
            "side_effect": True,
            "side_effect_note": "deletion is a side effect",
        }
    )
    resolved = DatabaseFixtureResolver().resolve_case(case, settings)
    assert resolved.request.path_params["id"] == 1

    duplicate_case = case.model_copy(
        update={
            "request": case.request.model_copy(
                update={
                    "method": "POST",
                    "path": "/shop-type",
                    "path_params": {},
                    "body": {"name": "$DB_FIXTURE[duplicate:tb_shop_type:name]"},
                }
            ),
            "side_effect_note": "creation is a side effect",
        }
    )
    duplicate_resolved = DatabaseFixtureResolver().resolve_case(duplicate_case, settings)
    assert duplicate_resolved.request.body["name"] == "Tea"
