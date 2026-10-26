FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable
ADD https://raw.githubusercontent.com/wowsims/forever/f02667f7bcc542d600a3cb924dc7b86a9e856495/assets/database/db.json /app/data/db.json

FROM python:3.13-slim-bookworm
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    WOWSIMS_DB_PATH=/app/data/db.json \
    WOWSIMS_MCP_HOST=0.0.0.0 \
    WOWSIMS_MCP_PORT=8000
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/data /app/data
EXPOSE 8000
USER 65532:65532
CMD ["wowsims-mcp"]
