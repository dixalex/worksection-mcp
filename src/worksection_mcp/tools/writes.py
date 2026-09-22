"""Write (mutation) MCP tools for Worksection.

DISABLED BY DEFAULT. Every tool in this module modifies live Worksection data
(creates/edits tasks, posts comments, changes task status, logs time). They refuse to run
unless BOTH of these are true:

1. ``WORKSECTION_ENABLE_WRITES=true`` in the environment, and
2. the OAuth token was authorized with the relevant ``*_write`` scope
   (``tasks_write`` for tasks/status, ``comments_write`` for comments,
   ``tags_write`` for status-label changes, ``costs_write`` for logged time).

The enable flag is the local kill-switch; the token scope is enforced by the
Worksection API itself. Both layers must agree before anything is written.
"""

from __future__ import annotations

import logging

from worksection_mcp.client import WorksectionClient
from worksection_mcp.config import Settings
from worksection_mcp.mcp_protocols import ToolRegistrar

logger = logging.getLogger(__name__)

_WRITES_DISABLED = {
    "status": "error",
    "error": "writes_disabled",
    "message": (
        "Worksection write operations are disabled. Set WORKSECTION_ENABLE_WRITES=true "
        "and re-authenticate with the required *_write scopes (tasks_write, "
        "comments_write, tags_write, costs_write) to enable."
    ),
}


