# Design — HIMA Operations CLI (`packages/hima-dht-cli/`)

Command interface wrapping the project's internal behaviors: model services, experiment
runs, metric aggregation, replay playback, and replay-to-HTML export. Workspace member
`hima-dht-cli` (`design-packages.md`), import package `hima_dht_cli`, installed as the
`hima` console script. Phases Model and Spec are skipped: pure
infrastructure, no domain semantics, no non-trivial algorithm.

## Design Overview

- **Classes**: `ServiceSpec`, `ServiceOptions`, `ServiceBackend`,
  `ServiceManifest`, `NativeService`, `DockerService`, `ReplayExporter`,
  `CommandError`
- **Modules**: `cli` (typer application: one typed command function per
  subcommand), `workspace` (run layout), `services` (package: public entry
  `services/__init__`, internal submodules `_lifecycle`, `_native`, `_docker`,
  `_manifest`, `_health`), `pysc2_play`,
  `experiment`, `metrics`, `replay`, `export`, `viewer`. The observation webui
  is the separate member `hima-dht-web` (`design-observation.md`).
- **Relationships**: `cli` dispatches to every command module (one-way).
  `viewer` uses `export` (frame data) and `hima_dht_web.logs` (decision and
  command parsing). `export` uses `hima_dht_game.sampler` (record file written
  during re-simulation) and `hima_dht_records` (folding).
  `experiment` uses `services` (health precheck) and `workspace`. Inside
  `services`, `_lifecycle` uses `_native`, `_docker`, `_manifest`, and
  `_health`; `_native` and `_docker` use `_health`; `_native` contains
  `ServiceSpec`; `_manifest` contains `ServiceBackend` and the manifest data
  holders. `services` uses `hima_dht_web.server` (webui default port and
  app factory for the managed webui). `export` contains `ReplayExporter`. All
  command modules use `workspace`.
- **Abstract**: `sc2.observer_ai.ObserverAI` (implemented by `ReplayExporter`)
- **Exceptions**: `CommandError` extends `Exception`, raised by every command module,
  handled only in `cli`
- **Dependency roles**: Data holders: `ServiceSpec`, `ServiceOptions`,
  `ServiceManifest`, `NativeService`, `DockerService`.
  Orchestrators: `cli.main`; `services._lifecycle` (backend dispatch).
  Helpers: all command modules (stateless functions).
- **Defaults**: `cli` loads `.env` from the working directory on entry;
  argument defaults resolve as CLI flag > exported environment > `.env` >
  code default. Environment lookup is declared per option (typer `envvar`);
  no hand-rolled resolution or conversion. The `HIMA_*` keys are shared with
  docker compose interpolation (`.env.example`); `HIMA_SERVICE_BACKEND` and
  `HIMA_OLLAMA_PORT` join them for `up`/`status`. Closed value sets
  (difficulty, race, service backend) are enums. Core modules never read the environment;
  they receive resolved values.
- **Run layout**: `workspace` anchors `tmp/`, `runs/`, and the service state
  directory to the invoking process's working directory (`RUN_ROOT`); `hima`
  runs from the repository root or any chosen run directory. Directory names
  come from the record contract (`hima_dht_records`); `SC2_APP` stays an
  absolute macOS constant.
- **Assets**: none. The canvas player template lives in `hima_dht_web`
  (`design-observation.md`); `viewer` calls `hima_dht_web.server.render` to
  produce one standalone HTML file per replay — the same injection the
  observation server uses.

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
  `webui_port: int`, `ollama_port: int`, `model: str` — each defaulting to
  the owning module's constant.
- **Methods**: none (data holder).

### ServiceBackend (`services._manifest`)
- **Responsibility**: Closed value set naming where the managed services run —
  `NATIVE` (host processes with pid files) or `DOCKER` (compose services).
  Persisted in the manifest so `down`/`status` operate on the recorded
  backend, never on port probing.

### ServiceManifest / NativeService / DockerService (`services._manifest`)
- **Responsibility**: Record of what `up` started, written to
  `tmp/services/manifest.toml` on every successful `up` (`--manifest-out`
  writes a copy); the ownership source for `down` and `status`.
