"""Tests cho VQL validator fail-closed (Task 13 — spec F1/R6).

`run_vql` chỉ chấp nhận VQL **server-side**; validator từ chối mọi thứ không
chứng minh được an toàn: side-effect ở bất kỳ vị trí, plugin client-side, dynamic
dispatch, `LET`, DDL, nhiều statement.
"""
from __future__ import annotations

import pytest

from chatagent.vql_policy import (
    VQL_MAX_BYTES,
    VQL_MAX_QUERY_CHARS,
    VQL_MAX_ROWS,
    VQL_STATEMENT_TIMEOUT_MS,
    VqlPolicyError,
    validate_vql,
)

PREFIX = "[chat_guardrail_vql]"


def _reject(query: str) -> str:
    with pytest.raises(VqlPolicyError) as exc:
        validate_vql(query)
    assert str(exc.value).startswith(PREFIX), str(exc.value)
    return str(exc.value)


def _accept(query: str) -> None:
    assert validate_vql(query) is None


# ── Accepted queries ────────────────────────────────────────────────────────


def test_accepts_select_from_info() -> None:
    _accept("SELECT * FROM info()")


def test_accepts_select_from_clients() -> None:
    _accept("SELECT * FROM clients()")


def test_accepts_select_from_scope() -> None:
    _accept("SELECT * FROM scope()")


def test_accepts_allowlisted_functions() -> None:
    _accept("SELECT count() FROM clients()")
    _accept("SELECT lower(name), upper(name), coalesce(a, b) FROM clients()")
    _accept("SELECT min(x), max(x), sum(x), avg(x), length(x) FROM clients()")
    _accept("SELECT date_trunc(x, 'h'), now(), str(x), int(x), typeof(x) FROM clients()")
    _accept("SELECT if(a, b, c) FROM clients()")
    _accept("SELECT x FROM clients() WHERE name = 'ws-01'")


def test_accepts_plugin_alias() -> None:
    _accept("SELECT a FROM clients() a")


def test_accepts_comment_between_tokens() -> None:
    _accept("SELECT /* */ * FROM info()")
    _accept("SELECT * /* c */ FROM info()")


def test_accepts_simple_with_cte() -> None:
    _accept("WITH x AS (SELECT * FROM info()) SELECT * FROM x")


def test_accepts_string_literal_that_looks_like_call() -> None:
    # Chuỗi không phải lời gọi hàm — nội dung bên trong không được phân tích.
    _accept('SELECT "collect_client()" AS msg FROM info()')


# ── Side-effect functions (everywhere) ──────────────────────────────────────


@pytest.mark.parametrize(
    "fn",
    [
        "collect_client",
        "collect_artifact",
        "artifact_set",
        "file_write",
        "upload",
        "execve",
        "shell",
        "rm",
        "kill_process",
        "quarantine",
        "yara",
        "eval",
    ],
)
def test_rejects_side_effect_function_in_select(fn: str) -> None:
    _reject(f"SELECT {fn}() FROM scope()")


def test_rejects_side_effect_in_where() -> None:
    _reject("SELECT * FROM info() WHERE file_write(x)")


def test_rejects_side_effect_in_subquery() -> None:
    _reject("SELECT * FROM info() WHERE x IN (SELECT collect_client() FROM scope())")


def test_rejects_alias_obfuscated_side_effect() -> None:
    _reject("SELECT collect_client() AS x FROM scope()")


def test_rejects_comment_obfuscated_side_effect() -> None:
    _reject("SELECT /* x */ collect_client() FROM scope()")


def test_rejects_line_comment_obfuscated_side_effect() -> None:
    _reject("SELECT // hidden\ncollect_client() FROM scope()")


def test_rejects_nested_side_effect_in_cte() -> None:
    _reject("WITH x AS (SELECT collect_artifact() FROM scope()) SELECT * FROM x")


# ── Plugins ─────────────────────────────────────────────────────────────────


def test_rejects_client_side_artifact_plugin() -> None:
    _reject("SELECT * FROM pslist()")


def test_rejects_unknown_plugin() -> None:
    _reject("SELECT * FROM secret_plugin()")


