"""Worksection API client."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, cast

import httpx

from worksection_mcp.cache.session_cache import SessionCache
from worksection_mcp.client.rate_limiter import AdaptiveRateLimiter
from worksection_mcp.config import Settings
from worksection_mcp.utils.date_utils import format_date_for_api

logger = logging.getLogger(__name__)


class WorksectionAPIError(Exception):
    """Worksection API error."""

    def __init__(self, message: str, status_code: int | None = None, response: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class OAuthTokenProvider(Protocol):
    """Protocol for OAuth providers required by WorksectionClient."""

    async def get_valid_token(self) -> str:
        """Return a valid access token."""
        ...

    async def close(self) -> None:
        """Close underlying resources."""
        ...


class WorksectionClient:
    """Async client for Worksection API with rate limiting."""

    def __init__(self, oauth: OAuthTokenProvider, settings: Settings):
        """Initialize Worksection client.

        Args:
            oauth: OAuth2 manager for authentication
            settings: Application settings
        """
        self.oauth = oauth
        self.settings = settings
        self.rate_limiter = AdaptiveRateLimiter(requests_per_second=1.0)
        self._http_client: httpx.AsyncClient | None = None
        self.cache = SessionCache()

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
            )
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client and OAuth manager."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
        await self.oauth.close()

    async def _make_request(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        method: str = "GET",
        use_cache: bool = False,
    ) -> dict[str, Any]:
        """Make an API request to Worksection.

        Args:
            action: API action name (e.g., 'get_projects')
            params: Additional query parameters
            method: HTTP method
            use_cache: Check/store in session cache

        Returns:
            API response data

        Raises:
            WorksectionAPIError: If request fails
        """
        # Check cache
        cache_key = ""
        if use_cache:
            frozen = frozenset((params or {}).items())
            cache_key = f"{action}:{frozen}"
            cached = await self.cache.get(cache_key)
            if cached is not None:
                return cast(dict[str, Any], cached)

        # Ensure we have a valid token
        token = await self.oauth.get_valid_token()

        # Build request
        client = await self._get_http_client()
        url = self.settings.api_base_url

        # Build parameters
        request_params = {"action": action}
        if params:
            request_params.update(params)

        headers = {"Authorization": f"Bearer {token}"}

        # Rate limiting
        async with self.rate_limiter:
            logger.debug(f"API request: {action} with params {params}")

            try:
                if method == "GET":
                    response = await client.get(url, params=request_params, headers=headers)
                else:
                    response = await client.post(url, params=request_params, headers=headers)

                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    self.rate_limiter.record_rate_limit(float(retry_after) if retry_after else None)
                    raise WorksectionAPIError(
                        "Rate limit exceeded",
                        status_code=429,
                    )

                # Record success for adaptive rate limiting
                self.rate_limiter.record_success()

                # Parse response
                if response.status_code != 200:
                    raise WorksectionAPIError(
                        f"API request failed: {response.text}",
                        status_code=response.status_code,
                    )

                data = cast(dict[str, Any], response.json())

                # Check for API-level errors
                if "error" in data:
                    raise WorksectionAPIError(
                        data.get("error_description", data["error"]),
                        response=data,
                    )

                # Store in cache
                if use_cache and cache_key:
                    await self.cache.set(cache_key, data)

                return data

            except httpx.ConnectError as e:
                # DNS or connection errors
                error_msg = str(e)
                if (
                    "nodename nor servname provided" in error_msg
                    or "Name or service not known" in error_msg
                ):
                    logger.error(f"DNS resolution failed for {url}")
                    raise WorksectionAPIError(
                        f"Cannot connect to Worksection API at {url}\n"
                        f"DNS resolution failed - the hostname cannot be resolved.\n"
                        f"Please verify WORKSECTION_ACCOUNT_URL in your .env file is correct.\n"
                        f"Current value: {self.settings.worksection_account_url}\n"
                        f"Original error: {e}"
                    ) from e

                logger.error(f"Connection failed to {url}: {e}")
                raise WorksectionAPIError(
                    f"Cannot connect to Worksection API at {url}\n"
                    f"Connection error: {e}\n"
                    f"Please check:\n"
                    f"  1. Your internet connection\n"
                    f"  2. WORKSECTION_ACCOUNT_URL is correct: {self.settings.worksection_account_url}\n"
                    f"  3. The Worksection service is accessible"
                ) from e

            except httpx.RequestError as e:
                logger.error(f"HTTP request failed: {e}")
                raise WorksectionAPIError(
                    f"Request failed: {e}\nURL: {url}\nAction: {action}"
                ) from e

    # ==========================================================================
    # Projects API
    # ==========================================================================

    async def get_projects(
        self,
        status_filter: str | None = None,
        extra: str | None = None,
    ) -> dict[str, Any]:
        """Get all projects.

        Args:
            status_filter: Filter by status (active, archive)
            extra: Additional data (text, options, users)

        Returns:
            Projects data with consistent structure
        """
        params = {}
        if status_filter:
            params["filter"] = status_filter
        if extra:
            params["extra"] = extra

        result = await self._make_request("get_projects", params)

        # Normalize response: ensure 'data' key exists
        if "data" not in result and result.get("status") == "ok":
            result["data"] = []

        return result

    async def get_project(
        self,
        project_id: str,
        extra: str | None = None,
    ) -> dict[str, Any]:
        """Get single project details.

        Args:
            project_id: Project ID
            extra: Additional data

        Returns:
            Project data
        """
        params = {"id_project": project_id}
        if extra:
            params["extra"] = extra
        return await self._make_request("get_project", params)

    async def get_project_groups(self) -> dict[str, Any]:
        """Get project folders/groups.

        Returns:
            Project groups data
        """
        return await self._make_request("get_project_groups")

    # ==========================================================================
    # Tasks API
    # ==========================================================================

    async def get_all_tasks(
        self,
        status_filter: str | None = None,
        extra: str | None = None,
    ) -> dict[str, Any]:
        """Get all tasks.

        Args:
            status_filter: Filter by status
            extra: Additional data (text, files, comments, relations, subtasks, subscribers)

        Returns:
            Tasks data with consistent structure:
            - status: "ok" or "error"
            - data: List of tasks (empty list if no tasks)
        """
        params = {}
        if status_filter:
            params["filter"] = status_filter
        if extra:
            params["extra"] = extra

        result = await self._make_request("get_all_tasks", params)

        # Normalize response: ensure 'data' key exists
        # API returns different structure when no data available
        if "data" not in result and result.get("status") == "ok":
            result["data"] = []

        return result

    async def get_tasks(
        self,
        project_id: str,
        status_filter: str | None = None,
        extra: str | None = None,
    ) -> dict[str, Any]:
        """Get tasks for a project.

        Args:
            project_id: Project ID
            status_filter: Filter by status
            extra: Additional data

        Returns:
            Tasks data with consistent structure
        """
        params = {"id_project": project_id}
        if status_filter:
            params["filter"] = status_filter
        if extra:
            params["extra"] = extra

        result = await self._make_request("get_tasks", params)

        # Normalize response: ensure 'data' key exists
        if "data" not in result and result.get("status") == "ok":
            result["data"] = []

        return result

    async def get_task(
        self,
        task_id: str,
        extra: str | None = None,
    ) -> dict[str, Any]:
        """Get single task details.

        Args:
            task_id: Task ID
            extra: Additional data

        Returns:
            Task data
        """
        params = {"id_task": task_id}
        if extra:
            params["extra"] = extra
        return await self._make_request("get_task", params)

    async def search_tasks(
        self,
        search_query: str | None = None,
        project_id: str | None = None,
        task_id: str | None = None,
        email_user_from: str | None = None,
        email_user_to: str | None = None,
        status: str | None = None,
        extra: str | None = None,
    ) -> dict[str, Any]:
        """Search tasks using Worksection query syntax.

        Args:
            search_query: Search query using Worksection syntax (e.g., "name has 'Report'")
                   Supports: name, dateadd, datestart, dateend, dateclose fields
                   Operators: =, has, >, <, >=, <=, !=, in, and, or
            project_id: Project ID to scope the search (at least one scope param required)
            task_id: Task ID to scope the search
            email_user_from: Filter by task author email
            email_user_to: Filter by assignee email
            status: Task state filter (active/done)
            extra: Additional data (text, html, files)

        Returns:
            Search results
        """
        params: dict[str, str] = {}
        if search_query:
            params["filter"] = search_query
        if project_id:
            params["id_project"] = project_id
        if task_id:
            params["id_task"] = task_id
        if email_user_from:
            params["email_user_from"] = email_user_from
        if email_user_to:
            params["email_user_to"] = email_user_to
        if status:
            params["status"] = status
        if extra:
            params["extra"] = extra
        return await self._make_request("search_tasks", params)

    # ==========================================================================
    # Comments API
    # ==========================================================================

    async def get_comments(
        self,
        task_id: str,
        extra: str | None = None,
    ) -> dict[str, Any]:
        """Get comments for a task.

        Args:
            task_id: Task ID
            extra: Additional data (files)

        Returns:
            Comments data
        """
        params = {"id_task": task_id}
        if extra:
            params["extra"] = extra
        return await self._make_request("get_comments", params)

    # ==========================================================================
    # Files API
    # ==========================================================================

    async def download_file(self, file_id: str) -> bytes:
        """Download a file.

        Args:
            file_id: File ID

        Returns:
            File content as bytes
        """
        token = await self.oauth.get_valid_token()
        client = await self._get_http_client()

        params = {
            "action": "download",
            "id_file": file_id,
        }
        headers = {"Authorization": f"Bearer {token}"}

        async with self.rate_limiter:
            response = await client.get(
                self.settings.api_base_url,
                params=params,
                headers=headers,
            )

            if response.status_code != 200:
                raise WorksectionAPIError(
                    f"File download failed: {response.status_code}",
                    status_code=response.status_code,
                )

            self.rate_limiter.record_success()
            payload = response.content

            # Detect API error responses disguised as file downloads.
            # Small JSON payloads with status=error indicate the file
            # could not be retrieved (e.g., not found, access denied).
            if len(payload) < 8192 and payload.lstrip().startswith(b"{"):
                try:
                    parsed = json.loads(payload)
                    if isinstance(parsed, dict) and parsed.get("status") == "error":
                        msg = parsed.get("message") or parsed.get("msg")
                        if isinstance(msg, str) and msg.strip():
                            raise WorksectionAPIError(
                                f"File download error: {msg}",
                                response=parsed,
                            )
                except json.JSONDecodeError, UnicodeDecodeError:
                    pass  # Not JSON — return as normal file content

            return payload

    async def get_files(
        self,
        project_id: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Get files from a project or task.

        Returns files from the Files section, project/task descriptions,
        and comments.

        Args:
            project_id: Project ID
            task_id: Task ID

        Returns:
            Files data
        """
        params: dict[str, str] = {}
        if project_id:
            params["id_project"] = project_id
        if task_id:
            params["id_task"] = task_id
        return await self._make_request("get_files", params)

    # ==========================================================================
    # Costs API
    # ==========================================================================

    async def get_costs(
        self,
        project_id: str | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        is_timer: bool | None = None,
    ) -> dict[str, Any]:
        """Get cost/time records.

        Args:
            project_id: Filter by project
            task_id: Filter by task
            user_id: Filter by user
            date_start: Start date (YYYY-MM-DD or DD.MM.YYYY)
            date_end: End date (YYYY-MM-DD or DD.MM.YYYY)
            is_timer: Filter by timer status

        Returns:
            Costs data
        """
        params = {}
        if project_id:
            params["id_project"] = project_id
        if task_id:
            params["id_task"] = task_id
        if user_id:
            params["id_user"] = user_id
        if date_start:
            formatted_start = format_date_for_api(date_start)
            if formatted_start is not None:
                params["datestart"] = formatted_start
        if date_end:
            formatted_end = format_date_for_api(date_end)
            if formatted_end is not None:
                params["dateend"] = formatted_end
        if is_timer is not None:
            params["is_timer"] = "1" if is_timer else "0"
        return await self._make_request("get_costs", params)

    async def get_costs_total(
        self,
        project_id: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
    ) -> dict[str, Any]:
        """Get aggregated cost totals.

        Args:
            project_id: Filter by project
            date_start: Start date (YYYY-MM-DD or DD.MM.YYYY)
            date_end: End date (YYYY-MM-DD or DD.MM.YYYY)

        Returns:
            Aggregated costs
        """
        params = {}
        if project_id:
            params["id_project"] = project_id
        if date_start:
            formatted_start = format_date_for_api(date_start)
            if formatted_start is not None:
                params["datestart"] = formatted_start
        if date_end:
            formatted_end = format_date_for_api(date_end)
            if formatted_end is not None:
                params["dateend"] = formatted_end
        return await self._make_request("get_costs_total", params)

    # ==========================================================================
    # Users API
    # ==========================================================================

    async def get_users(self, status_filter: str | None = None) -> dict[str, Any]:
        """Get all users.

        Args:
            status_filter: Filter by status

        Returns:
            Users data with consistent structure
        """
        params = {}
        if status_filter:
            params["filter"] = status_filter

        result = await self._make_request("get_users", params)

        # Normalize response: ensure 'data' key exists
        if "data" not in result and result.get("status") == "ok":
            result["data"] = []

        return result

    async def get_user(self, user_id: str) -> dict[str, Any]:
        """Get single user details.

        Note: Worksection API doesn't have a get_user action.
        This method gets all users and filters to the requested one.

        Args:
            user_id: User ID

        Returns:
            User data
        """
        # Get all users and find the specific one
        result = await self.get_users()

        if isinstance(result, dict) and "data" in result:
            for user in result["data"]:
                if str(user.get("id")) == str(user_id):
                    return {"status": "ok", "data": user}

        # User not found
        return {
            "status": "error",
            "message": f"User with id {user_id} not found",
        }

    async def me(self) -> dict:
        """Get current authenticated user.

        Returns:
            Current user data
        """
        return await self._make_request("me")

    async def get_user_groups(self) -> dict:
        """Get user teams/departments.

        Returns:
            User groups data
        """
        return await self._make_request("get_user_groups")

    async def get_contacts(self) -> dict:
        """Get contact database.

        Returns:
            Contacts data
        """
        return await self._make_request("get_contacts")

    async def get_contact_groups(self) -> dict:
        """Get contact folders/groups.

        Returns:
            Contact groups data
        """
        return await self._make_request("get_contact_groups")

    # ==========================================================================
    # Tags API (Read-only)
    # ==========================================================================

    async def get_task_tags(
        self,
        group: str | None = None,
        tag_type: str | None = None,
        access: str | None = None,
    ) -> dict:
        """Get task tags from all or selected group.

        Args:
            group: Filter by tag group (name or ID)
            tag_type: Filter by group type ('status' or 'label')
            access: Filter by visibility ('public' or 'private')

        Returns:
            Tags data
        """
        params = {}
        if group:
            params["group"] = group
        if tag_type:
            params["type"] = tag_type
        if access:
            params["access"] = access
        return await self._make_request("get_task_tags", params)

    async def get_task_tag_groups(
        self,
        tag_type: str | None = None,
        access: str | None = None,
    ) -> dict:
        """Get task tag groups.

        Args:
            tag_type: Filter by group type ('status' or 'label')
            access: Filter by visibility ('public' or 'private')

        Returns:
            Tag groups data
        """
        params = {}
        if tag_type:
            params["type"] = tag_type
        if access:
            params["access"] = access
        return await self._make_request("get_task_tag_groups", params if params else None)

    async def get_project_tags(
        self,
        group: str | None = None,
        tag_type: str | None = None,
        access: str | None = None,
    ) -> dict:
        """Get project tags from all or selected group.

        Args:
            group: Filter by tag group (name or ID)
            tag_type: Filter by group type ('status' or 'label')
            access: Filter by visibility ('public' or 'private')

        Returns:
            Project tags data
        """
        params = {}
        if group:
            params["group"] = group
        if tag_type:
            params["type"] = tag_type
        if access:
            params["access"] = access
        return await self._make_request("get_project_tags", params if params else None)

    async def get_project_tag_groups(
        self,
        tag_type: str | None = None,
        access: str | None = None,
    ) -> dict:
        """Get project tag groups.

        Args:
            tag_type: Filter by group type ('status' or 'label')
            access: Filter by visibility ('public' or 'private')

        Returns:
            Project tag groups data
        """
        params = {}
        if tag_type:
            params["type"] = tag_type
        if access:
            params["access"] = access
        return await self._make_request("get_project_tag_groups", params if params else None)

    # ==========================================================================
    # Activity API
    # ==========================================================================

    async def get_events(
        self,
        project_id: str | None = None,
        period: str | None = None,
    ) -> dict:
        """Get activity/event log.

        Args:
            project_id: Filter by project
            period: Time period for events. Format:
                - Minutes: 1m to 360m (e.g., "120m" for 2 hours)
                - Hours: 1h to 72h (e.g., "24h" for 1 day)
                - Days: 1d to 30d (e.g., "7d" for 1 week)

        Returns:
            Events data
        """
        params = {}
        if project_id:
            params["id_project"] = project_id
        if period:
            params["period"] = period
        return await self._make_request("get_events", params)

    # ==========================================================================
    # Timers API
    # ==========================================================================

    async def get_timers(self) -> dict[str, Any]:
        """Get all running timers.

        Returns:
            Timers data with list of active timers
        """
        return await self._make_request("get_timers", method="POST")

    async def get_my_timer(self) -> dict[str, Any]:
        """Get current user's timer.

        Returns:
            Current user's timer data
        """
        return await self._make_request("get_my_timer", method="POST")

    # ==========================================================================
    # Write API (mutations)
    #
    # These issue POST requests that MODIFY Worksection data. They require an
    # OAuth token authorized with the relevant *_write scope AND are gated at
    # the tool layer by Settings.worksection_enable_writes. Keep this section
    # thin: validation and gating live in tools/writes.py.
    # ==========================================================================

    async def add_costs(
        self,
        task_id: str,
        time: str | None = None,
        money: str | None = None,
        comment: str | None = None,
        date: str | None = None,
    ) -> dict[str, Any]:
        """Log time and/or money against a task (requires costs_write scope).

        Args:
            task_id: Task ID the cost belongs to
            time: Time in Worksection format, one of "0.15", "0,15" or "0:09"
            money: Money amount, when logging a monetary cost
            comment: Optional note describing the work
            date: Optional date the cost belongs to, as YYYY-MM-DD

        Returns:
            API response carrying the created cost id
        """
        if not time and not money:
            raise ValueError("at least one of time or money is required")
        params: dict[str, Any] = {"id_task": task_id}
        if time:
            params["time"] = time
        if money:
            params["money"] = money
        if comment:
            params["comment"] = comment
        if date:
            params["date"] = date
        return await self._make_request("add_costs", params, method="POST")

    async def post_comment(
        self,
        task_id: str,
        text: str,
        hidden: str | None = None,
        mention: str | None = None,
    ) -> dict[str, Any]:
        """Create a comment on a task (requires comments_write scope).

        Args:
            task_id: Task ID to comment on
            text: Comment body
            hidden: Comma-separated emails who may see an otherwise-hidden comment
            mention: Comma-separated emails to mention at the end of the comment

        Returns:
            API response with the created comment
        """
        params: dict[str, Any] = {"id_task": task_id, "text": text}
        if hidden:
            params["hidden"] = hidden
        if mention:
            params["mention"] = mention
        return await self._make_request("post_comment", params, method="POST")

    async def post_task(
        self,
        project_id: str,
        title: str,
        parent_task_id: str | None = None,
        assignee_email: str | None = None,
        priority: int | None = None,
        text: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        subscribe: str | None = None,
        max_time: str | None = None,
        max_money: str | None = None,
        tags: str | None = None,
    ) -> dict[str, Any]:
        """Create a (sub)task in a project (requires tasks_write scope).

        Args:
            project_id: Project ID to create the task in
            title: Task name
            parent_task_id: Parent task ID (creates a subtask when set)
            assignee_email: Executive email, or 'ANY' / 'NOONE'
            priority: Priority 0..10
            text: Task description
            date_start: Start date (YYYY-MM-DD or DD.MM.YYYY)
            date_end: Due date (YYYY-MM-DD or DD.MM.YYYY)
            subscribe: Comma-separated emails to subscribe to the task
            max_time: Time estimate
            max_money: Financial estimate
            tags: Comma-separated existing tag names or IDs

        Returns:
            API response with the created task
        """
        params: dict[str, Any] = {"id_project": project_id, "title": title}
        if parent_task_id:
            params["id_parent"] = parent_task_id
        if assignee_email:
            params["email_user_to"] = assignee_email
        if priority is not None:
            params["priority"] = str(priority)
        if text:
            params["text"] = text
        if date_start:
            formatted = format_date_for_api(date_start)
            if formatted is not None:
                params["datestart"] = formatted
        if date_end:
            formatted = format_date_for_api(date_end)
            if formatted is not None:
                params["dateend"] = formatted
        if subscribe:
            params["subscribe"] = subscribe
        if max_time:
            params["max_time"] = max_time
        if max_money:
            params["max_money"] = max_money
        if tags:
            params["tags"] = tags
        return await self._make_request("post_task", params, method="POST")

    async def update_task(
        self,
        task_id: str,
        title: str | None = None,
        assignee_email: str | None = None,
        priority: int | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        date_closed: str | None = None,
        max_time: str | None = None,
        max_money: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing (sub)task's parameters (requires tasks_write scope).

        Args:
            task_id: Task ID to update
            title: New task name
            assignee_email: New executive email, or 'ANY' / 'NOONE'
            priority: Priority 0..10
            date_start: Start date (YYYY-MM-DD or DD.MM.YYYY)
            date_end: Due date (YYYY-MM-DD or DD.MM.YYYY)
            date_closed: Closing date (YYYY-MM-DD or DD.MM.YYYY)
            max_time: Time estimate
            max_money: Financial estimate

        Returns:
            API response with the updated task
        """
        params: dict[str, Any] = {"id_task": task_id}
        if title:
            params["title"] = title
        if assignee_email:
            params["email_user_to"] = assignee_email
        if priority is not None:
            params["priority"] = str(priority)
        if date_start:
            formatted = format_date_for_api(date_start)
            if formatted is not None:
                params["datestart"] = formatted
        if date_end:
            formatted = format_date_for_api(date_end)
            if formatted is not None:
                params["dateend"] = formatted
        if date_closed:
            formatted = format_date_for_api(date_closed)
            if formatted is not None:
                params["dateclosed"] = formatted
        if max_time:
            params["max_time"] = max_time
        if max_money:
            params["max_money"] = max_money
        return await self._make_request("update_task", params, method="POST")

    async def complete_task(self, task_id: str) -> dict[str, Any]:
        """Mark a (sub)task as complete (requires tasks_write scope).

        Args:
            task_id: Task ID to complete

        Returns:
            API response
        """
        return await self._make_request("complete_task", {"id_task": task_id}, method="POST")

    async def reopen_task(self, task_id: str) -> dict[str, Any]:
        """Reopen a completed (sub)task (requires tasks_write scope).

        Args:
            task_id: Task ID to reopen

        Returns:
            API response
        """
        return await self._make_request("reopen_task", {"id_task": task_id}, method="POST")

    async def update_task_tags(
        self,
        task_id: str,
        plus: str | None = None,
        minus: str | None = None,
    ) -> dict[str, Any]:
        """Add and/or remove status/label tags on a task (requires tags_write scope).

        Args:
            task_id: Task ID
            plus: Comma-separated tag names or IDs to add
            minus: Comma-separated tag names or IDs to remove

        Returns:
            API response
        """
        params: dict[str, Any] = {"id_task": task_id}
        if plus:
            params["plus"] = plus
        if minus:
            params["minus"] = minus
        return await self._make_request("update_task_tags", params, method="POST")

    # ==========================================================================
    # System API
    # ==========================================================================

    async def get_webhooks(self) -> dict:
        """Get configured webhooks.

        Requires the 'administrative' scope.

        Returns:
            Webhooks data
        """
        return await self._make_request("get_webhooks")
