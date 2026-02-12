FROM python:3.13-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY models.py repository.py server.py google_sheets_auth.py ./

EXPOSE 8000

ENV MCP_TRANSPORT=http
ENV MCP_HOST=0.0.0.0
# MCP_PORT defaults to 8000, but Railway injects PORT at runtime.
# server.py reads PORT as a fallback if MCP_PORT is not set.

CMD ["uv", "run", "python", "server.py"]
