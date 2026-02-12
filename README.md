# Open PFM - Personal Finance MCP Server

An [MCP](https://modelcontextprotocol.io/) server that lets AI assistants manage your personal finances in a Google Spreadsheet. Connect it to Claude Desktop, Cursor, or any MCP client and use natural language to track transactions, view assets, and monitor recurring flows.

## What it does

| Tool | Description |
|------|-------------|
| `fetch_transactions` | Query transactions by date range and category |
| `get_transaction` | Look up a single transaction by ID |
| `add_transaction` | Add a new transaction |
| `update_transaction` | Edit an existing transaction |
| `delete_transaction` | Remove a transaction |
| `fetch_assets` | List accounts/assets from the Assets sheet |
| `fetch_flows` | List recurring income and expenses from the Recurring sheet |

## Quickstart (local, ~5 min)

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/open-pfm.git
cd open-pfm
uv sync
```

> Don't have `uv`? Install it: `curl -LsSf https://astral.sh/uv/install.sh | sh`

### 2. Set up Google Sheets API

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a project (or pick an existing one)
2. Enable the **Google Sheets API** (APIs & Services > Library > search "Google Sheets API" > Enable)
3. Create credentials:
   - **For local use:** Create an OAuth 2.0 Client ID (Desktop app), download the JSON, and save it as `credentials.json` in the project root
   - **For Docker / headless:** Create a Service Account, download the JSON key, and share your spreadsheet with the service account email

### 3. Prepare your spreadsheet

Create a Google Spreadsheet with a sheet per year (e.g. `2024`, `2025`). Each sheet should have **no header row** and the following columns:

| A (Date) | B (Name) | C (Amount) | D (Description) | E (Category) |
|-----------|----------|------------|------------------|--------------|
| 01/15/2025 | Coffee Shop | $5.50 | Morning coffee | Food |
| 01/16/2025 | Salary | $3000.00 | Monthly salary | Income |

Optional sheets:
- **Assets** (columns A-G): ID, Name, Type, Value, Last Updated, Institution, Notes
- **Recurring** (columns A-F): Name, Amount, Category, Description, Active (TRUE/FALSE), Cadence

### 4. Configure environment

```bash
cp example.env .env
```

Edit `.env` and set your spreadsheet ID (the long string in your spreadsheet's URL):

```
GOOGLE_SPREADSHEET_ID="your-spreadsheet-id-here"
```

### 5. Authenticate

If you're using **OAuth** (Option A from step 2), generate a token before connecting to an MCP client:

```bash
uv run python auth_setup.py
```

A browser window will open for Google OAuth. After authenticating, a `token.json` file is saved and the server can run headlessly from then on.

> **Why a separate step?** MCP clients like Claude Desktop launch the server as a background process with no browser access. Running `auth_setup.py` once up front avoids this problem. If you're using a service account, skip this step.

### 6. Connect your MCP client

**Claude Desktop / Cursor / Claude Code** - add to your MCP config:

```json
{
  "mcpServers": {
    "pfm": {
      "command": "/path/to/open-pfm/.venv/bin/python",
      "args": ["/path/to/open-pfm/server.py"],
      "env": {
        "GOOGLE_SPREADSHEET_ID": "your-spreadsheet-id-here"
      }
    }
  }
}
```

Then ask your assistant things like:
- "Show me my transactions from last month"
- "Add a $45 grocery transaction for today"
- "What are my recurring expenses?"

## Running with Docker

For running as a remote MCP server (e.g. for agents that connect over HTTP):

### Option A: Local Docker

```bash
# Put your service account key in secrets/
mkdir -p secrets
cp /path/to/your-service-account-key.json secrets/service-account.json

# Configure
cp example.env .env
# Edit .env with your GOOGLE_SPREADSHEET_ID

# Run
docker compose up -d
```

The server is available at `http://localhost:8000/sse`.

### Option B: Deploy to Railway (or any Docker host)

1. Encode your service account key: `base64 -w0 /path/to/key.json` (on macOS: `base64 -i /path/to/key.json`)
2. Set these environment variables on your host:

| Variable | Value |
|---|---|
| `GOOGLE_SPREADSHEET_ID` | Your spreadsheet ID |
| `GOOGLE_SERVICE_ACCOUNT_JSON_B64` | The base64 string from step 1 |
| `MCP_TRANSPORT` | `sse` |

The included `Dockerfile` and `railway.toml` work out of the box with Railway. For other platforms, any Docker host that runs the Dockerfile will work.

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_SPREADSHEET_ID` | Yes | - | Your Google Spreadsheet ID (from the URL) |
| `GOOGLE_SERVICE_ACCOUNT_JSON_B64` | No | `""` | Base64-encoded service account JSON (for cloud/Docker) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | No | `""` | Path to service account key file (for local Docker) |
| `GOOGLE_CREDENTIALS_FILE` | No | `credentials.json` | Path to OAuth client credentials (for local dev) |
| `GOOGLE_TOKEN_FILE` | No | `token.json` | Path to cached OAuth token (for local dev) |
| `MCP_TRANSPORT` | No | `stdio` | `stdio` for local, `sse` for remote/Docker |
| `MCP_HOST` | No | `0.0.0.0` | Host to bind (remote mode) |
| `MCP_PORT` | No | `8000` | Port to bind (remote mode) |

## Running tests

```bash
uv sync
uv run pytest tests/ -v
```

## Project structure

```
open-pfm/
├── server.py              # MCP server and tool definitions
├── models.py              # Pydantic data models
├── repository.py          # Data access layer (Google Sheets)
├── google_sheets_auth.py  # Authentication (OAuth / service account)
├── auth_setup.py          # One-time OAuth token generator
├── tests/                 # Test suite
├── Dockerfile             # Container image
├── docker-compose.yml     # Local Docker setup
├── pyproject.toml         # Python project config
└── example.env            # Environment variable template
```

## License

MIT - see [LICENSE](LICENSE).
