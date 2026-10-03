"""Test completeness-preserving SearchClients adapter (Task 7, spec V3-5/V5/V6).

``search_clients_exact`` phải đi qua TẤT CẢ các trang SearchClients rồi lọc exact
hostname (đã chuẩn hoá cả hai phía), fail-closed khi dữ liệu không đầy đủ.

Mock ở boundary HTTP (``httpx.MockTransport``) — không cần Velociraptor thật.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest

from app.core.config import settings
from app.services.velociraptor import (
    SEARCH_CLIENTS_MAX_PAGES,
    VelociraptorClient,
    VelociraptorError,
)


def _client_item(client_id: str, hostname: str) -> dict[str, Any]:
    return {
        "client_id": client_id,
        "os_info": {"hostname": hostname, "system": "windows"},
        "last_seen_at": "2026-08-01T10:00:00Z",
    }


def _build_transport(handler):
    """httpx.MockTransport với handler đồng bộ (req) -> Response."""

    async def _h(req: httpx.Request) -> httpx.Response:
        return handler(req)

    return httpx.MockTransport(_h)


def _make_client(handler) -> VelociraptorClient:
    return VelociraptorClient(
        "https://veloci.test",
        username="admin",
        password="tok",
        transport=_build_transport(handler),
    )


def _paged_handler(pages: dict[int, dict], seen_offsets: list[int] | None = None):
    """handler trả body theo tham số ``offset`` của request."""

    def handler(req: httpx.Request) -> httpx.Response:
        offset = int(req.url.params.get("offset", "0"))
        if seen_offsets is not None:
            seen_offsets.append(offset)
        body = pages.get(offset)
        if body is None:
            return httpx.Response(200, json={"items": [], "total": 0})
        return httpx.Response(200, json=body)

    return handler


def _search(handler, hostname: str):
    client = _make_client(handler)

    async def run():
        async with client as c:
            return await c.search_clients_exact(hostname)

    return asyncio.run(run())


def test_search_clients_exact_finds_match_across_pages() -> None:
    pages = {
        0: {
            "items": [
                _client_item("C.aaa111", "OTHER-PC"),
                _client_item("C.bbb222", "OTHER-PC2"),
            ],
            "total": 3,
        },
        2: {"items": [_client_item("C.ccc333", "DESKTOP-ABC")], "total": 3},
    }
    offsets: list[int] = []
    handler = _paged_handler(pages, offsets)

    assert _search(handler, "DESKTOP-ABC") == ["C.ccc333"]
    # Đi qua cả 2 trang: offset 0 rồi 2 (không dừng ở trang đầu).
    assert offsets == [0, 2]


def test_search_clients_exact_ambiguous_returns_error() -> None:
    pages = {
        0: {
            "items": [
                _client_item("C.aaa111", "DESKTOP-ABC"),
                _client_item("C.bbb222", "desktop-abc.local"),
            ],
            "total": 2,
        }
    }
    handler = _paged_handler(pages)

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    message = str(ei.value)
    # Danh sách client_id phân biệt phải có trong message.
    assert "C.aaa111" in message
    assert "C.bbb222" in message
    assert ei.value.category == "chat_collection_denied"


def test_search_clients_exact_no_match_raises(monkeypatch) -> None:
    # Cửa sổ retry = 0 để test không chờ 5s; fail closed ngay khi không thấy client.
    monkeypatch.setattr(settings, "resolver_consistency_window_seconds", 0)
    pages = {0: {"items": [_client_item("C.xxx999", "SOME-OTHER")], "total": 1}}
    handler = _paged_handler(pages)

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert ei.value.category == "chat_collection_denied"


def test_search_clients_exact_unknown_total_raises() -> None:
    # Response thiếu `total` → không xác định được completeness → fail closed.
    pages = {0: {"items": [_client_item("C.aaa111", "DESKTOP-ABC")]}}
    handler = _paged_handler(pages)

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert "total" in str(ei.value)
    assert ei.value.category == "chat_collection_denied"


def test_search_clients_exact_premature_empty_page_raises() -> None:
    # Trang rỗng nhưng total nói còn dữ liệu → dữ liệu không nhất quán → fail closed.
    pages = {0: {"items": [], "total": 5}}
    handler = _paged_handler(pages)

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert "trang rỗng sớm" in str(ei.value)
    assert ei.value.category == "chat_collection_denied"


def test_search_clients_exact_normalizes_hostname() -> None:
    # Khác hoa/thường + khoảng trắng + FQDN nhưng vẫn là cùng 1 host.
    pages = {0: {"items": [_client_item("C.aaa111", "  desktop-abc.LOCAL  ")], "total": 1}}
    handler = _paged_handler(pages)

    assert _search(handler, "DESKTOP-ABC") == ["C.aaa111"]


def test_search_clients_exact_duplicate_client_across_pages_not_ambiguous() -> None:
    # Cùng client_id xuất hiện ở 2 trang → dedup, KHÔNG phải ambiguity.
    pages = {
        0: {"items": [_client_item("C.same01", "DESKTOP-ABC")], "total": 2},
        1: {"items": [_client_item("C.same01", "DESKTOP-ABC")], "total": 2},
    }
    handler = _paged_handler(pages)

    assert _search(handler, "DESKTOP-ABC") == ["C.same01"]


def test_search_clients_exact_max_pages_guard() -> None:
    # Mỗi trang trả 1 client khác nhau, total vô cùng lớn → phải dừng ở MAX_SEARCH_PAGES.
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        offset = int(req.url.params.get("offset", "0"))
        return httpx.Response(
            200,
            json={"items": [_client_item(f"C.{offset:06d}", "OTHER")], "total": 10**9},
        )

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert str(SEARCH_CLIENTS_MAX_PAGES) in str(ei.value)
    assert ei.value.category == "chat_collection_denied"
    # Cap được kiểm tra TRƯỚC khi gửi request → đúng MAX_PAGES request, không hơn.
    assert calls["n"] == SEARCH_CLIENTS_MAX_PAGES


def test_search_clients_exact_retries_for_newly_enrolled_client(monkeypatch) -> None:
    # Client mới enroll chưa visible ở lần gọi đầu → retry bounded trong cửa sổ → thấy.
    monkeypatch.setattr(settings, "resolver_consistency_window_seconds", 2)
    monkeypatch.setattr(
        "app.services.velociraptor.SEARCH_CLIENTS_RETRY_INTERVAL_SECONDS", 0.01
    )
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"items": [], "total": 0})
        return httpx.Response(
            200, json={"items": [_client_item("C.new01", "DESKTOP-ABC")], "total": 1}
        )

    assert _search(handler, "DESKTOP-ABC") == ["C.new01"]
    assert calls["n"] >= 2


def test_search_clients_exact_total_changes_between_pages_raises() -> None:
    # total đổi giữa các trang → phân trang không đáng tin → fail closed.
    def handler(req: httpx.Request) -> httpx.Response:
        offset = int(req.url.params.get("offset", "0"))
        total = 2 if offset == 0 else 99
        return httpx.Response(
            200,
            json={"items": [_client_item("C.aaa111", "OTHER")], "total": total},
        )

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert "total" in str(ei.value)
    assert ei.value.category == "chat_collection_denied"


# ── Finding C1: item hỏng không được bỏ qua âm thầm ────────────────


def test_search_clients_exact_malformed_entry_raises() -> None:
    # `items=[valid_match, null], total=2` — item hỏng vẫn tính vào completeness
    # nên KHÔNG được trả về client hợp lệ.
    pages = {
        0: {"items": [_client_item("C.aaa111", "DESKTOP-ABC"), None], "total": 2}
    }
    handler = _paged_handler(pages)

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert "không hợp lệ" in str(ei.value)
    assert ei.value.category == "chat_collection_denied"


# ── Finding C2: total/đếm không hợp lệ không được authorize resolve ────


def test_search_clients_exact_negative_total_raises() -> None:
    pages = {0: {"items": [_client_item("C.aaa111", "DESKTOP-ABC")], "total": -1}}
    handler = _paged_handler(pages)

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert "âm" in str(ei.value)
    assert ei.value.category == "chat_collection_denied"


def test_search_clients_exact_fractional_total_raises() -> None:
    # 2.5 → int() cắt thành 2 sẽ cho phân trang sai → phải từ chối.
    pages = {0: {"items": [_client_item("C.aaa111", "DESKTOP-ABC")], "total": 2.5}}
    handler = _paged_handler(pages)

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert "số nguyên" in str(ei.value)
    assert ei.value.category == "chat_collection_denied"


def test_search_clients_exact_boolean_total_raises() -> None:
    # `True` là bool chứ không phải int hợp lệ cho `total`.
    pages = {0: {"items": [_client_item("C.aaa111", "DESKTOP-ABC")], "total": True}}
    handler = _paged_handler(pages)

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert "số nguyên" in str(ei.value)
    assert ei.value.category == "chat_collection_denied"


def test_search_clients_exact_items_exceed_total_raises() -> None:
    # offset + len(items) > total → phân trang không nhất quán → fail closed.
    pages = {
        0: {
            "items": [
                _client_item("C.aaa111", "DESKTOP-ABC"),
                _client_item("C.bbb222", "OTHER-PC"),
            ],
            "total": 1,
        }
    }
    handler = _paged_handler(pages)

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert "vượt total" in str(ei.value)
    assert ei.value.category == "chat_collection_denied"


# ── Finding I2: JSON hỏng phải theo error contract ────────────────────


def test_search_clients_exact_malformed_json_raises() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html>not json</html>",
            headers={"content-type": "application/json"},
        )

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert "JSON" in str(ei.value)
    assert ei.value.category == "chat_collection_denied"


# ── Finding I1: cửa sổ consistency là deadline có bao (fake clock) ────


class _FakeClock:
    """Đồng hồ giả để test deadline tất định (monkeypatch `_monotonic`)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _freeze_clock(monkeypatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr("app.services.velociraptor._monotonic", clock.now)
    return clock


def test_search_clients_exact_retry_bounded_by_consistency_window(monkeypatch) -> None:
    # Mỗi request "tốn" 3s; cửa sổ 5s → 1 lookup + 2 retry rồi bị chặn, KHÔNG retry
    # thứ 3 (request thứ 4) dù chưa thấy client.
    monkeypatch.setattr(settings, "resolver_consistency_window_seconds", 5)
    monkeypatch.setattr(
        "app.services.velociraptor.SEARCH_CLIENTS_RETRY_INTERVAL_SECONDS", 0.001
    )
    clock = _freeze_clock(monkeypatch)
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        clock.advance(3.0)
        return httpx.Response(200, json={"items": [], "total": 0})

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert ei.value.category == "chat_collection_denied"
    assert calls["n"] == 3


def test_search_clients_exact_match_after_window_fails_closed(monkeypatch) -> None:
    # Client khớp xuất hiện ở retry đã vượt cửa sổ → KHÔNG được trả về.
    monkeypatch.setattr(settings, "resolver_consistency_window_seconds", 5)
    monkeypatch.setattr(
        "app.services.velociraptor.SEARCH_CLIENTS_RETRY_INTERVAL_SECONDS", 0.001
    )
    clock = _freeze_clock(monkeypatch)
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        clock.advance(3.0)
        if calls["n"] < 3:
            return httpx.Response(200, json={"items": [], "total": 0})
        return httpx.Response(
            200,
            json={"items": [_client_item("C.late01", "DESKTOP-ABC")], "total": 1},
        )

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert ei.value.category == "chat_collection_denied"
    assert calls["n"] == 3


def test_search_clients_exact_retry_request_timeout_bounded(monkeypatch) -> None:
    # Request retry phải bị bao timeout theo deadline còn lại (≤ cửa sổ), không
    # dùng timeout 30s mặc định.
    monkeypatch.setattr(settings, "resolver_consistency_window_seconds", 5)
    monkeypatch.setattr(
        "app.services.velociraptor.SEARCH_CLIENTS_RETRY_INTERVAL_SECONDS", 0.001
    )
    clock = _freeze_clock(monkeypatch)
    timeouts: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        timeouts.append(dict(req.extensions.get("timeout") or {}))
        if len(timeouts) == 1:
            return httpx.Response(200, json={"items": [], "total": 0})
        clock.advance(10.0)  # retry này vượt khỏi cửa sổ 5s
        return httpx.Response(200, json={"items": [], "total": 0})

    with pytest.raises(VelociraptorError):
        _search(handler, "DESKTOP-ABC")
    assert len(timeouts) == 2
    read_timeout = timeouts[1].get("read")
    assert read_timeout is not None
    assert read_timeout <= 5.0


def test_search_clients_exact_retry_never_starts_after_deadline(monkeypatch) -> None:
    # Cửa sổ 0 → không retry; chỉ đúng 1 lookup rồi fail closed.
    monkeypatch.setattr(settings, "resolver_consistency_window_seconds", 0)
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"items": [], "total": 0})

    with pytest.raises(VelociraptorError) as ei:
        _search(handler, "DESKTOP-ABC")
    assert ei.value.category == "chat_collection_denied"
    assert calls["n"] == 1


