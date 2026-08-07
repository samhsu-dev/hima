# Design — CLI Service Lifecycle (`hima_dht_cli.services`)

Managed-service subsystem of the operations CLI. Command surface, run
commands, and error handling: `design-cli.md`. Deployment artifacts and
compose services: `design-deployment.md`.

## Design Overview

- **Classes**: `ServiceSpec`, `ServiceOptions`, `ServiceBackend`,
  `ServiceManifest`, `ModelEndpoint`, `NativeService`, `DockerService`
- **Modules**: public entry `services/__init__`; internal submodules
  `_lifecycle` (backend dispatch), `_native` (host processes), `_docker`
  (compose invocations and the game job), `_manifest` (ownership record),
  `_health` (endpoint probes).
- **Relationships**: `_lifecycle` uses `_native`, `_docker`, `_manifest`,
  and `_health`; `_native` and `_docker` use `_health`; `_native` contains
  `ServiceSpec`; `_manifest` contains `ServiceBackend` and the manifest
  data holders. `services` uses `hima_dht_web.server` (webui default port
  and app factory for the managed webui).
- **Dependency roles**: Data holders: `ServiceSpec`, `ServiceOptions`,
  `ServiceManifest`, `ModelEndpoint`, `NativeService`, `DockerService`.
  Orchestrator: `_lifecycle`. Helpers: `_native`, `_docker`, `_health`
  (stateless functions).
- **Exceptions**: `CommandError` on every user-facing failure, handled only
  in `cli` (`design-cli.md`).

## Class / Type Specifications

