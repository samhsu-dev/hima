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
- **Relationships**: `game` uses `advisor` by service name (one-way); the
  leader is an OpenAI-compatible URL (`HIMA_LEADER_BASE_URL`), defaulting to
  the host's native Ollama through the container-to-host name. `webui` reads
  the host's `runs/` and `tmp/` bind mounts. `advisor` and `webui` build from
  `hima.Dockerfile` with their member selected; `game` builds from the cli
  image.
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
  (no default groups). No image mutates site-packages: the pysc2
  compatibility fixes apply in-process (`hima_dht_cli.pysc2_play`).
- **Interfaces**: no default command; each compose service sets its own.
- **Constraint**: Linux torch resolves from the CPU wheel index
  (`[tool.uv.sources]`, marker `sys_platform == 'linux'`); macOS keeps the default
  MPS-capable wheel. GPU-advisor images are out of scope. Torch enters only the
  advisor image; the webui and cli images exclude the advisor closure.

### game (`docker/game.Dockerfile`)
- **Responsibility**: The cli image plus the StarCraft II Linux headless client
  (4.10), the 4.10-compatible ladder map artifact (`AncientCisternAIE` from
  `maps/`, installed under the retail name), and the emulation boundary that
  runs only the SC2 binary under amd64 emulation.
- **Base**: the cli member image on the build host's native platform, consumed
  via the `HIMA_IMAGE` build argument. Python and the game runtime execute
  natively; no whole-container emulation.
- **Emulation boundary**: `SC2_x64` is a wrapper script that execs the real
  binary (`SC2_x64.real`, same directory) through `qemu-x86_64` on non-x86_64
  hosts and directly on x86_64. burnysc2 spawns the wrapper unchanged; `exec`
  keeps the process id it kills. The amd64 runtime libraries (libc, libstdc++)
  install via Debian multiarch at their canonical paths, so the wrapper needs
  no library-prefix argument.
- **Build argument**: the license-acceptance string unpacking Blizzard's archive;
  no default value — the build fails until the user supplies it.
- **Constraint**: whole-container amd64 emulation on Apple silicon is forbidden —
  Rosetta crashes SC2 at port initialization (`impl-deployment.md`). qemu-user
  TCG is slow; acceptable because games are LLM-bound. Results are not
  comparable with retail 5.0.16 runs (`concept-deployment.md`).

### leader baked (`docker/leader.Dockerfile`)
- **Responsibility**: ollama image with qwen3:8b pulled at build time; version pinned
  to the local client's ollama release.

## Service Specifications

| Service | Image | Command | Ports | Data |
|---------|-------|---------|-------|------|
| `advisor` | advisor | `uvicorn --factory hima_dht_game.app:create_default_app --host 0.0.0.0 --port 8090` | 8090 | `hf-cache` volume at `HF_HOME` |
| `ollama` | ollama pinned | default | none (compose network) | `ollama` volume |
| `leader-baked` | leader baked | default | 11434 | weights in image |
| `webui` | webui | `uvicorn --factory hima_dht_web.server:create_default_app --host 0.0.0.0 --port 8123` | 8123 | `./runs`, `./tmp` bind mounts (read-only) |
| `game` | game | `hima run`, configured via `HIMA_*` environment | none | `./runs`, `./tmp` bind mounts (read-write) |

- The webui factory and `hima run` anchor the run layout to the working
  directory (`design-packages.md`); each service's `WORKDIR` is the directory
  holding the `runs/` and `tmp/` bind mounts.

- Service lifecycle boundary: `hima up`/`down`/`status` manage the long-lived
  prerequisite services only (`ollama`/`leader-baked`, `advisor`, `webui`). The
  `game` service is a one-shot job in the run lifecycle: launched per game via
  the `game` profile, exits with the run, never managed by `up`/`down`.
- `ollama` and `leader-baked` are compose-network alternatives for the same
  role, selected by pointing `HIMA_LEADER_BASE_URL` at their service name;
  the `baked` profile builds the weights into the image. Only `leader-baked`
  publishes 11434 — its profile is explicit opt-in — while the
  default-profile `ollama` publishes nothing, leaving the host port to the
  native server `hima up` manages.
- `advisor` serves `GET /health`, ready only after model loading completes; the
  host-side health precheck polls it.
- `game` carries no command flags: its compose `environment` block sets the
  container-context values (`HIMA_ADVISOR_HOST=advisor`; leader URL default
  `http://host.docker.internal:11434/v1`) and forwards `.env` overrides via
  `${HIMA_*}` interpolation, keeping the CLI precedence chain (flag >
  environment > .env > default) intact. The host-native game keeps the
  localhost defaults. The advisor host is an argument: `hima_dht_game
  --advisor_host` (default `localhost`), consumed by the bot when building
  the inference URL, forwarded by `hima run --advisor-host`.

## Exception / Error Handling

- A compose service failing its health start-up is restarted by compose policy;
  `hima status` on the host reports reachability the same way for native and
  containerized services.
- The `game` image build without the license argument fails at the unpack layer with
  the argument name in the error.