def register_write_tools(
    mcp: ToolRegistrar,
    client: WorksectionClient,
    settings: Settings,
) -> None:
    """Register mutating tools, all gated behind ``settings.worksection_enable_writes``."""

    def _blocked() -> dict | None:
        """Return the refusal envelope when writes are disabled, else None."""
        if not settings.worksection_enable_writes:
            return dict(_WRITES_DISABLED)
        return None

    @mcp.tool()
    async def add_comment(
        task_id: str,
        text: str,
        mention_emails: str | None = None,
        hidden_emails: str | None = None,
    ) -> dict:
        """Post a comment on a task. WRITE — visible to everyone with task access.

        Requires WORKSECTION_ENABLE_WRITES=true and the comments_write scope.
        The comment is authored by the account that owns the OAuth token.

        Args:
            task_id: The task ID to comment on
            text: The comment body (must be non-empty)
            mention_emails: Optional comma-separated emails to @mention
            hidden_emails: Optional comma-separated emails limiting who can see the comment

        Returns:
            API response with the created comment, or a writes_disabled error envelope
        """
        blocked = _blocked()
        if blocked:
            return blocked
        if not text or not text.strip():
            raise ValueError("text must be a non-empty string")
        logger.info("WRITE add_comment id_task=%s", task_id)
        return await client.post_comment(
            task_id=task_id,
            text=text,
            hidden=hidden_emails,
            mention=mention_emails,
        )

    @mcp.tool()
    async def log_time(
        task_id: str,
        time: str,
        comment: str | None = None,
        date: str | None = None,
    ) -> dict:
        """Log time spent on a task. WRITE — creates a cost entry on live data.

        Requires WORKSECTION_ENABLE_WRITES=true and the costs_write scope.
        The entry is attributed to the account that owns the OAuth token.
        Without a date the entry lands on today.

        Args:
            task_id: The task ID to log time against
            time: Time spent, one of "0.15" (decimal hours), "0,15" or "0:09" (h:mm)
            comment: Optional note describing what the time went on
            date: Optional day the time belongs to, as YYYY-MM-DD

        Returns:
            API response with the created cost id, or a writes_disabled error envelope
        """
        blocked = _blocked()
        if blocked:
            return blocked
        if not time or not time.strip():
            raise ValueError("time must be a non-empty string")
        logger.info("WRITE log_time id_task=%s time=%s date=%s", task_id, time, date)
        return await client.add_costs(task_id=task_id, time=time, comment=comment, date=date)

    @mcp.tool()
    async def create_task(
        project_id: str,
        title: str,
        parent_task_id: str | None = None,
        assignee_email: str | None = None,
        priority: int | None = None,
        description: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        subscribe_emails: str | None = None,
        max_time: str | None = None,
        max_money: str | None = None,
        tags: str | None = None,
    ) -> dict:
        """Create a task (or subtask) in a project. WRITE — creates real work.

        Requires WORKSECTION_ENABLE_WRITES=true and the tasks_write scope.

        Args:
            project_id: Project ID to create the task in
            title: Task name (must be non-empty)
            parent_task_id: Set to create a subtask under this parent
            assignee_email: Executive email, or the literals 'ANY'/'NOONE'
            priority: Priority 0..10
            description: Task description text
            date_start: Start date (YYYY-MM-DD or DD.MM.YYYY)
            date_end: Due date (YYYY-MM-DD or DD.MM.YYYY)
            subscribe_emails: Comma-separated emails to subscribe
            max_time: Time estimate
            max_money: Financial estimate
            tags: Comma-separated existing tag names or IDs

        Returns:
            API response with the created task, or a writes_disabled error envelope
        """
        blocked = _blocked()
        if blocked:
            return blocked
        if not title or not title.strip():
            raise ValueError("title must be a non-empty string")
        if priority is not None and not (0 <= priority <= 10):
            raise ValueError("priority must be between 0 and 10")
        logger.info("WRITE create_task id_project=%s title=%r", project_id, title)
        return await client.post_task(
            project_id=project_id,
            title=title,
            parent_task_id=parent_task_id,
            assignee_email=assignee_email,
            priority=priority,
            text=description,
            date_start=date_start,
            date_end=date_end,
            subscribe=subscribe_emails,
            max_time=max_time,
            max_money=max_money,
            tags=tags,
        )

    @mcp.tool()
    async def update_task(
        task_id: str,
        title: str | None = None,
        assignee_email: str | None = None,
        priority: int | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        date_closed: str | None = None,
        max_time: str | None = None,
        max_money: str | None = None,
    ) -> dict:
        """Update an existing task's fields. WRITE — edits real work.

        Requires WORKSECTION_ENABLE_WRITES=true and the tasks_write scope.
        Only the fields you pass are changed. To open/close a task use
        complete_task / reopen_task; to change status labels use set_task_status.

        Args:
            task_id: Task ID to update
            title: New task name
            assignee_email: New executive email, or 'ANY'/'NOONE'
            priority: Priority 0..10
            date_start: Start date (YYYY-MM-DD or DD.MM.YYYY)
            date_end: Due date (YYYY-MM-DD or DD.MM.YYYY)
            date_closed: Closing date (YYYY-MM-DD or DD.MM.YYYY)
            max_time: Time estimate
            max_money: Financial estimate

        Returns:
            API response with the updated task, or a writes_disabled error envelope
        """
        blocked = _blocked()
        if blocked:
            return blocked
        if priority is not None and not (0 <= priority <= 10):
            raise ValueError("priority must be between 0 and 10")
        logger.info("WRITE update_task id_task=%s", task_id)
        return await client.update_task(
            task_id=task_id,
            title=title,
            assignee_email=assignee_email,
            priority=priority,
            date_start=date_start,
            date_end=date_end,
            date_closed=date_closed,
            max_time=max_time,
            max_money=max_money,
        )

    @mcp.tool()
    async def complete_task(task_id: str) -> dict:
        """Mark a task as done. WRITE — changes task status for the whole team.

        Requires WORKSECTION_ENABLE_WRITES=true and the tasks_write scope.

        Args:
            task_id: Task ID to complete

        Returns:
            API response, or a writes_disabled error envelope
        """
        blocked = _blocked()
        if blocked:
            return blocked
        logger.info("WRITE complete_task id_task=%s", task_id)
        return await client.complete_task(task_id=task_id)

    @mcp.tool()
    async def reopen_task(task_id: str) -> dict:
        """Reopen a completed task. WRITE — changes task status for the whole team.

        Requires WORKSECTION_ENABLE_WRITES=true and the tasks_write scope.

        Args:
            task_id: Task ID to reopen

        Returns:
            API response, or a writes_disabled error envelope
        """
        blocked = _blocked()
        if blocked:
            return blocked
        logger.info("WRITE reopen_task id_task=%s", task_id)
        return await client.reopen_task(task_id=task_id)

    @mcp.tool()
    async def set_task_status(
        task_id: str,
        add_tags: str | None = None,
        remove_tags: str | None = None,
    ) -> dict:
        """Add/remove status or label tags on a task. WRITE — needs tags_write scope.

        Use this for status-label tags (e.g. 'On Track', 'On Hold', 'Off Track'),
        distinct from the done/active state handled by complete_task/reopen_task.
        Requires WORKSECTION_ENABLE_WRITES=true and the tags_write scope (which is
        NOT part of the default comments+tasks write set — grant it separately).

        Args:
            task_id: Task ID
            add_tags: Comma-separated tag names or IDs to add
            remove_tags: Comma-separated tag names or IDs to remove

        Returns:
            API response, or a writes_disabled error envelope
        """
        blocked = _blocked()
        if blocked:
            return blocked
        if not add_tags and not remove_tags:
            raise ValueError("Provide at least one of add_tags or remove_tags")
        logger.info("WRITE set_task_status id_task=%s", task_id)
        return await client.update_task_tags(task_id=task_id, plus=add_tags, minus=remove_tags)
