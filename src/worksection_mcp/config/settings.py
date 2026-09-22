"""Configuration management using Pydantic Settings."""

import socket
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_LARGE_RESPONSE_OFFLOAD_THRESHOLD_BYTES = 50_000
DEFAULT_LARGE_RESPONSE_MAX_READ_BYTES = 50_000


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # OAuth2 Configuration (Required)
    worksection_client_id: str = Field(
        ...,
        description="OAuth2 client ID from Worksection app settings",
    )
    worksection_client_secret: str = Field(
        ...,
        description="OAuth2 client secret from Worksection app settings",
    )
    worksection_account_url: str = Field(
        ...,
        description="Worksection account URL (e.g., https://company.worksection.com)",
    )
    worksection_redirect_uri: str = Field(
        default="https://localhost:8080/oauth/callback",
        description="OAuth2 redirect URI",
    )
    worksection_scopes: str = Field(
        default="projects_read,tasks_read,costs_read,tags_read,comments_read,files_read,users_read,contacts_read",
        description="Comma-separated OAuth2 scopes",
    )
    worksection_enable_writes: bool = Field(
        default=False,
        description=(
            "Master switch for mutating (write) tools. When False (default), all write "
            "tools refuse to run regardless of token scopes. Requires an OAuth token "
            "authorized with the relevant *_write scopes to actually take effect."
        ),
    )

    # OAuth2 Flow Settings
    oauth_callback_host: str = Field(
        default="localhost",
        description="Host for OAuth callback server",
    )
    oauth_callback_port: int = Field(
        default=8080,
        description="Port for OAuth callback server",
    )
    oauth_auto_open_browser: bool = Field(
        default=True,
        description="Automatically open browser for OAuth authorization",
    )
    oauth_interactive_fallback: bool = Field(
        default=True,
        description=(
            "Fall back to the interactive browser flow when no usable token is stored. "
            "Disable when the registered redirect URI is not a local callback, so startup "
            "fails fast instead of blocking on a flow that cannot complete."
        ),
    )

    # SSL Configuration for OAuth Callback
    oauth_callback_use_ssl: bool = Field(
        default=True,
        description="Use HTTPS for OAuth callback server",
    )
    oauth_ssl_cert_path: Path = Field(
        default=Path("./data/certs/callback.crt"),
        description="Path to SSL certificate file",
    )
    oauth_ssl_key_path: Path = Field(
        default=Path("./data/certs/callback.key"),
        description="Path to SSL private key file",
    )
    oauth_ssl_cert_days: int = Field(
        default=365,
        description="Certificate validity in days for auto-generated certs",
    )

    # Token Management
    token_storage_path: Path = Field(
        default=Path("./data/tokens"),
        description="Directory for storing encrypted tokens",
    )
    token_encryption_key: str = Field(
        default="",
        description="Encryption key for tokens (auto-generated if empty)",
    )

    # File Caching
    file_cache_path: Path = Field(
        default=Path("./data/files"),
        description="Directory for cached file attachments",
    )
    file_cache_retention_hours: int = Field(
        default=24,
        description="How long to keep cached files (hours)",
    )
    max_file_size_mb: int = Field(
        default=10,
        description="Maximum file size to cache (MB)",
    )

    # Large Response Handling
    large_response_offload_enabled: bool = Field(
        default=True,
        description="Enable automatic offloading of oversized MCP tool responses.",
    )
    large_response_offload_path: Path = Field(
        default=Path("./data/offload"),
        description="Directory for oversized MCP tool response files.",
    )
    large_response_offload_threshold_bytes: int = Field(
        default=DEFAULT_LARGE_RESPONSE_OFFLOAD_THRESHOLD_BYTES,
        description="Serialized response size in bytes above which responses are offloaded. 0 disables offloading.",
    )
    large_response_offload_retention_hours: int = Field(
        default=24,
        description="How long to keep offloaded response files.",
    )
    large_response_offload_max_files: int = Field(
        default=100,
        description="Maximum number of offloaded response files to retain.",
    )
    large_response_offload_include_file_path: bool = Field(
        default=False,
        description="Include local file_path in offload metadata.",
    )
    large_response_max_read_bytes: int = Field(
        default=DEFAULT_LARGE_RESPONSE_MAX_READ_BYTES,
        description="Maximum bytes returned by offloaded response read helper tools.",
    )

    # MCP Server Configuration
    mcp_server_name: str = Field(
        default="worksection",
        description="Server name used in MCP protocol",
    )
    mcp_server_host: str = Field(
        default="127.0.0.1",
        description="Server host for HTTP transports (0.0.0.0 for LAN access, 127.0.0.1 for local only)",
    )
    mcp_server_port: int = Field(
        default=8000,
        description="Server port for HTTP transports",
    )
    mcp_transport: Literal["streamable-http", "stdio"] = Field(
        default="streamable-http",
        description="MCP transport type",
    )

    # Runtime Configuration
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )
    log_use_colors: bool = Field(
        default=True,
        description="Enable ANSI colors for log level names when output is a TTY",
    )
    request_log_mode: Literal["INFO", "DEBUG", "OFF"] = Field(
        default="INFO",
        description="Verbosity for request/access logs from Uvicorn and httpx",
    )
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Runtime environment",
    )

    @field_validator("worksection_account_url")
    @classmethod
    def validate_account_url(cls, v: str) -> str:
        """Validate account URL format and structure."""
        if not v:
            raise ValueError(
                "WORKSECTION_ACCOUNT_URL is required. "
                "Set it in your .env file (e.g., https://yourcompany.worksection.com)"
            )

        # Remove trailing slash
        v = v.rstrip("/")

        # Parse URL
        try:
            parsed = urlparse(v)
        except Exception as e:
            raise ValueError(
                f"Invalid URL format for WORKSECTION_ACCOUNT_URL: {v}\n"
                f"Error: {e}\n"
                f"Expected format: https://yourcompany.worksection.com"
            ) from e

        # Validate scheme
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"Invalid URL scheme in WORKSECTION_ACCOUNT_URL: {parsed.scheme}\n"
                f"Expected 'https' (or 'http' for testing)\n"
                f"Provided: {v}"
            )

        # Validate hostname exists
        if not parsed.netloc:
            raise ValueError(
                f"Missing hostname in WORKSECTION_ACCOUNT_URL: {v}\n"
                f"Expected format: https://yourcompany.worksection.com"
            )

        # Extract hostname (remove port if present)
        hostname = parsed.hostname
        if not hostname:
            raise ValueError(
                f"Could not extract hostname from WORKSECTION_ACCOUNT_URL: {v}\n"
                f"Expected format: https://yourcompany.worksection.com"
            )

        return v

    @field_validator("request_log_mode", mode="before")
    @classmethod
    def normalize_request_log_mode(cls, v):
        """Normalize request log mode to uppercase for env compatibility."""
        if isinstance(v, str):
            return v.upper()
        return v

    @field_validator(
        "token_storage_path",
        "file_cache_path",
        "large_response_offload_path",
        "oauth_ssl_cert_path",
        "oauth_ssl_key_path",
        mode="before",
    )
    @classmethod
    def ensure_path(cls, v):
        """Convert string to Path."""
        return Path(v) if isinstance(v, str) else v

    @field_validator("worksection_client_id", "worksection_client_secret")
    @classmethod
    def validate_credentials(cls, v: str, info) -> str:
        """Validate OAuth2 credentials format."""
        field_name = info.field_name
        if not v or not v.strip():
            raise ValueError(
                f"{field_name.upper()} is required. "
                f"Set it in your .env file from your Worksection OAuth2 app settings."
            )

        # Minimum length check
        min_length = 8 if "id" in field_name else 16
        if len(v) < min_length:
            raise ValueError(
                f"{field_name.upper()} seems too short (minimum {min_length} characters). "
                f"Please check your Worksection OAuth2 app settings."
            )

        return v.strip()

    @field_validator("worksection_redirect_uri")
    @classmethod
    def validate_redirect_uri(cls, v: str) -> str:
        """Validate OAuth2 redirect URI."""
        if not v:
            raise ValueError("WORKSECTION_REDIRECT_URI is required")

        parsed = urlparse(v)

        # Worksection requires HTTPS (except localhost)
        if parsed.scheme != "https" and parsed.hostname != "localhost":
            raise ValueError(
                f"Worksection requires HTTPS for redirect URIs.\n"
                f"Current: {v}\n"
                f"Expected: https://... (or https://localhost:... for local development)"
            )

        if not parsed.netloc:
            raise ValueError(
                f"Invalid redirect URI format: {v}\n"
                f"Expected format: https://localhost:8080/oauth/callback"
            )

        return v

    @field_validator("oauth_callback_port", "mcp_server_port")
    @classmethod
    def validate_port(cls, v: int, info) -> int:
        """Validate port numbers."""
        if not (1 <= v <= 65535):
            raise ValueError(f"{info.field_name} must be between 1 and 65535. Current: {v}")
        return v

    @field_validator("max_file_size_mb", "file_cache_retention_hours")
    @classmethod
    def validate_positive(cls, v: int, info) -> int:
        """Validate positive integers."""
        if v <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0. Current: {v}")
        return v

    @field_validator(
        "large_response_offload_retention_hours",
        "large_response_offload_max_files",
    )
    @classmethod
    def validate_large_response_positive(cls, v: int, info) -> int:
        """Validate positive large-response settings."""
        if v <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0. Current: {v}")
        return v

    @field_validator("large_response_max_read_bytes")
    @classmethod
    def validate_large_response_max_read_bytes(cls, v: int, info) -> int:
        """Validate read chunks can always advance across UTF-8 characters."""
        if v < 4:
            raise ValueError(f"{info.field_name} must be greater than or equal to 4. Current: {v}")
        return v

    @field_validator("large_response_offload_threshold_bytes")
    @classmethod
    def validate_large_response_threshold(cls, v: int, info) -> int:
        """Validate non-negative large-response threshold."""
        if v < 0:
            raise ValueError(f"{info.field_name} must be greater than or equal to 0. Current: {v}")
        return v

    @field_validator("worksection_scopes")
    @classmethod
    def validate_scopes(cls, v: str) -> str:
        """Validate OAuth2 scopes."""
        if not v or not v.strip():
            raise ValueError(
                "WORKSECTION_SCOPES is required. "
                "Set comma-separated scopes (e.g., 'projects_read,tasks_read')"
            )

        # Parse scopes
        scopes = [s.strip() for s in v.split(",") if s.strip()]

        if not scopes:
            raise ValueError("At least one OAuth2 scope is required")

        # Valid scopes (read + write). Write scopes only take effect when
        # WORKSECTION_ENABLE_WRITES=true; this set merely rejects typos.
        valid_scopes = {
            "projects_read",
            "tasks_read",
            "costs_read",
            "tags_read",
            "comments_read",
            "files_read",
            "users_read",
            "contacts_read",
            "projects_write",
            "tasks_write",
            "costs_write",
            "tags_write",
            "comments_write",
            "files_write",
            "users_write",
            "contacts_write",
            "administrative",
        }

        invalid = [s for s in scopes if s not in valid_scopes]
        if invalid:
            raise ValueError(
                f"Invalid scopes: {', '.join(invalid)}\n"
                f"Valid scopes: {', '.join(sorted(valid_scopes))}"
            )

        return v

    @model_validator(mode="after")
    def validate_ssl_consistency(self) -> Settings:
        """Validate SSL configuration consistency."""
        # If SSL is enabled, redirect URI should use HTTPS
        if self.oauth_callback_use_ssl:
            parsed = urlparse(self.worksection_redirect_uri)
            if parsed.scheme != "https":
                raise ValueError(
                    "When OAUTH_CALLBACK_USE_SSL=true, WORKSECTION_REDIRECT_URI must use HTTPS.\n"
                    f"Current redirect URI: {self.worksection_redirect_uri}\n"
                    "Either set OAUTH_CALLBACK_USE_SSL=false or use https:// in redirect URI"
                )

        return self

    @property
    def scopes_list(self) -> list[str]:
        """Return scopes as a list."""
        return [s.strip() for s in self.worksection_scopes.split(",")]

    @property
    def oauth2_base_url(self) -> str:
        """Return the OAuth2 base URL."""
        return "https://worksection.com"

    @property
    def api_base_url(self) -> str:
        """Return the API base URL for the account."""
        return f"{self.worksection_account_url}/api/oauth2"

    @property
    def max_file_size_bytes(self) -> int:
        """Return max file size in bytes."""
        return self.max_file_size_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        """Create required directories if they don't exist."""
        self.token_storage_path.mkdir(parents=True, exist_ok=True)
        self.file_cache_path.mkdir(parents=True, exist_ok=True)
        if self.large_response_offload_enabled:
            self.large_response_offload_path.mkdir(parents=True, exist_ok=True)
        # Create SSL certificates directory
        self.oauth_ssl_cert_path.parent.mkdir(parents=True, exist_ok=True)

    def validate_external_resources(self) -> dict[str, str]:
        """Validate external resources (DNS, filesystem, etc.).

        Pydantic validators handle field-level validation.
        This method checks external dependencies that Pydantic can't validate.

        Returns:
            Dictionary with validation results
        """
        results = {}

        # DNS resolution check for account URL
        hostname: str | None = None
        try:
            parsed = urlparse(self.worksection_account_url)
            hostname = parsed.hostname
            if hostname:
                socket.getaddrinfo(hostname, None)
                results["dns_resolution"] = f"✓ Can resolve {hostname}"
            else:
                results["dns_resolution"] = "✗ No hostname found in account URL"
        except socket.gaierror as e:
            results["dns_resolution"] = f"✗ Cannot resolve {hostname}: {e}"
        except Exception as e:
            results["dns_resolution"] = f"✗ DNS check failed: {e}"

        # Check directory write permissions
        try:
            self.token_storage_path.mkdir(parents=True, exist_ok=True)
            test_file = self.token_storage_path / ".write_test"
            test_file.touch()
            test_file.unlink()
            results["token_storage_writable"] = f"✓ {self.token_storage_path} is writable"
        except Exception as e:
            results["token_storage_writable"] = f"✗ Cannot write to {self.token_storage_path}: {e}"

        try:
            self.file_cache_path.mkdir(parents=True, exist_ok=True)
            test_file = self.file_cache_path / ".write_test"
            test_file.touch()
            test_file.unlink()
            results["file_cache_writable"] = f"✓ {self.file_cache_path} is writable"
        except Exception as e:
            results["file_cache_writable"] = f"✗ Cannot write to {self.file_cache_path}: {e}"

        # Check SSL cert directory
        try:
            self.oauth_ssl_cert_path.parent.mkdir(parents=True, exist_ok=True)
            results["ssl_cert_dir"] = "✓ SSL cert directory accessible"
        except Exception as e:
            results["ssl_cert_dir"] = f"✗ Cannot create SSL cert directory: {e}"

        return results


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()  # pyright: ignore[reportCallIssue]
