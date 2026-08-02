from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pytest
from whydiff.adapters import SQLSafetyError
from whydiff_mcp.server import SecurityPolicy, WhyDiffServer, build_fastmcp


def test_public_tools_are_discoverable_with_typed_schemas() -> None:
    server = WhyDiffServer(
        database=":memory:", policy=SecurityPolicy(allowed_relations=("main.*",))
    )

    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {
        "compare_key_coverage",
        "compare_measures",
        "detect_duplicate_keys",
        "detect_fanout",
        "diagnose_difference",
        "inspect_date_boundaries",
        "inspect_relations",
        "inspect_scd2_alignment",
    }
    compare = next(tool for tool in tools if tool.name == "compare_key_coverage")
    assert compare.inputSchema["required"] == ["left", "right", "keys"]
    schemas = json.dumps(
        {tool.name: tool.inputSchema for tool in tools},
        sort_keys=True,
        separators=(",", ":"),
    )
    assert hashlib.sha256(schemas.encode()).hexdigest() == (
        "d6a31f2fda741386ed707ed9943eeb35cdef47078cdb6a7cc9d536b52ed4a64a"
    )


def test_mcp_transport_lists_and_invokes_every_mvp_tool_without_an_llm(
    tmp_path: Path,
) -> None:
    database = tmp_path / "transport.duckdb"
    connection = duckdb.connect(str(database))
    connection.sql("create table expected(id integer, amount integer)")
    connection.sql("create table actual(id integer, amount integer)")
    connection.sql("insert into expected values (1, 10), (2, 20)")
    connection.sql("insert into actual values (1, 10), (3, 30)")
    connection.sql("create table after_join(id integer, amount integer)")
    connection.sql("insert into after_join values (1, 10), (1, 10), (2, 20)")
    connection.sql("create table left_dates(event_at timestamp)")
    connection.sql("create table right_dates(event_at timestamp)")
    connection.sql("insert into left_dates values ('2026-01-01'), ('2026-01-02')")
    connection.sql("insert into right_dates values ('2026-01-01')")
    connection.sql("create table facts(customer_id integer, event_at timestamp)")
    connection.sql("insert into facts values (1, '2026-01-15')")
    connection.sql(
        "create table dimension(customer_id integer, valid_from timestamp, valid_to timestamp)"
    )
    connection.sql("insert into dimension values (1, '2026-01-01', null)")
    connection.close()
    domain = WhyDiffServer(database=str(database), policy=SecurityPolicy(allowed_relations=("*",)))
    transport = build_fastmcp(domain)

    tools = asyncio.run(transport.list_tools())

    async def invoke_all() -> list[dict[str, Any]]:
        arguments = {
            "inspect_relations": {"relations": ["expected", "actual"]},
            "compare_key_coverage": {
                "left": "expected",
                "right": "actual",
                "keys": ["id"],
            },
            "detect_duplicate_keys": {"relation": "expected", "keys": ["id"]},
            "compare_measures": {
                "left": "expected",
                "right": "actual",
                "keys": ["id"],
                "measures": [{"name": "amount", "expression": "sum(amount)"}],
            },
            "diagnose_difference": {
                "left": "expected",
                "right": "actual",
                "keys": ["id"],
            },
            "detect_fanout": {
                "before": "expected",
                "after": "after_join",
                "keys": ["id"],
                "measures": [{"name": "amount", "expression": "sum(amount)"}],
            },
            "inspect_date_boundaries": {
                "left": "left_dates",
                "right": "right_dates",
                "timestamp_column": "event_at",
            },
            "inspect_scd2_alignment": {
                "fact": "facts",
                "dimension": "dimension",
                "business_keys": ["customer_id"],
                "event_timestamp": "event_at",
                "valid_from": "valid_from",
                "valid_to": "valid_to",
            },
        }
        results: list[dict[str, Any]] = []
        for name, tool_arguments in arguments.items():
            _, structured = await transport.call_tool(name, tool_arguments)
            assert isinstance(structured, dict)
            results.append(structured)
        return results

    results = asyncio.run(invoke_all())

    assert {tool.name for tool in tools} == {
        "compare_key_coverage",
        "compare_measures",
        "detect_duplicate_keys",
        "detect_fanout",
        "diagnose_difference",
        "inspect_date_boundaries",
        "inspect_relations",
        "inspect_scd2_alignment",
    }
    assert len(results) == 8
    assert all(result["trace"]["sanitized"] for result in results)


def test_out_of_scope_relation_is_rejected_before_execution() -> None:
    server = WhyDiffServer(
        database=":memory:", policy=SecurityPolicy(allowed_relations=("analytics.*",))
    )

    with pytest.raises(PermissionError, match="outside the configured scope"):
        asyncio.run(
            server.call_tool(
                "detect_duplicate_keys", {"relation": "private.customers", "keys": ["id"]}
            )
        )


def test_sample_limit_cannot_exceed_policy() -> None:
    server = WhyDiffServer(
        database=":memory:",
        policy=SecurityPolicy(allowed_relations=("main.*",), max_sample_rows=10),
    )

    with pytest.raises(ValueError, match="sample_limit"):
        asyncio.run(
            server.call_tool(
                "inspect_relations", {"relations": ["main.orders"], "sample_limit": 11}
            )
        )


def test_tool_result_has_deterministic_sql_redaction_and_sanitized_trace(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixture.duckdb"
    connection = duckdb.connect(str(database))
    connection.sql("create table expected(id integer, secret varchar)")
    connection.sql("create table actual(id integer, secret varchar)")
    connection.sql("insert into expected values (1, 'safe'), (2, 'hide-me')")
    connection.sql("insert into actual values (1, 'safe')")
    connection.close()
    server = WhyDiffServer(
        database=str(database),
        policy=SecurityPolicy(
            allowed_relations=("*",), redacted_columns=("secret",), max_sample_rows=5
        ),
    )

    result = asyncio.run(
        server.call_tool(
            "compare_key_coverage",
            {"left": "expected", "right": "actual", "keys": ["id"], "sample_limit": 5},
        )
    )

    assert result["generated_sql"].startswith("WITH")
    assert result["evidence"]["left_only_distinct_keys"] == 1
    assert result["trace"]["sanitized"] is True
    assert "fixture.duckdb" not in str(result["trace"])

    inspection = asyncio.run(
        server.call_tool("inspect_relations", {"relations": ["expected"], "sample_limit": 5})
    )
    assert inspection["findings"][0]["evidence"]["columns"]["secret"] == "[REDACTED]"


def test_unsafe_measure_expression_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    connection = duckdb.connect(str(database))
    connection.sql("create table expected(id integer, amount integer)")
    connection.sql("create table actual(id integer, amount integer)")
    connection.close()
    server = WhyDiffServer(database=str(database), policy=SecurityPolicy(allowed_relations=("*",)))

    with pytest.raises(SQLSafetyError, match="rejected"):
        asyncio.run(
            server.call_tool(
                "compare_measures",
                {
                    "left": "expected",
                    "right": "actual",
                    "keys": ["id"],
                    "measures": [
                        {
                            "name": "amount",
                            "expression": ("sum(amount)); delete from expected; select sum(amount"),
                        }
                    ],
                },
            )
        )
