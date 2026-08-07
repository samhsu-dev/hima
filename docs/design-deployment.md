# Design — Deployment Artifacts (`docker/`)

Concepts and placement rationale: `concept-deployment.md`. This document specifies the images,
services, and their interfaces. No classes; components only.

## Design Overview

- **Images**: one image per service from one parameterized Dockerfile —
  advisor (`hima-dht-game[advisor]`), webui (`hima-dht-web`), cli
  (`hima-dht-cli` without the `advisor` extra); `game` (cli image +
  StarCraft II headless); leader baked image (ollama + qwen3:8b weights).
  Member mapping: `design-packages.md`.
- **Services** (`docker-compose.yml`): `advisor`, `ollama`, `leader-baked` (profile
  `baked`), `webui`, `game` (profile `game`)
- **Relationships**: `game` uses `advisor` and `ollama` by service name (one-way).
  `webui` reads the host's `runs/` and `tmp/` bind mounts. `advisor` and `webui`
  build from `hima.Dockerfile` with their member selected; `game` builds from
  the cli image.
- **Build inputs**: root `pyproject.toml` + `uv.lock` (locked workspace),
  `packages/` (member metadata and sources), StarCraft II Linux package
  (user-provided license acceptance).

## Image Specifications

### member images (`docker/hima.Dockerfile`)
- **Responsibility**: One Dockerfile for every Python service image; the `PACKAGE`
  build argument selects the workspace member, and `uv sync --locked --package`
  installs that member plus its dependency closure, nothing else.
- **Layers**: uv base image → dependency-only sync from the lock and member
  metadata → copy `packages/` source → `uv sync --locked --package $PACKAGE`
  (no dev groups). The cli image additionally runs `uv run hima setup`
  (site-packages patches — pysc2 and s2protocol live only in the cli closure).
- **Interfaces**: no default command; each compose service sets its own.
- **Constraint**: Linux torch resolves from the CPU wheel index
  (`[tool.uv.sources]`, marker `sys_platform == 'linux'`); macOS keeps the default
  MPS-capable wheel. GPU-advisor images are out of scope. Torch enters only the
  advisor image; the webui and cli images exclude the advisor closure.

### game (`docker/game.Dockerfile`)
- **Responsibility**: The cli image plus the StarCraft II Linux headless client
  (4.10) and the ladder map pool including Ancient Cistern LE.
- **Base**: the cli member image built with `--platform linux/amd64`,
  consumed via the `HIMA_IMAGE` build argument.
- **Build argument**: the license-acceptance string unpacking Blizzard's archive;
  no default value — the build fails until the user supplies it.
- **Constraint**: `linux/amd64` only; on Apple silicon it runs emulated and slow.
  Results are not comparable with retail 5.0.16 runs (`concept-deployment.md`).

### leader baked (`docker/leader.Dockerfile`)
- **Responsibility**: ollama image with qwen3:8b pulled at build time; version pinned
  to the local client's ollama release.

## Service Specifications

| Service | Image | Command | Ports | Data |
|---------|-------|---------|-------|------|
| `advisor` | advisor | `uvicorn --factory hima_dht_game.advisor:create_default_app --host 0.0.0.0 --port 8090` | 8090 | `hf-cache` volume at `HF_HOME` |
| `ollama` | ollama pinned | default | 11434 | `ollama` volume |
| `leader-baked` | leader baked | default | 11434 | weights in image |
| `webui` | webui | `uvicorn --factory hima_dht_web.server:create_default_app --host 0.0.0.0 --port 8123` | 8123 | `./runs`, `./tmp` bind mounts (read-only) |
| `game` | game | `hima run` with service-name endpoints | none | `./runs`, `./tmp` bind mounts (read-write) |

- The webui factory and `hima run` anchor the run layout to the working
  directory (`design-packages.md`); each service's `WORKDIR` is the directory
  holding the `runs/` and `tmp/` bind mounts.

- `ollama` and `leader-baked` are alternatives on the same port; `baked` profile
  selects the second.
- `advisor` serves `GET /health`, ready only after model loading completes; the
  host-side health precheck polls it.
- `game` passes `--advisor-host advisor` and `--base-url http://ollama:11434/v1`;
  the host-native game keeps the localhost defaults. This requires the advisor host
  to become an argument: `hima_dht_game --advisor_host` (default `localhost`), consumed
  by the bot when building the inference URL, forwarded by `hima run --advisor-host`.

## Exception / Error Handling

- A compose service failing its health start-up is restarted by compose policy;
  `hima status` on the host reports reachability the same way for native and
  containerized services.
- The `game` image build without the license argument fails at the unpack layer with
  the argument name in the error.
