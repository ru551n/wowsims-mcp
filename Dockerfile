FROM golang:1.25.4-bookworm AS sim-build
ARG WOWSIMS_COMMIT=f02667f7bcc542d600a3cb924dc7b86a9e856495
RUN apt-get update \
    && apt-get install -y --no-install-recommends protobuf-compiler libprotobuf-dev python3 \
    && rm -rf /var/lib/apt/lists/* \
    && go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.10
WORKDIR /src
RUN git clone --filter=blob:none https://github.com/wowsims/forever.git . \
    && git checkout "$WOWSIMS_COMMIT" \
    && test "$(git rev-parse HEAD)" = "$WOWSIMS_COMMIT" \
    && protoc -I=./proto \
        --go_opt=Mgoogle/protobuf/descriptor.proto=google.golang.org/protobuf/types/descriptorpb \
        --go_out=./sim/core ./proto/*.proto \
    && CGO_ENABLED=0 go build --tags=with_db -o /wowsimcli ./cmd/wowsimcli
COPY tools/build_presets.py /tmp/build_presets.py
RUN python3 /tmp/build_presets.py /src /presets.json

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY --from=sim-build /presets.json ./src/wowsims_mcp/presets.json
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
COPY --from=sim-build /wowsimcli /usr/local/bin/wowsimcli
EXPOSE 8000
USER 65532:65532
CMD ["wowsims-mcp"]
