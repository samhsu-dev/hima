# One parameterized image for every hima Python service: the PACKAGE build
# argument selects the workspace member, EXTRA optionally adds one of its
# extras (design-deployment.md). Built from the committed lock only — no
# dependency resolution at build time.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

ARG PACKAGE
ARG EXTRA=""
RUN test -n "${PACKAGE}" || { \
      echo "build arg PACKAGE required: the workspace member to install"; \
      exit 1; }

WORKDIR /app

# Dependency layer from the lock and member metadata alone, so source edits
# never bust it. Workspace discovery needs every member's pyproject.toml.
COPY pyproject.toml uv.lock /app/
COPY packages/hima-dht-records/pyproject.toml /app/packages/hima-dht-records/
COPY packages/hima-dht-game/pyproject.toml /app/packages/hima-dht-game/
COPY packages/hima-dht-web/pyproject.toml /app/packages/hima-dht-web/
COPY packages/hima-dht-cli/pyproject.toml /app/packages/hima-dht-cli/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package "${PACKAGE}" --no-default-groups \
      --no-install-workspace ${EXTRA:+--extra "${EXTRA}"}

COPY packages /app/packages

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package "${PACKAGE}" --no-default-groups \
      ${EXTRA:+--extra "${EXTRA}"}

ENV PATH="/app/.venv/bin:$PATH"
