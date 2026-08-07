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
  4.10 client is still unverified: the first containerized run crashed in SC2
  startup, before map load (see Rosetta incompatibility below).
- SC2 4.10 under OrbStack's Rosetta amd64 emulation crashes at startup: after
  "Creating stub renderer..." it prints "unable to parse listen address." /
  "Failed to initialize port" and dies with signal 11. Reproduced with single-
  and double-dash arg forms, `-listen 127.0.0.1|0.0.0.0|localhost`, and on both
  Debian trixie and Ubuntu 18.04 userlands — glibc version is not the cause.
  `getaddrinfo`/`bind` from Python succeed in the same Rosetta container.
- The same binary and args under qemu-user TCG (arm64 container, `qemu-x86_64
  -L <amd64 rootfs>`) starts fully: "Listening on: 127.0.0.1:5000", "Startup
  Phase 3 complete". The crash is a Rosetta emulation defect, not an SC2 or
  image defect.
- qemu-user caveats: launching via `ld-2.27.so <binary>` breaks SC2's install-root
  discovery (`/proc/self/exe` points at the loader — "Failed to find .build.info");
  exec the binary directly with `-L`. An `-L` prefix must not contain absolute
  symlinks that escape it (Ubuntu's `/lib64/ld-linux-x86-64.so.2` does; replace
  with a copy).
- Containerized game on Apple silicon therefore requires either an amd64 host or
  an arm64 game image that execs only `SC2_x64` through qemu-user — a
  `design-deployment.md` revision pending user confirmation.

## Developer instructions

- After editing `[tool.uv.sources]`: `uv lock`, commit `uv.lock`.
- No image patches site-packages: the pysc2 compatibility fixes apply
  in-process when `hima replay` spawns `hima_dht_cli.pysc2_play`.
- Compose: default profile = advisor + ollama + webui; `--profile baked` swaps the
  leader; `--profile game` adds the containerized game (linux/amd64 only).
- `FROM` of a local tag ignores the requested build platform, so the game image
  needs a separate amd64 base tag:
  `docker build --platform linux/amd64 -t hima-cli:amd64 --build-arg
  PACKAGE=hima-dht-cli -f docker/hima.Dockerfile .`.
- Compose forwards `SC2_LICENSE` from the environment (`${SC2_LICENSE:-}`); an
  empty value fails the guard layer naming the argument before any download.
- Compose `${VAR:-default}` interpolation reads the `.env` beside
  `docker-compose.yml`; an exported environment variable overrides the `.env`
  value. The published-port defaults live in `.env.example`.
- python:3.12-slim has no curl; the advisor healthcheck runs
  `python -c "urllib.request.urlopen(...)"` from the image venv on PATH.
- The ladder map lives in the git-tracked `maps/`; the game image COPYs it from
  there. No `docker/maps/` staging directory.
- macOS container VMs (Docker Desktop, OrbStack) expose no Apple-GPU
  passthrough: a containerized Ollama runs CPU-only. The leader runs on native
  Ollama (`brew install ollama`); the compose `ollama` service targets Linux
  hosts (NVIDIA block commented in `docker-compose.yml`).
- Leader portability lives in the endpoint contract, not the engine: `hima run`
  prechecks `GET {HIMA_LEADER_BASE_URL}/models` with `HIMA_LEADER_API_KEY` as
  bearer token, so any OpenAI-compatible server (Ollama, vLLM, hosted
  providers) serves the leader.