def test_search_clients_exact_slow_retry_response_hits_absolute_deadline(
    monkeypatch,
) -> None:
    # Cửa sổ consistency phải là DEADLINE TUYỆT ĐỐI, không chỉ timeout từng read
    # của httpx: response retry chậm hơn cửa sổ (nhưng vẫn "sống") phải bị cancel
    # và fail closed, KHÔNG được chạy tới hết.
    monkeypatch.setattr(settings, "resolver_consistency_window_seconds", 1.0)
    monkeypatch.setattr(
        "app.services.velociraptor.SEARCH_CLIENTS_RETRY_INTERVAL_SECONDS", 0.01
    )
    calls = {"n": 0}

    async def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            # Lookup trực tiếp trả ngay, không khớp → kích hoạt retry có deadline.
            return httpx.Response(200, json={"items": [], "total": 0})
        # Retry: chậm hơn hẳn cửa sổ 1s → phải bị deadline tuyệt đối cắt.
        await asyncio.sleep(5.0)
        return httpx.Response(200, json={"items": [], "total": 0})

    client = VelociraptorClient(
        "https://veloci.test",
        username="admin",
        password="tok",
        transport=httpx.MockTransport(handler),
    )

    started = time.monotonic()

    async def run():
        async with client as c:
            return await c.search_clients_exact("DESKTOP-ABC")

    with pytest.raises(VelociraptorError) as ei:
        asyncio.run(run())
    elapsed = time.monotonic() - started

    assert ei.value.category == "chat_collection_denied"
    assert calls["n"] == 2
    # Bị cancel quanh deadline (~1s), KHÔNG chờ hết 5s của response.
    assert elapsed < 3.0
