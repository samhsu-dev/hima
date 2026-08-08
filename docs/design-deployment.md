# Design — Deployment Artifacts (`docker/`)

Concepts and placement rationale: `concept-deployment.md`. This document specifies the images,
services, and their interfaces. No classes; components only.

## Design Overview

- **Images**: one image per service from one parameterized Dockerfile —
  advisor (`hima-dht-game[advisor]`), webui (`hima-dht-web`), cli
  (`hima-dht-cli` without the `advisor` extra); `game` (cli image +
  StarCraft II headless); leader baked image (ollama + qwen3:8b weights).
  Member mapping: `design-packages.md`.
- **Services** (`docker-compose.yml`): `advisor`, `webui` (profile `webui`),
  `ollama` (profile `leader`), `leader-baked` (profile `baked`), `game`
  (profile `game`). Only `advisor` is in the default set: it is the one
  service every game needs.
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
| `ollama` (profile `leader`) | ollama pinned | default | `${HIMA_OLLAMA_PORT:-11434}` | `ollama` volume |
| `leader-baked` (profile `baked`) | leader baked | default | 11434 | weights in image |
| `webui` (profile `webui`) | webui | `uvicorn --factory hima_dht_web.server:create_default_app --host 0.0.0.0 --port 8123` | 8123 | `./runs`, `./tmp` bind mounts (read-only) |
| `game` (profile `game`) | game | `hima run`, configured via `HIMA_*` environment | none | `./runs`, `./tmp` bind mounts (read-write) |

- The webui factory and `hima run` anchor the run layout to the working
  directory (`design-packages.md`); each service's `WORKDIR` is the directory
  holding the `runs/` and `tmp/` bind mounts.

- Service lifecycle boundary: `hima up`/`down`/`status` manage the hima-owned
  long-lived services only — the `advisor` always, the `webui` when
  `--webui` selects it, identically at both placements. The leader is
  consumed through its endpoint, never managed as a hima-owned process or a
  compose service. The `game` service is a one-shot job in the run
  lifecycle: launched per game by `hima run --game container` via the
  `game` profile, exits with the run, never managed by `up`/`down`.
- Leader responsibility split: hima owns verification of the leader endpoint
  (`GET {HIMA_LEADER_BASE_URL}/models` with the bearer key, at `up` and at
  `run`), never the engine behind it — at either placement and with no
  exception. The operator owns the engine's lifecycle: a host
  `ollama serve` (`brew services start ollama` on macOS), the opt-in
  compose `leader` profile, or a hosted provider. hima never spawns,
  stops, or pulls models for it.
- `hima up --services host|container` (`HIMA_SERVICES`, default `host`)
  selects where the managed services run: host processes, or these
  compose services via `docker compose up -d --wait`. `--webui`
  (`HIMA_WEBUI`, default off) adds the observation server to that set at
  either placement — as a second host process, or by adding the `webui`
  profile to the compose invocation. Every successful `up`
  records its ownership in `tmp/services/manifest.toml`; `down`/`status`
  operate on the recorded placement (`design-cli.md`). Both placements serve
  the same host ports, so they are exclusive per port: `up` fails explicitly
  when an endpoint is answered by a process it does not own — never a
  silent skip.
- The three deployment choices are independent and share no vocabulary:
  `up --services` places the services, `run --game` places the game, and
  `run --ui` selects the observation surface. A container game with host
  services is invalid only because the game job needs the compose network,
  which the manifest check states explicitly; the observation surface
  constrains nothing, because both surfaces read the `runs/` and `tmp/`
  trees that either game placement writes.
- `ollama` (profile `leader`) is an opt-in containerized engine for Linux
  hosts with NVIDIA GPUs: activate the profile and point
  `HIMA_LEADER_BASE_URL` at its published `${HIMA_OLLAMA_PORT:-11434}`. On
  macOS the engine stays native for the Metal GPU (`impl-deployment.md`).
  `ollama` and `leader-baked` are alternatives for the same role — the
  `baked` profile (explicit opt-in, fixed 11434 publish) builds the weights
  into the image; a compose-network game selects either by pointing
  `HIMA_LEADER_BASE_URL` at the service name.
- `advisor` serves `GET /health`, ready only after model loading completes; the
  host-side health precheck polls it.
- `game` carries no command flags in the compose file: its `environment`
  block sets the container-context values (`HIMA_ADVISOR_HOST=advisor`;
  `HIMA_GAME=host`, because the game is already local once inside the
  container and the shipped default would otherwise make the in-container
  `hima run` dispatch back into compose; leader URL default
  `http://host.docker.internal:11434/v1`) and forwards
  `.env` overrides via `${HIMA_*}` interpolation, keeping the CLI precedence
  chain (flag > environment > .env > default) intact. The host game
  keeps the localhost defaults. The advisor host is an argument:
  `hima_dht_game --advisor_host` (default `localhost`), consumed by the bot
  when building the inference URL, forwarded by `hima run --advisor-host`.
- `hima run` wraps the one-shot `game` job at its default placement
  `--game container`. It requires a manifest
  recording the container placement, ensures the game image (built via the compose
  `game` profile when absent; the build requires `SC2_LICENSE`), then runs
  the service with `--rm`. Game-semantic flags given on the host command line
  (difficulty, enemy race, seed, model, realtime) are forwarded as flags to
  the in-container `hima run` — a per-invocation command override, so the
  chain inside the container still resolves flag > environment > .env >
  default. Host-topology flags (`--port`, `--advisor-host`, `--base-url`,
  `--api-key`) are rejected with `--game container`: inside the compose
  network those values are the `environment` block's concern. `--game host`
  runs the retail macOS client in place and takes those flags instead.

## Exception / Error Handling

- A compose service failing its health start-up is restarted by compose policy;
  `hima status` on the host reports reachability the same way for host
  processes and containerized services.
- The `game` image build without the license argument fails at the unpack layer with
  the argument name in the error.
- An unreachable leader endpoint fails `up` naming both remediations: start
  an engine serving the URL (`ollama serve`) or point `HIMA_LEADER_BASE_URL`
  at a reachable provider.
- A container game without a container-placement manifest fails naming the
  remediation (`hima down && hima up --services container`); a missing game
  image without `SC2_LICENSE` fails naming the variable and the license
  acceptance it carries.
- `hima run --ui web` without a webui answering fails naming
  `hima up --webui`; the run does not start, because an observation the
  user asked for and cannot get is a failed request, not a downgrade.
