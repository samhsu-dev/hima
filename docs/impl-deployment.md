# Implementation Notes — Deployment (`design-deployment.md`)

## APIs

- **[uv]** index pinning by platform marker (verified against uv docs; named indexes
  must be defined in `pyproject.toml` itself):

  ```toml
  [tool.uv.sources]
  torch = [{ index = "pytorch-cpu", marker = "sys_platform == 'linux'" }]

  [[tool.uv.index]]
  name = "pytorch-cpu"
  url = "https://download.pytorch.org/whl/cpu"
  explicit = true
  ```

- **[uv]** Docker layering (verified against uv Docker guide; tag `0.12.1` exists and
  matches the local uv):

  ```dockerfile
  COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/
  RUN --mount=type=cache,target=/root/.cache/uv \
      --mount=type=bind,source=uv.lock,target=uv.lock \
      --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
      uv sync --locked --no-install-project --no-dev
  COPY . /app
  RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev
  ```

## Libraries

- torch 2.13.0+cpu — CPU index ships `manylinux_2_28_x86_64` and `_aarch64` wheels:
  advisor/webui images build for linux/amd64 and linux/arm64; macOS keeps the PyPI
  MPS wheel (marker excludes darwin).
- ollama/ollama:0.32.5 — pinned to the local client; stock service and baked image
  (`docker/leader.Dockerfile`, build verified).

## StarCraft II Linux client

- Download: `https://blzdistsc2-a.akamaihd.net/Linux/SC2.4.10.zip`; unzip password
  `iagreetotheeula` is the AI and Machine Learning License acceptance — the game
  image build argument carries it, no default.
- Install root: burnysc2 Linux default is `~/StarCraftII` (`sc2/paths.py`);
  `SC2PATH` overrides.
- Blizzard map packs (`.../MapPacks/<name>.zip`, same password) end at Ladder 2019
  Season 3 — Ancient Cistern LE (2023) is not in them.
- Map source: the retail install's `/Applications/StarCraft II/Maps/Ancient Cistern
  LE.SC2Map`, copied into the image's `Maps/`. Compatibility of a 2023 map with the
  4.10 client is unverified until the first containerized game runs.

## Developer instructions

- After editing `[tool.uv.sources]`: `uv lock`, commit `uv.lock`.
- Image build runs `uv run hima setup` after the final sync so the three
  site-packages patches land inside the image venv.
- PySC2 4.0.0 wheel ships the colors.py shuffle line with a trailing
  `# Return a fixed shuffle` comment; the patch target includes it — a fresh
  install (image build) fails setup with a comment-less target.
- Compose: default profile = advisor + ollama + webui; `--profile baked` swaps the
  leader; `--profile game` adds the containerized game (linux/amd64 only).
- `FROM` of a local tag ignores the requested build platform, so the game image
  needs a separate amd64 base tag:
  `docker build --platform linux/amd64 -t hima:amd64 -f docker/hima.Dockerfile .`.
- Compose forwards `SC2_LICENSE` from the environment (`${SC2_LICENSE:-}`); an
  empty value fails the guard layer naming the argument before any download.
- python:3.12-slim has no curl; the advisor healthcheck runs
  `python -c "urllib.request.urlopen(...)"` from the image venv on PATH.
- The ladder map is not redistributable: `docker/maps/` is gitignored and filled
  from the retail install before building the game image.