### ServiceSpec (`services._native`)
- **Responsibility**: Describe one natively spawned background service.
- **Fields**: `name: str`, `argv: list[str]`, `health_url: str`,
  `pid_file: Path`, `log_file: Path`, `process_keyword: str`,
  `env: Mapping[str, str]` (extra spawn environment; Ollama's bind address).
- **Methods**: none (data holder). `process_keyword` guards `down`: a stored PID is
  killed only when its command line contains this keyword.

### ServiceOptions (`services._lifecycle`)
- **Responsibility**: Backend, endpoint, and model selection for the managed
  services, resolved by `cli` and passed as one parameter object.
- **Fields**: `backend: ServiceBackend`, `advisor_port: int`,
  `webui_port: int`, `ollama_port: int`, `model: str`,
  `leader_base_url: str`, `leader_api_key: str` — each defaulting to
  the owning module's constant.
- **Methods**: none (data holder).

### ServiceBackend (`services._manifest`)
- **Responsibility**: Closed value set naming where the managed services run —
  `NATIVE` (host processes with pid files) or `DOCKER` (compose services).
  Persisted in the manifest so `down`/`status` operate on the recorded
  backend, never on port probing.

### ServiceManifest / ModelEndpoint / NativeService / DockerService (`services._manifest`)
- **Responsibility**: Record of what `up` started and which model endpoints
  the deployment consumes, written to `tmp/services/manifest.toml` on every
  successful `up` (`--manifest-out` writes a copy); the ownership source for
  `down` and `status`.
- **Fields**: `ServiceManifest` — `backend: ServiceBackend`, `created: str`
  (ISO timestamp), `endpoints: dict[str, ModelEndpoint]` (keyed by role;
  today the single role `leader`), `services: dict[str, NativeService |
  DockerService]`. `ModelEndpoint` — `url: str` (the OpenAI-compatible base
  URL `up` verified, host view), `model: str`; never an API key — secrets
  stay in the environment chain. `NativeService` — `endpoint: str`,
  `pid: int`, `pid_file: str`, `log_file: str`. `DockerService` —
  `endpoint: str` (host-published), `container: str`.
- **Methods**: none (data holders). TOML write via `tomli-w`, read via
  `tomllib`; the manifest-level `backend` discriminates the service entry
  type; endpoints serialize as the `[endpoints.<role>]` tables.
  The document carries a layout `version` key (currently 2). The write is
  atomic: a scratch file replaced over the target, so a crash mid-write
  never leaves a torn manifest. The read raises `CommandError` on
  unparsable TOML, on a version other than the reader's, and on a document
  missing required keys — each message states the remediation (delete the
  file and rerun `hima up`; `hima down` without a manifest still sweeps
  native pid files).

## Function Specifications

- **up(options, skip_pull, manifest_out) -> None** — Behavior:
  serialize against every other `up`/`down` via an exclusive non-blocking
  lock on `tmp/services/up-down.lock` (released on close or process exit —
  a crashed holder never wedges it), then dispatch on `options.backend`.
  Leader handling is common to both backends: when
  `options.leader_base_url` equals the local default derived from the
  ollama port (`http://localhost:{ollama_port}/v1`, textual comparison) the
  native backend provisions `ollama serve` and ensures the leader model
  (host `ollama pull` when absent unless `skip_pull`); any other URL — and
  every URL on the docker backend — is verified instead: `GET
  {url}/models` with the bearer key must list `options.model`.
  `NATIVE`: ensure the services in dependency order — the provisioned
  `ollama serve` (bound to `ollama_port` via `OLLAMA_HOST`) when the rule
  selects it, the advisor FastAPI server (`uvicorn --factory` on
  `hima_dht_game.app`), the observation webui (`uvicorn --factory` on
  `hima_dht_web.server`); each ensure is ownership-aware — an owned live
  pid (pid file + matching command line + process-group leader)
  short-circuits, while an endpoint answering without an owned pid is a
  foreign server and raises; each launch first rotates a service log grown
  past 10 MiB to a single `.1` backup.
  `DOCKER`: `docker compose up -d --wait` on advisor/webui, container
  names from `docker compose ps`; the leader engine is never a managed
  compose service (`design-deployment.md`).
  Both paths write the manifest recording the leader `ModelEndpoint`;
  `manifest_out` writes a copy. Errors: `CommandError` when the service
  lock is held, when health is not reached within the attempt bound, on a
  foreign endpoint, on a compose failure, when the verified leader
  endpoint is unreachable or does not serve the model, or when the model
  is absent under `skip_pull`.
- **down() -> None** — Behavior: serialize via the same
  service lock as `up`, then read the manifest; backend
  `DOCKER` → `docker compose stop` of the recorded services; backend
  `NATIVE` or no manifest → stop PIDs recorded in pid files in
  reverse launch order (webui, advisor, ollama) after verifying ownership
  (command line matches `process_keyword` and the pid is its own
  process-group leader); each stop signals the whole process group SIGTERM,
  waits 10 s, escalates to SIGKILL, waits 5 s more; never touches other
  processes. Removes the manifest. Errors: `CommandError` when the service
  lock is held or a process survives SIGKILL.
- **status(options) -> bool** — Behavior: report the manifest
  (backend and creation time, or its absence), then one check per recorded
  service: probe the recorded endpoint at its health path (one probe-path
  table in `_health`, shared with the service specs); a native entry
  additionally requires the recorded pid alive — a reachable endpoint whose
  recorded pid is gone fails as a foreign process; then the leader check
  against the recorded `ModelEndpoint`: `GET {url}/models` with the
  chain-resolved bearer key must list the recorded model
  (endpoint-agnostic — Ollama, vLLM, or a hosted provider); then the
  backend-matched game runtime — the SC2 installation path on the native
  backend, the game image presence on the docker backend (its failure
  detail names `hima run --headless` as the builder). Without a manifest,
  checks fall back to option-derived endpoints and the native game
  runtime. Output: `True` when every check passes; `cli` exits 1
  otherwise. Errors: `CommandError` on a corrupt or version-mismatched
  manifest.
- **ensure_game_image(sc2_license) -> None** — Behavior: return when the
  game image exists (`docker image inspect`); absent with `sc2_license`
  `None` → error naming `SC2_LICENSE` and the Blizzard AI and Machine
  Learning License acceptance it carries; absent with a value → build via
  `docker compose --profile game build game` with `SC2_LICENSE` passed
  through the build environment, logging that the first build downloads
  multiple GB. Errors: `CommandError` on a missing license or failed build.
- **run_game(game_args) -> None** — Behavior: `docker compose --profile
  game run --rm game`, appending the in-container command override
  `hima run <game_args>` when `game_args` is non-empty (an empty list keeps
  the compose-file command); streams output. Errors: `CommandError`
  carrying the exit code on a non-zero game exit.

## Exception / Error Types

- `CommandError` — the CLI-wide user-facing failure type; raising sites
  above, full catalog and handling in `design-cli.md`.