def test_rejects_plugin_used_as_function() -> None:
    # `clients()` trong projection không phải FROM → không hợp lệ.
    _reject("SELECT clients() FROM info()")


def test_rejects_unknown_function() -> None:
    _reject("SELECT frobnicate(x) FROM info()")


def test_rejects_dynamic_dispatch() -> None:
    _reject("SELECT eval('1+1') FROM scope()")


# ── Grammar / statements ────────────────────────────────────────────────────


def test_rejects_empty_query() -> None:
    _reject("")
    _reject("   ")


def test_rejects_non_select_start() -> None:
    _reject("UPDATE machines SET status = 'x'")
    _reject("DELETE FROM machines")


def test_rejects_let() -> None:
    _reject("LET x = (SELECT * FROM info())")


def test_rejects_ddl() -> None:
    _reject("SET TRANSACTION READ ONLY")
    _reject("CREATE TABLE t (id int)")
    _reject("DROP TABLE machines")


def test_rejects_multi_statement() -> None:
    _reject("SELECT * FROM info(); SELECT * FROM clients()")


def test_rejects_with_recursive() -> None:
    _reject("WITH RECURSIVE x AS (SELECT * FROM info()) SELECT * FROM x")


def test_accepts_boolean_and_in_predicates() -> None:
    _accept("SELECT * FROM clients() WHERE a = 1 AND (b = 2 OR c = 3)")
    _accept("SELECT * FROM clients() WHERE client_id IN (SELECT client_id FROM flows())")
    _accept("SELECT * FROM clients() WHERE NOT (a = 1)")


def test_rejects_side_effect_inside_in_subquery() -> None:
    _reject("SELECT * FROM clients() WHERE x IN (SELECT collect_client() FROM scope())")


def test_rejects_oversized_query() -> None:
    _reject("SELECT * FROM info()" + " " * (VQL_MAX_QUERY_CHARS + 1))


# ── Obfuscation bypasses ────────────────────────────────────────────────────


def test_rejects_backtick_quoted_side_effect() -> None:
    _reject("SELECT `collect_client`() FROM scope()")


def test_rejects_backtick_quoted_plugin() -> None:
    _reject("SELECT * FROM `pslist`()")


def test_rejects_indirect_call_via_string() -> None:
    _reject('SELECT "collect_client"() FROM scope()')


def test_rejects_uppercase_side_effect() -> None:
    _reject("SELECT COLLECT_CLIENT() FROM SCOPE()")


def test_accepts_backtick_quoted_allowed_plugin() -> None:
    _accept("SELECT * FROM `info`()")


# ── Qualified callables (C3) ────────────────────────────────────────────────


def test_rejects_qualified_allowlisted_plugin() -> None:
    """`Artifact.Custom.clients()` có ident cuối `clients` trong allowlist nhưng định
    danh đầy đủ KHÔNG — phải bị từ chối."""
    _reject("SELECT * FROM Artifact.Custom.clients()")


def test_rejects_qualified_allowlisted_function() -> None:
    _reject("SELECT Ns.count() FROM clients()")


def test_rejects_deep_qualified_side_effect() -> None:
    _reject("SELECT Scope.collect_client() FROM scope()")


def test_rejects_qualified_plugin_in_from() -> None:
    _reject("SELECT * FROM Ns.pslist()")


def test_rejects_method_call_on_string_literal() -> None:
    _reject('SELECT "foo".bar() FROM scope()')


def test_accepts_bare_names_after_c3() -> None:
    """Đảm bảo fix C3 không chặn nhầm gọi trần hợp lệ."""
    _accept("SELECT count() FROM clients()")
    _accept("SELECT lower(name) FROM clients()")
    _accept("SELECT * FROM scope()")


# ── Caps (exported for execution in T15) ────────────────────────────────────


def test_caps_have_spec_values() -> None:
    assert VQL_STATEMENT_TIMEOUT_MS == 5000
    assert VQL_MAX_ROWS == 5000
    assert VQL_MAX_BYTES == 2 * 1024 * 1024