- **Fields**: `ServiceManifest` — `backend: ServiceBackend`, `created: str`
  (ISO timestamp), `leader_model: str`, `leader_endpoint: str` (the
  OpenAI-compatible URL of the leader engine `up` ensures; a
  `HIMA_LEADER_BASE_URL` override may point games elsewhere),
  `services: dict[str, NativeService | DockerService]`.
  `NativeService` — `endpoint: str`, `pid: int`, `pid_file: str`,
  `log_file: str`. `DockerService` — `endpoint: str` (host-published),
  `container: str`.
- **Methods**: none (data holders). TOML write via `tomli-w`, read via
  `tomllib`; the manifest-level `backend` discriminates the entry type.
  The document carries a layout `version` key (currently 1). The write is
  atomic: a scratch file replaced over the target, so a crash mid-write
  never leaves a torn manifest. The read raises `CommandError` on
  unparsable TOML, on a version other than the reader's, and on a document
  missing required keys — each message states the remediation (delete the
  file and rerun `hima up`; `hima down` without a manifest still sweeps
  native pid files).

### ReplayExporter (`export`)
- **Responsibility**: Step through a replay via the SC2 engine and record sampled
  game-state frames.
- **State**: `sample_interval: int`, `frames: list[dict]`, `type_names: list[str]`,
  `type_meta: list[dict]`, `neutral: list[list[float]]`, `meta: dict`.
- **Methods**:
  - `on_step(iteration)` — Behavior: every `sample_interval` iterations append one
    frame (time, resources, supply, visible unit tuples). Input: iteration index.
    Output: none. Errors: none.
  - Frame tuple: `[type_index, x, y, owner, hp]`; `owner` 1 = observed player,
    2 = enemy. Enemy visibility is fog-of-war limited to the observed player's vision.

### CommandError (`errors`)
- **Responsibility**: Signal a user-facing command failure with a printable message.

## Function Specifications

Each command module exposes one public entry consumed by `cli`.

