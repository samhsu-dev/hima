# Design — CLI Service Lifecycle (`hima_dht_cli.services`)

Managed-service subsystem of the operations CLI. Command surface, run
commands, and error handling: `design-cli.md`. Deployment artifacts and
compose services: `design-deployment.md`.

## Design Overview

- **Classes**: `ServiceSpec`, `ServiceOptions`, `ServiceManifest`,
  `ModelEndpoint`, `HostService`, `ContainerService`; the placement value
  set `Placement` (`hima_dht_cli.placement`, `design-cli.md`).
- **Modules**: public entry `services/__init__`; internal submodules
  `_lifecycle` (placement dispatch), `_host` (host processes), `_docker`
  (compose invocations and the game job), `_manifest` (ownership record),
  `_health` (endpoint probes).
- **Relationships**: `_lifecycle` uses `_host`, `_docker`, `_manifest`,
  and `_health`; `_host` and `_docker` use `_health`; `_host` contains
  `ServiceSpec`; `_manifest` contains the manifest data holders and uses
  `placement`. `services` uses `hima_dht_web.server` (webui default port
  and app factory for the managed webui).
- **Dependency roles**: Data holders: `ServiceSpec`, `ServiceOptions`,
  `ServiceManifest`, `ModelEndpoint`, `HostService`, `ContainerService`.
  Orchestrator: `_lifecycle`. Helpers: `_host`, `_docker`, `_health`
  (stateless functions).
- **Exceptions**: `CommandError` on every user-facing failure, handled only
  in `cli` (`design-cli.md`).

## Class / Type Specifications

### ServiceSpec (`services._host`)
- **Responsibility**: Describe one natively spawned background service.
- **Fields**: `name: str`, `argv: list[str]`, `health_url: str`,
  `pid_file: Path`, `log_file: Path`, `process_keyword: str`.
- **Methods**: none (data holder). `process_keyword` guards `down`: a stored PID is
  killed only when its command line contains this keyword.

### ServiceOptions (`services._lifecycle`)
- **Responsibility**: Placement, service set, endpoint, and model selection
  for the managed services, resolved by `cli` and passed as one parameter
  object.
- **Fields**: `placement: Placement`, `webui: bool` (the observation server
  is opt-in; the advisor is always managed because every game needs it),
  `advisor_port: int`, `webui_port: int`, `model: str`,
  `leader_base_url: str`, `leader_api_key: str` — each defaulting to the
  owning module's constant.
- **Methods**: none (data holder).

### ServiceManifest / ModelEndpoint / HostService / ContainerService (`services._manifest`)
- **Responsibility**: Record of what `up` started and which model endpoints
  the deployment consumes, written to `tmp/services/manifest.toml` on every
  successful `up` (`--manifest-out` writes a copy); the ownership source for
  `down` and `status`.
- **Fields**: `ServiceManifest` — `placement: Placement`, `created: str`
  (ISO timestamp), `endpoints: dict[str, ModelEndpoint]` (keyed by role;
  today the single role `leader`), `services: dict[str, HostService |
  ContainerService]` (the webui entry is absent when `up` did not start
  it). `ModelEndpoint` — `url: str` (the OpenAI-compatible base
  URL `up` verified, host view), `model: str`; never an API key — secrets
  stay in the environment chain. `HostService` — `endpoint: str`,
  `pid: int`, `pid_file: str`, `log_file: str`. `ContainerService` —
  `endpoint: str` (host-published), `container: str`.
- **Methods**: none (data holders). TOML write via `tomli-w`, read via
  `tomllib`; the manifest-level `placement` discriminates the service entry
  type; endpoints serialize as the `[endpoints.<role>]` tables.
  The document carries a layout `version` key (currently 3). The write is
  atomic: a scratch file replaced over the target, so a crash mid-write
  never leaves a torn manifest. The read raises `CommandError` on
  unparsable TOML, on a version other than the reader's, and on a document
  missing required keys — each message states the remediation (delete the
  file and rerun `hima up`; `hima down` without a manifest still sweeps
  host pid files).

## Function Specifications

