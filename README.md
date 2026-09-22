# Worksection MCP Server

[![CI](https://github.com/pbv7/worksection-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/pbv7/worksection-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/pbv7/worksection-mcp/graph/badge.svg)](https://codecov.io/gh/pbv7/worksection-mcp)

> ⚠️ **Unofficial project.** Not affiliated with, endorsed by, or supported by
> Worksection. "Worksection" is used solely to identify the third-party API
> this project integrates with. See [Disclaimer](#disclaimer) for details.

A multi-tenant MCP (Model Context Protocol) server for the
[Worksection](https://worksection.com) project management platform,
built with [FastMCP](https://github.com/jlowin/fastmcp).

Provides **comprehensive read-only tools** for data access,
enabling AI assistants like Claude to generate reports, analyze project data,
and process image attachments.

> 🔀 **Fork note.** This is a fork of
> [pbv7/worksection-mcp](https://github.com/pbv7/worksection-mcp) that adds
> **opt-in write operations** on top of the upstream read-only server:
> `add_comment`, `create_task`, `update_task`, `complete_task`, `reopen_task`,
> `set_task_status` and `log_time`. Writes are **disabled by default** — they
> require `WORKSECTION_ENABLE_WRITES=true` **and** an OAuth token authorized
> with the relevant `*_write` scopes (`tasks_write`, `comments_write`,
> `tags_write` for status labels, `costs_write` for logged time). With the flag off, behavior is identical to upstream.
> See [Write Operations](#write-operations-opt-in).

## Features

- **Multi-tenant** - Configurable for any Worksection account
- **OAuth2 Authentication** - Secure authorization code flow with automatic
  token refresh
- **Comprehensive Read-only Tools** - Projects, tasks, comments, time tracking,
  users, and more
- **Image Analysis** - MCP resources for Claude vision to analyze screenshots
  and attachments
- **Rate Limiting** - Built-in 1 req/sec throttling per Worksection API limits
- **File Caching** - Local cache for downloaded attachments
- **Large Response Offloading** - Oversized tool responses are offloaded to disk; clients read them back in bounded chunks via helper tools
- **Production Ready** - Docker containerization with multi-stage builds
- **Extensible** - Clean architecture for adding custom tools

## Quick Start

### Prerequisites

- Python 3.14+
- [uv](https://github.com/astral-sh/uv) package manager
- Worksection account with OAuth2 app credentials

### Installation

```bash
# Clone the repository
git clone https://github.com/pbv7/worksection-mcp.git
cd worksection-mcp

# Install dependencies with uv (always use --frozen to respect lockfile)
uv sync --frozen --extra dev

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
# Then validate your configuration
uv run python scripts/validate_config.py

# Restrict permissions on the data directory (tokens, keys, certs)
mkdir -p data && chmod 700 data
```

### Configuration

Edit `.env` with your Worksection OAuth2 credentials:

```bash
# Required
WORKSECTION_CLIENT_ID=your_client_id
WORKSECTION_CLIENT_SECRET=your_client_secret
WORKSECTION_ACCOUNT_URL=https://yourcompany.worksection.com

# Optional (defaults shown)
WORKSECTION_REDIRECT_URI=https://localhost:8080/oauth/callback
MCP_SERVER_HOST=127.0.0.1
MCP_SERVER_PORT=8000
MCP_TRANSPORT=streamable-http
LOG_LEVEL=INFO
LOG_USE_COLORS=true
REQUEST_LOG_MODE=INFO
FASTMCP_SHOW_SERVER_BANNER=false
```

### Running the Server

```bash
# Development
uv run python -m worksection_mcp

# Or using the entry point
uv run worksection-mcp
```

On first run, the server will:

1. Open your browser for OAuth2 authorization
2. After you authorize, it will save encrypted tokens
3. Start the MCP server on port 8000

### Docker Deployment

```bash
# Build the image
docker build -t worksection-mcp .

# Run with environment file
docker run -d \
  --name worksection-mcp \
  -p 8000:8000 \
  -e MCP_SERVER_HOST=0.0.0.0 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  worksection-mcp

# Or use docker-compose
docker compose up -d
```

## OAuth2 Setup

### Creating a Worksection OAuth2 App

1. Go to your Worksection account settings
2. Navigate to API / Integrations
3. Create a new OAuth2 application
4. Set the redirect URI to `https://localhost:8080/oauth/callback`
   (HTTPS required)
5. Note your `client_id` and `client_secret`
6. Enable required read scopes: Projects, Tasks, Costs, Tags,
   Comments, Files, People, Contacts

### HTTPS for OAuth Callback

Worksection requires HTTPS for OAuth2 redirect URIs. This server automatically
generates a self-signed SSL certificate on first run.

**What to expect:**

- Certificates are auto-generated and stored in `./data/certs/`
- Your browser will show "Your connection is not private" warning
- Click "Advanced" → "Proceed to localhost (unsafe)" to continue
- This is expected for self-signed certificates in local development

**Using custom certificates:**

```bash
# Set paths to your certificates in .env
OAUTH_SSL_CERT_PATH=/path/to/your/cert.crt
OAUTH_SSL_KEY_PATH=/path/to/your/key.key
```

**Disable SSL (not recommended):**

```bash
# Only if you have an alternative HTTPS solution (e.g., ngrok)
OAUTH_CALLBACK_USE_SSL=false
```

### Authentication Flow

```text
First Run (no tokens):
1. Server starts callback listener on port 8080
2. Opens browser → Worksection authorization page
3. User grants permissions
4. Callback receives authorization code
5. Server exchanges code for access + refresh tokens
6. Tokens encrypted and saved locally
7. MCP server starts

Subsequent Runs:
1. Load encrypted tokens from storage
2. If access token expired → auto-refresh
3. If refresh token expired → re-authenticate via browser
4. MCP server starts
```

## Available Tools

### Projects

| Tool | Description |
| ------ | ------------- |
| `get_projects` | List all projects with optional filtering |
| `get_project` | Get single project details |
| `get_project_groups` | Get project folders/groups |
| `get_project_team` | Get team members assigned to project |

### Tasks

| Tool | Description |
| ------ | ------------- |
| `get_all_tasks` | Get all tasks across projects |
| `get_tasks` | Get tasks for a specific project |
| `get_task` | Get single task details |
| `search_tasks` | Search tasks by query or filter expression |
| `get_task_subtasks` | Get subtasks of a task |
| `get_task_relations` | Get related/dependent tasks |
| `get_task_subscribers` | Get task watchers |

### Comments

| Tool | Description |
| ------ | ------------- |
| `get_comments` | Get comments for a task |
| `get_task_discussion` | Get full discussion thread with comments and files |

### Files

| Tool | Description |
| ------ | ------------- |
| `get_task_files` | Get files attached to task |
| `get_all_task_attachments` | Get all attachments from task and comments |
| `get_project_files` | List all files in a project or task |
| `download_file` | Download and cache a file |
| `get_file_as_base64` | Download file as base64 encoded string |
| `get_file_content` | Extract text content from files |
| `list_image_attachments` | List image files for a task or project |

### Costs & Timers

| Tool | Description |
| ------ | ------------- |
| `get_costs` | Get time/cost records |
| `get_costs_total` | Get aggregated costs |
| `get_user_workload` | Get user's time entries |
| `get_project_time_report` | Get project time report |
| `get_timers` | Get all currently running timers |
| `get_my_timer` | Get current user's running timer |

### Users & Teams

| Tool | Description |
| ------ | ------------- |
| `get_users` | Get all account users |
| `get_user` | Get single user details |
| `get_current_user` | Get current authenticated user |
| `get_user_groups` | Get teams/departments |
| `get_contacts` | Get contact database |
| `get_contact_groups` | List contact folders |
| `get_user_assignments` | Get tasks assigned to user |

### Tags

| Tool | Description |
| ------ | ------------- |
| `get_task_tags` | Get available task tags (labels/statuses) |
| `get_task_tag_groups` | Get task tag groups |
| `get_project_tags` | Get available project tags |
| `get_project_tag_groups` | Get project tag groups |
| `get_task_with_tags` | Get a task with its assigned tags |
| `search_tasks_by_tag` | Find tasks with a specific tag |

### Analytics

| Tool | Description |
| ------ | ------------- |
| `get_project_stats` | Get project statistics |
| `get_overdue_tasks` | Get overdue tasks |
| `get_tasks_by_status` | Filter tasks by status |
| `get_tasks_by_priority` | Filter tasks by priority |
| `get_team_workload_summary` | Get team workload overview |

### Activity

| Tool | Description |
| ------ | ------------- |
| `get_activity_log` | Get activity/event log with auto-size truncation and event type breakdown |
| `get_user_activity` | Get user's activity with auto-size truncation |

Activity tools default to returning as many events as fit under MCP's 1MB response
limit (with ~150KB safety margin, no fixed default cap). Set `max_results` explicitly to control truncation.
Truncation metadata (`total_count`, `returned_count`, `truncated`, `truncation_reason`)
is always included.

### System

| Tool | Description |
| ------ | ------------- |
| `health_check` | Check server health and API status |
| `get_webhooks` | List configured webhooks (requires `administrative` scope) |

### Large Response Helpers

When a tool response exceeds `LARGE_RESPONSE_OFFLOAD_THRESHOLD_BYTES`, it is offloaded to disk and
replaced with a compact envelope. Use these tools to inspect and read the offloaded content:

| Tool | Description |
| ------ | ------------- |
| `get_offloaded_response_info` | Inspect metadata (size, SHA-256, MIME type) for an offloaded response |
| `read_offloaded_response_text` | Read offloaded text/JSON content in bounded UTF-8-safe chunks (`offset` + `max_bytes`) |

## Write Operations (opt-in)

> **Fork addition.** Not part of upstream `pbv7/worksection-mcp`.

These tools **modify live Worksection data**. They are **disabled by default**
and only run when **both** conditions hold:

1. `WORKSECTION_ENABLE_WRITES=true` is set in the environment, and
2. the OAuth token carries the relevant `*_write` scope (enforced by Worksection).

With the flag off, every write tool returns a `writes_disabled` refusal and the
server behaves exactly like upstream. Each successful write emits a `WRITE …`
audit line to the logs.

| Tool | Description | Required scope |
| ------ | ------------- | ---------------- |
| `add_comment` | Post a comment on a task | `comments_write` |
| `create_task` | Create a task or subtask in a project | `tasks_write` |
| `update_task` | Edit an existing task (title, assignee, priority, dates, estimates) | `tasks_write` |
| `complete_task` | Mark a task done | `tasks_write` |
| `reopen_task` | Reopen a completed task | `tasks_write` |
| `set_task_status` | Add/remove status or label tags on a task | `tags_write` |
| `log_time` | Log time against a task, optionally on an earlier date | `costs_write` |

### Enabling writes

1. Add the write scopes you need to your Worksection OAuth2 app (in Worksection
   admin), e.g. `tasks_write`, `comments_write` (+ `tags_write` for
   `set_task_status`, `costs_write` for `log_time`).
2. Add those scopes to `WORKSECTION_SCOPES` in `.env` and set
   `WORKSECTION_ENABLE_WRITES=true`.
3. Re-authenticate so the new token carries the write scopes (delete
   `data/tokens/tokens.enc`, restart, and complete the OAuth flow).

## MCP Resources

Resources allow Claude to directly access and analyze files:

| Resource URI | Description |
| -------------- | ------------- |
| `worksection://file/{file_id}` | Access file for vision analysis |
| `worksection://task/{task_id}/context` | Get full task context with attachments |
| `worksection://cache/stats` | Get file cache statistics |
| `worksection://offload/{response_id}` | Preview an offloaded large tool response |

### Using Resources for Image Analysis

```python
# In your MCP client or skill:
# 1. Get task discussion with files
discussion = await get_task_discussion(task_id="12345")

# 2. For each image file, access via resource
for file in discussion.get("images", []):
    # Claude can read this resource and analyze the image
    image_content = await read_resource(file["resource_uri"])
```

## Configuration Reference

| Variable | Description | Default |
| ---------- | ------------- | --------- |
| `WORKSECTION_CLIENT_ID` | OAuth2 client ID | Required |
| `WORKSECTION_CLIENT_SECRET` | OAuth2 client secret | Required |
| `WORKSECTION_ACCOUNT_URL` | Your Worksection URL | Required |
| `WORKSECTION_REDIRECT_URI` | OAuth callback URL | `https://localhost:8080/oauth/callback` |
| `WORKSECTION_SCOPES` | OAuth2 scopes | `projects_read,tasks_read,...` |
| `OAUTH_CALLBACK_HOST` | Callback server host | `localhost` |
| `OAUTH_CALLBACK_PORT` | Callback server port | `8080` |
| `OAUTH_AUTO_OPEN_BROWSER` | Auto-open browser | `true` |
| `OAUTH_CALLBACK_USE_SSL` | Use HTTPS for callback | `true` |
| `OAUTH_SSL_CERT_PATH` | SSL certificate path | `./data/certs/callback.crt` |
| `OAUTH_SSL_KEY_PATH` | SSL private key path | `./data/certs/callback.key` |
| `OAUTH_SSL_CERT_DAYS` | Certificate validity (days) | `365` |
| `TOKEN_STORAGE_PATH` | Token storage directory | `./data/tokens` |
| `TOKEN_ENCRYPTION_KEY` | Encryption key (auto-generated) | |
| `FILE_CACHE_PATH` | File cache directory | `./data/files` |
| `FILE_CACHE_RETENTION_HOURS` | Cache retention | `24` |
| `MAX_FILE_SIZE_MB` | Max cached file size | `10` |
| `LARGE_RESPONSE_OFFLOAD_ENABLED` | Offload oversized MCP tool responses | `true` |
| `LARGE_RESPONSE_OFFLOAD_PATH` | Offloaded response directory | `./data/offload` |
| `LARGE_RESPONSE_OFFLOAD_THRESHOLD_BYTES` | Serialized response size above which responses are offloaded (`0` disables) | `50000` |
| `LARGE_RESPONSE_OFFLOAD_RETENTION_HOURS` | Offloaded response retention | `24` |
| `LARGE_RESPONSE_OFFLOAD_MAX_FILES` | Max offloaded response files to retain | `100` |
| `LARGE_RESPONSE_OFFLOAD_INCLUDE_FILE_PATH` | Include local file path in offload metadata | `false` |
| `LARGE_RESPONSE_MAX_READ_BYTES` | Max raw bytes requested by offload read helper tools (minimum `4`) | `50000` |
| `MCP_SERVER_NAME` | Server name | `worksection` |
| `MCP_SERVER_HOST` | HTTP bind host (`127.0.0.1` local only, `0.0.0.0` LAN) | `127.0.0.1` |
| `MCP_SERVER_PORT` | Server port | `8000` |
| `MCP_TRANSPORT` | Transport type (`streamable-http`/`stdio`) | `streamable-http` |
| `LOG_LEVEL` | Global logging level for app/server components | `INFO` |
| `LOG_USE_COLORS` | Colorize log levels when output is a TTY | `true` |
| `REQUEST_LOG_MODE` | Request/access log verbosity (`INFO`/`DEBUG`/`OFF`) for `uvicorn.access` and `httpx` | `INFO` |
| `FASTMCP_SHOW_SERVER_BANNER` | Show FastMCP startup banner in logs | `true` |
| `ENVIRONMENT` | Environment name | `development` |

## Testing

### Automated Testing (Recommended)

Test all MCP tools automatically:

```bash
# Use first available project
uv run python tests/test_all_mcp_tools.py

# Specify project name
uv run python tests/test_all_mcp_tools.py --project "My Project"
```

This comprehensive test script:

- ✅ Tests all registered MCP tools
- ✅ Configurable project selection (via CLI argument or environment variable)
- ✅ Automatically extracts test IDs from your project data
- ✅ Provides detailed pass/fail results
- ✅ Handles rate limiting automatically

See **[TESTING.md](TESTING.md)** for complete documentation and configuration options.

To verify large response offloading against a real Worksection account:

```bash
uv run python tests/live_large_response_offload_roundtrip.py -v
```

### Manual Testing with MCP Inspector

For interactive testing:

```bash
# Start your MCP server
uv run worksection-mcp

# In another terminal, start the MCP Inspector
npx @modelcontextprotocol/inspector http://localhost:8000/mcp
```

## Development

### Setup Development Environment

```bash
# Install with dev dependencies (use --frozen, never uv pip install)
uv sync --frozen --extra dev

# Run tests
make test-fast

# Run with coverage
make test

# Plain `uv run pytest` uses the same no-coverage mode as `make test-fast`.
# Use `make test` or `make check` when you need coverage output.

# Lint code
make lint

# Lint all Markdown from repo root
make lint-docs

# Auto-fix all Markdown from repo root
npx markdownlint-cli2 --fix

# Type check
make typecheck

# Run the full CI-like check
make check
```

### Project Structure

```text
worksection-mcp/
├── src/
│   └── worksection_mcp/
│       ├── __init__.py          # Package init
│       ├── __main__.py          # Entry point
│       ├── server.py            # FastMCP server
│       ├── config/              # Configuration
│       ├── auth/                # OAuth2 authentication
│       ├── client/              # API client
│       ├── tools/               # MCP tools
│       ├── resources/           # MCP resources
│       ├── cache/               # File and session caching
│       ├── large_response.py    # Large tool response offloading
│       └── utils/               # Date formatting, response helpers
├── tests/                       # Test suite
├── data/                        # Runtime data (gitignored)
├── Dockerfile                   # Container build
├── docker-compose.yml           # Local development
└── docker-compose.prod.yml      # Production deployment
```

## Deployment

### Docker Production

```bash
# Build production image
docker build -t worksection-mcp:latest .

# Run with production compose
docker compose -f docker-compose.prod.yml up -d
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worksection-mcp
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: worksection-mcp
        image: worksection-mcp:latest
        ports:
        - containerPort: 8000
        env:
        - name: WORKSECTION_CLIENT_ID
          valueFrom:
            secretKeyRef:
              name: worksection-secrets
              key: client_id
        - name: WORKSECTION_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: worksection-secrets
              key: client_secret
        volumeMounts:
        - name: data
          mountPath: /app/data
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: worksection-mcp-data
```

### Pre-authentication for Containers

Since OAuth2 requires browser interaction, authenticate locally first:

```bash
# 1. Run locally to authenticate
uv run python -m worksection_mcp

# 2. After authentication, tokens are saved to ./data/tokens/

# 3. Mount this directory in your container
docker run -v ./data:/app/data worksection-mcp
```

## Troubleshooting

### Configuration Validation

Before troubleshooting, validate your complete configuration:

```bash
uv run python scripts/validate_config.py
```

The validator performs comprehensive checks in 3 steps:

**Step 1: Pydantic Validation** (automatic when loading .env)

- OAuth2 credentials format and length
- URL format and structure
- Redirect URI HTTPS requirement
- Valid OAuth2 scope names
- Port number ranges (1-65535)
- Positive values for file sizes and retention
- SSL configuration consistency

#### Step 2: Configuration Summary

- Shows all loaded settings
- Displays derived values (API URLs)
- Includes logging controls (`LOG_LEVEL`, `LOG_USE_COLORS`, `REQUEST_LOG_MODE`)
- Helps verify environment variables are set correctly

#### Step 3: External Resource Checks

- DNS resolution for account URL
- Directory write permissions (tokens, cache, certs)
- Filesystem accessibility

If validation passes, your configuration is complete and the server will start successfully.

### OAuth2 Issues

#### "Invalid redirect URI"

- Ensure your registered redirect URI in Worksection matches exactly
- Default: `https://localhost:8080/oauth/callback`
- Worksection requires HTTPS - do not use `http://`

#### "Your connection is not private" browser warning

- This is expected with self-signed certificates
- Click "Advanced" → "Proceed to localhost (unsafe)" to continue
- The warning only appears during OAuth authorization

#### "Refresh token expired"

- Delete `./data/tokens/tokens.enc` and re-authenticate

#### SSL certificate issues

- Delete `./data/certs/` directory to regenerate certificates
- Ensure you have write permissions to the data directory

### Configuration & Connection Issues

#### "Cannot resolve hostname" or "nodename nor servname provided, or not known"

This DNS resolution error means the Worksection account URL cannot be resolved:

**Check your configuration:**

```bash
# Run validation to diagnose
uv run python scripts/validate_config.py
```

**Common causes:**

- Typo in `WORKSECTION_ACCOUNT_URL` in your `.env` file
- Missing or incorrect domain name (should be `https://yourcompany.worksection.com`)
- No internet connectivity
- Corporate firewall blocking DNS

**Fix:**

1. Verify the URL in your `.env` matches your actual Worksection account
2. Test DNS resolution: `nslookup yourcompany.worksection.com`
3. Check internet connectivity
4. Try alternative DNS servers (8.8.8.8, 1.1.1.1)

**Note:** With the new validation, this error is caught at startup with a clear message instead of during runtime.

#### "Validation errors" on startup

The server now validates all configuration at startup using Pydantic. If you see validation errors:

1. Check the error message - it tells you exactly what's wrong
2. Refer to `.env.example` for correct format
3. Common issues:
   - Client ID/Secret too short (minimum 8/16 characters)
   - Invalid redirect URI (must be HTTPS, except localhost)
   - Invalid scopes (see list in `.env.example`)
   - Port numbers out of range (1-65535)

### Rate Limiting

#### "429 Too Many Requests"

- The server automatically backs off and retries
- Worksection API limit: 1 request/second

### File Cache

#### "File too large"

- Increase `MAX_FILE_SIZE_MB` environment variable
- Default limit: 10MB

### API Constraints & Limitations

#### Worksection API Design

##### No Pagination Support

Most Worksection API endpoints return complete datasets without pagination:

- `get_users` - Returns ALL users in a single call
- `get_events` - Returns ALL events for the specified period
- `get_projects` - Returns ALL projects
- `get_all_tasks` - Returns ALL tasks across all projects
- `get_tasks` - Returns ALL tasks for a project
- `get_project_groups` - Returns ALL project folders

**Impact**: For large datasets, responses can exceed MCP's 1MB limit.

**Solution**: The server uses two response-size controls:

- Central large-response offloading stores oversized tool results under
  `LARGE_RESPONSE_OFFLOAD_PATH` and returns a compact metadata envelope with an
  offload ID.
- `get_offloaded_response_info` and `read_offloaded_response_text` let clients
  inspect and read offloaded responses in bounded chunks.
- Local `file_path` values are hidden by default; use `resource_uri` and helper
  tools unless the MCP client runs with trusted local filesystem access.
- The default 50 KB offload threshold and 50 KB read limit leave room for JSON
  envelope and escaping overhead in MCP clients with strict inline response
  limits.
- Chunk reads may return fewer raw bytes than requested when JSON escaping would
  otherwise make the serialized helper-tool response too large.
- Offloaded files are cleaned on startup and before due future offloads, using
  `LARGE_RESPONSE_OFFLOAD_RETENTION_HOURS` and `LARGE_RESPONSE_OFFLOAD_MAX_FILES`.
- Deployments whose MCP clients accept larger inline responses can raise
  `LARGE_RESPONSE_OFFLOAD_THRESHOLD_BYTES` or `LARGE_RESPONSE_MAX_READ_BYTES`,
  trading fewer offload/read calls for higher context and client-limit risk.
- Selected high-volume tools still apply endpoint-specific truncation:
  `get_activity_log`, `get_user_activity`, `search_tasks`, and `get_comments`.

Truncated responses include metadata: `total_count`, `returned_count`, `truncated`,
`truncation_reason`.

For a comprehensive list of API limitations and workarounds, see
**[docs/API-LIMITATIONS.md](docs/API-LIMITATIONS.md)**.

For a client-facing summary of practical coverage, constraints, and expected
`PASS`/`PARTIAL` semantics, see
**[docs/CLIENT-CAPABILITIES.md](docs/CLIENT-CAPABILITIES.md)**.

##### Elevated Scope Requirements

Some endpoints require the `administrative` scope:

- `get_webhooks` - Webhook management
- Other administrative operations

Add `administrative` to `WORKSECTION_SCOPES` in `.env` to enable these tools.

#### MCP Protocol Constraints

##### Response Size Limit: 1MB

Error: `"Tool result is too large. Maximum size is 1MB."`

The Model Context Protocol enforces a 1MB maximum response size. This server handles
oversized generic tool results through automatic file offloading and uses
tool-specific truncation for selected list/search tools.

#### Network & Security

##### Default Binding: 127.0.0.1

By default, the MCP server binds to `127.0.0.1` (localhost only) for security.

**Docker Deployment**: Set `MCP_SERVER_HOST=0.0.0.0` in docker-compose to make the
server accessible from the network.

See `.env.example` for configuration details

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please read our contributing guidelines and submit pull requests.

## Support

- [GitHub Issues](https://github.com/pbv7/worksection-mcp/issues)
- [Worksection API Docs](https://worksection.com/en/faq/api-start.html)
- [MCP Documentation](https://modelcontextprotocol.io/)

## Disclaimer

This is an **independent, community-built integration** with the Worksection API.
It is **not affiliated with, endorsed by, or supported by** Worksection or its
parent company.

- The author is not a Worksection employee.
- "Worksection" and any associated logos are trademarks of their respective
  owner; this project uses the name solely to identify the third-party API it
  integrates with, under nominative fair use.
- For issues with this MCP server, open a ticket on
  [GitHub](https://github.com/pbv7/worksection-mcp/issues) — **not** with
  Worksection support.
- For issues with the Worksection product or API itself, contact
  [Worksection](https://worksection.com) directly.