- **main() -> None** (`pysc2_play`) — Responsibility: run `pysc2.bin.play`
  with the compatibility shims applied in-process. Behavior: replace
  `colors.shuffled_hue` (Python 3.11 removed `random.shuffle`'s `random`
  argument; the shim replicates the wheel's fixed shuffle) and wrap
  `run_configs.get` (a replay version newer than pysc2's table falls back
  to the installed 'latest' build), then invoke the play entry. Runs as a
  subprocess of `replay`; site-packages carries no patches, so `uv sync`
  never needs a follow-up step. s2protocol's Python 3.12 breakage is left
  alone: no code path imports it.
- **up(options, skip_pull, manifest_out) -> None** (`services`) — Behavior:
  serialize against every other `up`/`down` via an exclusive non-blocking
  lock on `tmp/services/up-down.lock` (released on close or process exit —
  a crashed holder never wedges it), then dispatch on `options.backend`.
  `NATIVE`: ensure the services in dependency
  order — `ollama serve` (bound to `ollama_port` via `OLLAMA_HOST`), the
  leader model (host `ollama pull` when absent unless `skip_pull`), the
  advisor FastAPI server (`uvicorn --factory` on `hima_dht_game.app`), the
  observation webui (`uvicorn --factory` on `hima_dht_web.server`); each
  ensure is ownership-aware — an owned live pid (pid file + matching command
  line + process-group leader) short-circuits, while an endpoint answering
  without an owned pid is a foreign server and raises; each launch first
  rotates a service log grown past 10 MiB to a single `.1` backup.
  `DOCKER`: `docker compose up -d --wait` on
  ollama/advisor/webui, then verify the compose-published ollama port
  equals the requested one — compose interpolation reads only exported
  environment and `.env`, so a diverging value aborts with a
  `HIMA_OLLAMA_PORT` remediation — leader model presence via the published
  port, pull via `docker compose exec ollama ollama pull`, container names
  from `docker compose ps`. Both paths write the manifest; `manifest_out`
  writes a copy. Errors: `CommandError` when the service lock is held, when
  health is not reached within the attempt bound, on a foreign endpoint, on
  a compose failure or published-port divergence, or when the model is
  absent under `skip_pull`.
- **down() -> None** (`services`) — Behavior: serialize via the same
  service lock as `up`, then read the manifest; backend
  `DOCKER` → `docker compose stop` of the recorded services; backend
  `NATIVE` or no manifest → stop PIDs recorded in pid files in
  reverse launch order (webui, advisor, ollama) after verifying ownership
  (command line matches `process_keyword` and the pid is its own
  process-group leader); each stop signals the whole process group SIGTERM,
  waits 10 s, escalates to SIGKILL, waits 5 s more; never touches other
  processes. Removes the manifest. Errors: `CommandError` when the service
  lock is held or a process survives SIGKILL.
- **status(options) -> bool** (`services`) — Behavior: report the manifest
  (backend and creation time, or its absence), then one check per recorded
  service: probe the recorded endpoint at its health path (one probe-path
  table in `_health`, shared with the service specs); a native entry
  additionally requires the recorded pid alive — a reachable endpoint whose
  recorded pid is gone fails as a foreign process; then leader model
  presence at the recorded Ollama endpoint and the SC2 installation path.
  Without a manifest, checks fall back to option-derived endpoints. Output:
  `True` when every check passes; `cli` exits 1 otherwise. Errors:
  `CommandError` on a corrupt or version-mismatched manifest.
- **run(options) -> None** (`experiment`) — Responsibility: one full experiment game.
  Behavior: precheck the advisor health endpoint and the leader endpoint's
  OpenAI-compatible model list (`GET {base_url}/models` with the bearer key —
  endpoint-agnostic: Ollama, vLLM, or a hosted provider), invoke
  `python -m hima_dht_game` with `--num_server 1` (keeps the
  advisor port independent of `--seed`), stream its output, then archive
  `tmp/{command,input,output,prompt}.txt`, `metric.json`, `frames.jsonl`, and the
  result-named replay into `runs/<replay-stem>/`, and print the metric summary.
  Input: difficulty, enemy race, seed, port, advisor host (default `localhost`,
  forwarded as `--advisor_host` for containerized runs), leader model,
  base URL, API key (default `ollama` — Ollama ignores it; a remote provider
  needs its real key, forwarded as `--LLM_api_key`), realtime flag.
  Errors: `CommandError` on unhealthy services or non-zero exit of `hima_dht_game`.
- **metrics() -> None** (`metrics`) — Behavior: read every `runs/*/metric.json`
  plus an unarchived `tmp/metric.json`, print one aligned table
  (result, time, agent_call, apu, rur, pbr). Errors: none; empty set prints a hint.
- **play(replay_path) -> None** (`replay`) — Behavior: launch the pysc2 human
  renderer with the macOS-required feature-layer flags
  (`--rgb_screen_size 0 --rgb_minimap_size 0`). Errors: `CommandError` when the
  replay file is missing.
- **export(replay_path, sample, out, logs_dir) -> Path** (`viewer`) — Behavior: host
  the replay with `ReplayExporter` (direct `_setup_replay`/`_play_replay` hosting:
  burnysc2 7.3.0 `run_replay` drops `observed_id`, causing `Race.NoRace`), parse
  leader decisions (`output.txt`) and executed commands (`command.txt`) from
  `logs_dir`, write the record file `frames.jsonl` beside the logs (`design-observation.md`),
  inject all data into `player_template.html`, write one standalone
  HTML next to the replay (or `out`). Output: written path.
  Errors: `CommandError` when the replay is missing; engine failures propagate.
- **view(path) -> None** (`viewer`) — Behavior: `export` when given a replay (reuse
  an existing export when present), then open the HTML in the default browser.
- **_serve(host, port) -> None** (`cli`) — Behavior: build the observation app
  via `hima_dht_web.server.create_default_app` and run uvicorn in-process;
  routes and page behavior in `design-observation.md`. Errors: `CommandError`
  when the port is bound (uvicorn's startup-failure exit is mapped, never
  propagated as `SystemExit`).

## Exception / Error Types

- `CommandError(Exception)` — raised by command modules on any user-facing failure
  (missing file, unhealthy service, subprocess failure, a service endpoint
  answered by a process hima does not own, a failed `docker compose`
  invocation, a corrupt or version-mismatched manifest, a held service
  lock, a compose-published port diverging from the requested one, a
  process surviving SIGKILL). `cli` catches it, prints
  the message to stderr, exits 1. All other exceptions propagate with traceback.