- **up(options, manifest_out) -> None** — Behavior:
  serialize against every other `up`/`down` via an exclusive non-blocking
  lock on `tmp/services/up-down.lock` (released on close or process exit —
  a crashed holder never wedges it), then dispatch on `options.placement`.
  Leader handling is identical at both placements and is verification only:
  `GET {options.leader_base_url}/models` with the bearer key must list
  `options.model`. hima never starts, stops, or pulls for a leader engine
  at any placement — the engine is operator-owned, whether a host
  `ollama serve`, the opt-in compose `leader` profile, or a hosted
  provider.
  The managed set is the advisor plus, when `options.webui`, the
  observation webui; the observation surface is opt-in because a run
  needs an advisor but never needs a place to watch it from.
  `HOST`: ensure the advisor FastAPI server (`uvicorn --factory` on
  `hima_dht_game.app`) and the selected webui (`uvicorn --factory` on
  `hima_dht_web.server`); each ensure is ownership-aware — an owned live
  pid (pid file + matching command line + process-group leader)
  short-circuits, while an endpoint answering without an owned pid is a
  foreign server and raises; each launch first rotates a service log grown
  past 10 MiB to a single `.1` backup.
  `CONTAINER`: `docker compose up -d --wait` on the selected services
  (the webui sits behind its own `webui` profile, added only when
  `options.webui`), container names from `docker compose ps`; the leader
  engine is never a managed compose service (`design-deployment.md`).
  Both paths write the manifest recording the leader `ModelEndpoint`;
  `manifest_out` writes a copy. Errors: `CommandError` when the service
  lock is held, when health is not reached within the attempt bound, on a
  foreign endpoint, on a compose failure, or when the leader endpoint is
  unreachable or does not serve the model.
- **down() -> None** — Behavior: serialize via the same
  service lock as `up`, then read the manifest; placement
  `CONTAINER` → `docker compose stop` of the recorded services; placement
  `HOST` or no manifest → stop PIDs recorded in pid files in
  reverse launch order (webui, advisor) after verifying ownership
  (command line matches `process_keyword` and the pid is its own
  process-group leader); each stop signals the whole process group SIGTERM,
  waits 10 s, escalates to SIGKILL, waits 5 s more; never touches other
  processes. Removes the manifest. Errors: `CommandError` when the service
  lock is held or a process survives SIGKILL.
- **status(options, game) -> bool** — Behavior: report the manifest
  (placement and creation time, or its absence), then one check per
  recorded service — the webui is checked only when the manifest records
  it, so an advisor-only `up` reports two lines, not a webui failure:
  probe the recorded endpoint at its health path (one probe-path
  table in `_health`, shared with the service specs); a host entry
  additionally requires the recorded pid alive — a reachable endpoint whose
  recorded pid is gone fails as a foreign process; then the leader check
  against the recorded `ModelEndpoint`: `GET {url}/models` with the
  chain-resolved bearer key must list the recorded model
  (endpoint-agnostic — Ollama, vLLM, or a hosted provider); then the game
  runtime for `game`, never for the service placement — the two are
  independent axes (`design-cli.md`), and `game` resolves through the same
  `--game`/`HIMA_GAME` chain `hima run` uses, so `status` checks exactly
  the runtime the next run will use: the SC2 installation path for `HOST`,
  the game image presence for `CONTAINER` (its failure detail names
  `hima run --game container` as the builder). Without a manifest, checks
  fall back to option-derived endpoints. Output: `True` when every check
  passes; `cli` exits 1 otherwise. Errors: `CommandError` on a corrupt or
  version-mismatched manifest.
- **ensure_game_image(sc2_license) -> None** — Behavior: return when the
  game image exists (`docker image inspect`); absent with `sc2_license`
  `None` → error naming `SC2_LICENSE` and the Blizzard AI and Machine
  Learning License acceptance it carries; absent with a value → build via
  `docker compose --profile game build game` with `SC2_LICENSE` passed
  through the build environment, logging that the first build downloads
  multiple GB. Errors: `CommandError` on a missing license or failed build.
- **run_game(game_args, advisor_host) -> None** — Behavior: `docker compose
  --profile game run --rm -e HIMA_ADVISOR_HOST=<advisor_host> game`,
  appending the in-container command override
  `hima run <game_args>` when `game_args` is non-empty (an empty list keeps
  the compose-file command); streams output. The advisor address is an
  environment override, not a flag, so the in-container chain still
  resolves flag > environment > .env > default. The compose `game` service
  pins `HIMA_GAME=host` in its environment: inside the container the game
  is already local, and without the pin the container-default value would
  make the in-container `hima run` dispatch back into compose
  (`design-deployment.md`). Errors: `CommandError` carrying the exit code
  on a non-zero game exit.

## Exception / Error Types

- `CommandError` — the CLI-wide user-facing failure type; raising sites
  above, full catalog and handling in `design-cli.md`.
