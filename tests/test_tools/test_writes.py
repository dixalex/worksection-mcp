"""Tests for write (mutation) MCP tools and their enable-flag gating."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.helpers import FakeMCP
from worksection_mcp.tools.writes import register_write_tools


def _make_write_client(**overrides: Any) -> Any:
    """Client-like object exposing the async write methods used by write tools."""
    defaults: dict[str, Any] = {
        "post_comment": AsyncMock(return_value={"status": "ok", "data": {"id": "c1"}}),
        "post_task": AsyncMock(return_value={"status": "ok", "data": {"id": "t1"}}),
        "update_task": AsyncMock(return_value={"status": "ok", "data": {"id": "t1"}}),
        "complete_task": AsyncMock(return_value={"status": "ok"}),
        "reopen_task": AsyncMock(return_value={"status": "ok"}),
        "update_task_tags": AsyncMock(return_value={"status": "ok"}),
        "add_costs": AsyncMock(return_value={"status": "ok", "id": 3706}),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _settings(enabled: bool) -> Any:
    return SimpleNamespace(worksection_enable_writes=enabled)


def test_write_tools_are_registered() -> None:
    """Every write tool should be registered."""
    mcp = FakeMCP()
    register_write_tools(mcp, _make_write_client(), _settings(True))
    for name in (
        "add_comment",
        "create_task",
        "update_task",
        "complete_task",
        "reopen_task",
        "set_task_status",
        "log_time",
    ):
        assert name in mcp.tools


@pytest.mark.asyncio
async def test_writes_disabled_refuses_and_never_calls_client() -> None:
    """When the flag is off, every tool returns writes_disabled and calls nothing."""
    client = _make_write_client()
    mcp = FakeMCP()
    register_write_tools(mcp, client, _settings(False))

    results = [
        await mcp.tools["add_comment"]("t1", "hi"),
        await mcp.tools["create_task"]("p1", "New task"),
        await mcp.tools["update_task"]("t1", title="Renamed"),
        await mcp.tools["complete_task"]("t1"),
        await mcp.tools["reopen_task"]("t1"),
        await mcp.tools["set_task_status"]("t1", add_tags="On Track"),
        await mcp.tools["log_time"]("t1", "1:30"),
    ]

    for r in results:
        assert r["status"] == "error"
        assert r["error"] == "writes_disabled"

    client.post_comment.assert_not_awaited()
    client.post_task.assert_not_awaited()
    client.update_task.assert_not_awaited()
    client.complete_task.assert_not_awaited()
    client.reopen_task.assert_not_awaited()
    client.update_task_tags.assert_not_awaited()
    client.add_costs.assert_not_awaited()


@pytest.mark.asyncio
async def test_writes_enabled_delegate_to_client() -> None:
    """When enabled, tools call the matching client method with expected params."""
    client = _make_write_client()
    mcp = FakeMCP()
    register_write_tools(mcp, client, _settings(True))

    await mcp.tools["add_comment"]("t1", "hello", mention_emails="a@x.com")
    client.post_comment.assert_awaited_with(
        task_id="t1", text="hello", hidden=None, mention="a@x.com"
    )

    await mcp.tools["create_task"](
        "p1", "Build", assignee_email="dev@x.com", priority=5, description="do it"
    )
    client.post_task.assert_awaited_with(
        project_id="p1",
        title="Build",
        parent_task_id=None,
        assignee_email="dev@x.com",
        priority=5,
        text="do it",
        date_start=None,
        date_end=None,
        subscribe=None,
        max_time=None,
        max_money=None,
        tags=None,
    )

    await mcp.tools["update_task"]("t1", priority=1)
    client.update_task.assert_awaited_with(
        task_id="t1",
        title=None,
        assignee_email=None,
        priority=1,
        date_start=None,
        date_end=None,
        date_closed=None,
        max_time=None,
        max_money=None,
    )

    await mcp.tools["complete_task"]("t1")
    client.complete_task.assert_awaited_with(task_id="t1")

    await mcp.tools["reopen_task"]("t1")
    client.reopen_task.assert_awaited_with(task_id="t1")

    await mcp.tools["set_task_status"]("t1", add_tags="On Track", remove_tags="On Hold")
    client.update_task_tags.assert_awaited_with(task_id="t1", plus="On Track", minus="On Hold")


@pytest.mark.asyncio
async def test_write_input_validation() -> None:
    """Validation errors should raise before any client call (when enabled)."""
    client = _make_write_client()
    mcp = FakeMCP()
    register_write_tools(mcp, client, _settings(True))

    with pytest.raises(ValueError, match="text must be"):
        await mcp.tools["add_comment"]("t1", "   ")
    with pytest.raises(ValueError, match="title must be"):
        await mcp.tools["create_task"]("p1", "")
    with pytest.raises(ValueError, match="priority must be between"):
        await mcp.tools["create_task"]("p1", "ok", priority=99)
    with pytest.raises(ValueError, match="priority must be between"):
        await mcp.tools["update_task"]("t1", priority=-1)
    with pytest.raises(ValueError, match="at least one of add_tags"):
        await mcp.tools["set_task_status"]("t1")

    client.post_comment.assert_not_awaited()
    client.post_task.assert_not_awaited()
    client.update_task.assert_not_awaited()
    client.update_task_tags.assert_not_awaited()


@pytest.mark.asyncio
async def test_validation_is_checked_after_the_enable_gate() -> None:
    """A disabled server refuses even syntactically-invalid calls (no raise)."""
    client = _make_write_client()
    mcp = FakeMCP()
    register_write_tools(mcp, client, _settings(False))

    # Empty title would raise if enabled, but the disabled gate returns first.
    result = await mcp.tools["create_task"]("p1", "")
    assert result["error"] == "writes_disabled"
    client.post_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_log_time_delegates_to_add_costs() -> None:
    """Enabled log_time should forward the task and time to the client."""
    client = _make_write_client()
    mcp = FakeMCP()
    register_write_tools(mcp, client, _settings(True))

    result = await mcp.tools["log_time"]("t1", "0:45")

    client.add_costs.assert_awaited_with(task_id="t1", time="0:45", comment=None, date=None)
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_log_time_rejects_blank_time() -> None:
    """A blank time must fail before any client call."""
    client = _make_write_client()
    mcp = FakeMCP()
    register_write_tools(mcp, client, _settings(True))

    with pytest.raises(ValueError, match="time must be a non-empty string"):
        await mcp.tools["log_time"]("t1", "   ")

    client.add_costs.assert_not_awaited()


@pytest.mark.asyncio
async def test_log_time_forwards_date_and_comment() -> None:
    """A backdated entry must pass the day and note through to the client."""
    client = _make_write_client()
    mcp = FakeMCP()
    register_write_tools(mcp, client, _settings(True))

    await mcp.tools["log_time"]("t1", "2:00", comment="webhook review", date="2026-09-21")

    client.add_costs.assert_awaited_with(
        task_id="t1", time="2:00", comment="webhook review", date="2026-09-21"
    )
