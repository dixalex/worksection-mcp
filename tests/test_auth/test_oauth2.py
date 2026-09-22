"""Tests for OAuth2 manager behavior."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from tests.helpers import build_settings
from worksection_mcp.auth.oauth2 import OAuth2Error, OAuth2Manager


@pytest.fixture
def oauth_manager(tmp_path):
    """Create OAuth manager with temp settings."""
    settings = build_settings(tmp_path)
    return OAuth2Manager(settings)


def test_build_authorize_url_contains_expected_params(oauth_manager):
    """Authorization URL should include required OAuth query params."""
    url = oauth_manager._build_authorize_url("csrf-state")
    assert url.startswith("https://worksection.com/oauth2/authorize?")
    assert "client_id=test_client_id_12345" in url
    assert "redirect_uri=https%3A%2F%2Flocalhost%3A8080%2Foauth%2Fcallback" in url
    assert "response_type=code" in url
    assert "state=csrf-state" in url


@pytest.mark.asyncio
async def test_exchange_code_success(oauth_manager):
    """Successful token exchange should return parsed response payload."""
    http_client = AsyncMock()
    http_client.post = AsyncMock(
        return_value=httpx.Response(200, json={"access_token": "a", "refresh_token": "r"})
    )
    oauth_manager._get_http_client = AsyncMock(return_value=http_client)  # type: ignore[method-assign]

    data = await oauth_manager._exchange_code("auth-code")
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_exchange_code_error_response(oauth_manager):
    """Non-200 token exchange should raise OAuth2Error with API details."""
    http_client = AsyncMock()
    http_client.post = AsyncMock(
        return_value=httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "bad code"},
        )
    )
    oauth_manager._get_http_client = AsyncMock(return_value=http_client)  # type: ignore[method-assign]

    with pytest.raises(OAuth2Error, match="invalid_grant"):
        await oauth_manager._exchange_code("auth-code")


@pytest.mark.asyncio
async def test_refresh_token_no_stored_refresh_token(oauth_manager):
    """Refresh should fail fast when no refresh token exists."""
    oauth_manager.token_storage = SimpleNamespace(get_refresh_token=MagicMock(return_value=None))
    with pytest.raises(OAuth2Error, match="No refresh token available"):
        await oauth_manager._refresh_token()


@pytest.mark.asyncio
async def test_refresh_token_success(oauth_manager):
    """Refresh flow should return new token payload."""
    oauth_manager.token_storage = SimpleNamespace(
        get_refresh_token=MagicMock(return_value="r-token")
    )
    http_client = AsyncMock()
    http_client.post = AsyncMock(
        return_value=httpx.Response(
            200,
            json={"access_token": "new", "refresh_token": "r2", "expires_in": 3600},
        )
    )
    oauth_manager._get_http_client = AsyncMock(return_value=http_client)  # type: ignore[method-assign]

    data = await oauth_manager._refresh_token()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_refresh_token_handles_invalid_success_body(oauth_manager):
    """API can return HTTP 200 with error payload; this should raise."""
    oauth_manager.token_storage = SimpleNamespace(
        get_refresh_token=MagicMock(return_value="r-token")
    )
    http_client = AsyncMock()
    http_client.post = AsyncMock(
        return_value=httpx.Response(
            200,
            json={"error": "invalid_token", "error_description": "expired refresh token"},
        )
    )
    oauth_manager._get_http_client = AsyncMock(return_value=http_client)  # type: ignore[method-assign]

    with pytest.raises(OAuth2Error, match="invalid_token"):
        await oauth_manager._refresh_token()


@pytest.mark.asyncio
async def test_ensure_authenticated_short_circuits_when_access_token_valid(oauth_manager):
    """Valid access token should bypass refresh/authentication flow."""
    oauth_manager.token_storage = SimpleNamespace(
        is_access_token_valid=MagicMock(return_value=True),
        get_refresh_token=MagicMock(return_value="unused"),
    )
    oauth_manager.authenticate = AsyncMock()
    oauth_manager._refresh_token = AsyncMock()

    await oauth_manager.ensure_authenticated()

    oauth_manager._refresh_token.assert_not_called()
    oauth_manager.authenticate.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_authenticated_refreshes_when_possible(oauth_manager):
    """Expired token with refresh token should refresh and save."""
    oauth_manager.token_storage = SimpleNamespace(
        is_access_token_valid=MagicMock(return_value=False),
        get_refresh_token=MagicMock(return_value="refresh"),
        save=MagicMock(),
    )
    oauth_manager._refresh_token = AsyncMock(return_value={"access_token": "new"})
    oauth_manager.authenticate = AsyncMock()

    await oauth_manager.ensure_authenticated()

    oauth_manager.token_storage.save.assert_called_once_with({"access_token": "new"})
    oauth_manager.authenticate.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_authenticated_keeps_tokens_when_refresh_fails(oauth_manager):
    """Failed refresh must not discard stored tokens before falling back."""
    oauth_manager.token_storage = SimpleNamespace(
        is_access_token_valid=MagicMock(return_value=False),
        get_refresh_token=MagicMock(return_value="refresh"),
        delete=MagicMock(),
    )
    oauth_manager._refresh_token = AsyncMock(side_effect=OAuth2Error("refresh failed"))
    oauth_manager.authenticate = AsyncMock()

    await oauth_manager.ensure_authenticated()

    oauth_manager.token_storage.delete.assert_not_called()
    oauth_manager.authenticate.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_authenticated_uses_token_refreshed_by_another_process(oauth_manager):
    """A token refreshed while waiting for the lock should be reused as is."""
    validity = iter([False, True])
    oauth_manager.token_storage = SimpleNamespace(
        is_access_token_valid=MagicMock(side_effect=lambda: next(validity)),
        get_refresh_token=MagicMock(return_value="refresh"),
        save=MagicMock(),
        delete=MagicMock(),
    )
    oauth_manager._refresh_token = AsyncMock()
    oauth_manager.authenticate = AsyncMock()

    await oauth_manager.ensure_authenticated()

    oauth_manager._refresh_token.assert_not_called()
    oauth_manager.authenticate.assert_not_called()
    oauth_manager.token_storage.delete.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_authenticated_raises_when_interactive_fallback_disabled(oauth_manager):
    """With the browser flow disabled the failure must be explicit."""
    oauth_manager.settings.oauth_interactive_fallback = False
    oauth_manager.token_storage = SimpleNamespace(
        is_access_token_valid=MagicMock(return_value=False),
        get_refresh_token=MagicMock(return_value="refresh"),
        delete=MagicMock(),
    )
    oauth_manager._refresh_token = AsyncMock(side_effect=OAuth2Error("refresh failed"))
    oauth_manager.authenticate = AsyncMock()

    with pytest.raises(OAuth2Error, match="OAUTH_INTERACTIVE_FALLBACK"):
        await oauth_manager.ensure_authenticated()

    oauth_manager.authenticate.assert_not_called()
    oauth_manager.token_storage.delete.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_lock_is_skipped_without_file_locking(tmp_path, monkeypatch):
    """Where flock is unavailable the refresh runs unserialised, not broken."""
    monkeypatch.setattr("worksection_mcp.auth.oauth2.fcntl", None)
    mgr = OAuth2Manager(build_settings(tmp_path))

    handle = await mgr._acquire_refresh_lock()

    assert handle is None
    await mgr._release_refresh_lock(handle)


@pytest.mark.asyncio
async def test_refresh_lock_is_exclusive_across_managers(tmp_path):
    """A second holder must block until the first one releases the lock."""
    first = OAuth2Manager(build_settings(tmp_path))
    second = OAuth2Manager(build_settings(tmp_path))

    held = await first._acquire_refresh_lock()
    try:
        with pytest.raises(OAuth2Error, match="Timed out waiting"):
            await second._acquire_refresh_lock(wait_seconds=0.3)
    finally:
        await first._release_refresh_lock(held)

    acquired = await asyncio.wait_for(second._acquire_refresh_lock(), timeout=5)
    await second._release_refresh_lock(acquired)


@pytest.mark.asyncio
async def test_refresh_token_surfaces_worksection_error_description(oauth_manager):
    """Worksection reports refresh errors as HTTP 200 plus errorDescription."""
    oauth_manager.token_storage = SimpleNamespace(
        get_refresh_token=MagicMock(return_value="refresh"),
    )
    http_client = AsyncMock()
    http_client.post = AsyncMock(
        return_value=httpx.Response(
            200, json={"errorDescription": "Cannot decrypt the refresh token"}
        )
    )
    oauth_manager._get_http_client = AsyncMock(return_value=http_client)  # type: ignore[method-assign]

    with pytest.raises(OAuth2Error, match="Cannot decrypt the refresh token"):
        await oauth_manager._refresh_token()


@pytest.mark.asyncio
async def test_get_valid_token_raises_when_no_token_available(oauth_manager):
    """get_valid_token should fail if token is still unavailable after ensure."""
    oauth_manager.ensure_authenticated = AsyncMock()
    oauth_manager.token_storage = SimpleNamespace(get_access_token=MagicMock(return_value=None))

    with pytest.raises(OAuth2Error, match="No access token available"):
        await oauth_manager.get_valid_token()


@pytest.mark.asyncio
async def test_get_user_info_success_and_failure(oauth_manager):
    """get_user_info should proxy successful responses and raise on failures."""
    oauth_manager.get_valid_token = AsyncMock(return_value="token")
    ok_http_client = AsyncMock()
    ok_http_client.post = AsyncMock(return_value=httpx.Response(200, json={"id": "u1"}))
    oauth_manager._get_http_client = AsyncMock(return_value=ok_http_client)  # type: ignore[method-assign]
    assert (await oauth_manager.get_user_info()) == {"id": "u1"}

    bad_http_client = AsyncMock()
    bad_http_client.post = AsyncMock(return_value=httpx.Response(401, text="unauthorized"))
    oauth_manager._get_http_client = AsyncMock(return_value=bad_http_client)  # type: ignore[method-assign]
    with pytest.raises(OAuth2Error, match="Failed to get user info"):
        await oauth_manager.get_user_info()


def test_has_tokens_and_clear_tokens(oauth_manager):
    """Token convenience helpers should proxy token storage behavior."""
    token_storage = SimpleNamespace(
        load=MagicMock(return_value={"access_token": "x"}), delete=MagicMock()
    )
    oauth_manager.token_storage = token_storage

    assert oauth_manager.has_tokens() is True
    oauth_manager.clear_tokens()
    token_storage.delete.assert_called_once()


@pytest.mark.asyncio
async def test_authenticate_runs_interactive_flow(monkeypatch, oauth_manager):
    """authenticate should start callback server, exchange code, and persist tokens."""
    oauth_manager.settings.oauth_callback_use_ssl = False
    oauth_manager.settings.oauth_auto_open_browser = True

    callback_server = SimpleNamespace(
        start=MagicMock(),
        stop=MagicMock(),
        wait_for_callback=AsyncMock(return_value=("code-1", "state-1")),
    )
    monkeypatch.setattr("worksection_mcp.auth.oauth2.CallbackServer", lambda **_: callback_server)
    monkeypatch.setattr("worksection_mcp.auth.oauth2.secrets.token_urlsafe", lambda _: "state-1")

    browser_calls: list[str] = []
    monkeypatch.setattr("worksection_mcp.auth.oauth2.webbrowser.open", browser_calls.append)

    oauth_manager._exchange_code = AsyncMock(
        return_value={"access_token": "x", "refresh_token": "y"}
    )
    oauth_manager.token_storage = SimpleNamespace(save=MagicMock())

    await oauth_manager.authenticate()

    callback_server.start.assert_called_once()
    callback_server.stop.assert_called_once()
    oauth_manager._exchange_code.assert_awaited_once_with("code-1")
    oauth_manager.token_storage.save.assert_called_once()
    assert len(browser_calls) == 1


@pytest.mark.asyncio
async def test_authenticate_rejects_state_mismatch(monkeypatch, oauth_manager):
    """State mismatch should raise OAuth2Error and still stop callback server."""
    oauth_manager.settings.oauth_callback_use_ssl = False
    callback_server = SimpleNamespace(
        start=MagicMock(),
        stop=MagicMock(),
        wait_for_callback=AsyncMock(return_value=("code-1", "wrong-state")),
    )
    monkeypatch.setattr("worksection_mcp.auth.oauth2.CallbackServer", lambda **_: callback_server)
    monkeypatch.setattr(
        "worksection_mcp.auth.oauth2.secrets.token_urlsafe", lambda _: "expected-state"
    )
    monkeypatch.setattr("worksection_mcp.auth.oauth2.webbrowser.open", lambda *_: None)

    with pytest.raises(OAuth2Error, match="State mismatch"):
        await oauth_manager.authenticate()

    callback_server.stop.assert_called_once()


@pytest.mark.asyncio
async def test_authenticate_ssl_path_invokes_ssl_helpers(monkeypatch, oauth_manager):
    """When SSL callback is enabled, SSL cert/context helpers should be used."""
    oauth_manager.settings.oauth_callback_use_ssl = True
    oauth_manager.settings.oauth_auto_open_browser = False

    callback_server = SimpleNamespace(
        start=MagicMock(),
        stop=MagicMock(),
        wait_for_callback=AsyncMock(return_value=("code-1", "state-1")),
    )
    monkeypatch.setattr("worksection_mcp.auth.oauth2.CallbackServer", lambda **_: callback_server)
    monkeypatch.setattr("worksection_mcp.auth.oauth2.secrets.token_urlsafe", lambda _: "state-1")
    monkeypatch.setattr("worksection_mcp.auth.oauth2.webbrowser.open", lambda *_: None)

    ssl_calls = {"ensure": 0, "context": 0}

    def fake_ensure(*_args, **_kwargs):
        ssl_calls["ensure"] += 1

    def fake_context(*_args, **_kwargs):
        ssl_calls["context"] += 1
        return object()

    monkeypatch.setattr("worksection_mcp.auth.ssl_utils.ensure_ssl_cert", fake_ensure)
    monkeypatch.setattr("worksection_mcp.auth.ssl_utils.create_ssl_context", fake_context)

    oauth_manager._exchange_code = AsyncMock(
        return_value={"access_token": "x", "refresh_token": "y"}
    )
    oauth_manager.token_storage = SimpleNamespace(save=MagicMock())

    await oauth_manager.authenticate()

    assert ssl_calls == {"ensure": 1, "context": 1}
