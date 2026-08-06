# One Python runtime for every hima service; each compose service sets its
# own command (design-deployment.md). Built from the committed lock only —
# no dependency resolution at build time.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

WORKDIR /app

# Dependency layer from lock + pyproject alone, so source edits never bust it.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

# Land the three site-packages patches inside the image venv.
RUN --mount=type=cache,target=/root/.cache/uv uv run hima setup

ENV PATH="/app/.venv/bin:$PATH"
