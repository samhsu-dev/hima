# Design — HIMA Operations CLI (`packages/hima-dht-cli/`)

Command interface wrapping the project's internal behaviors: model services, experiment
runs, metric aggregation, replay playback, and replay-to-HTML export. Workspace member
`hima-dht-cli` (`design-packages.md`), import package `hima_dht_cli`, installed as the
`hima` console script. Phases Model and Spec are skipped: pure
infrastructure, no domain semantics, no non-trivial algorithm. Two
subsystems have their own documents: the managed services (placement,
manifest, health, game job) in `design-cli-services.md`, and the game runs
(game placement, observation surface) in `design-cli-run.md`.

## Design Overview

- **Classes**: `ReplayExporter`, `CommandError`, `Placement`; the
  service-subsystem data holders (`ServiceSpec`, `ServiceOptions`,
  `ServiceManifest`, `ModelEndpoint`, `HostService`, `ContainerService`) in
  `design-cli-services.md`; the run holders (`ObservationUI`,
  `ObservationOptions`, `RunOptions`, `ContainerRunOptions`) in
  `design-cli-run.md`.
- **Modules**: `cli` (typer application: one typed command function per
  subcommand), `placement` (the `Placement` value set, shared by the
  service and game axes), `workspace` (run layout), `services` (package:
  public entry `services/__init__`; internals in `design-cli-services.md`),
  `pysc2_play`, `experiment`, `metrics`, `replay`, `export`, `viewer`. The
  observation webui is the separate member `hima-dht-web`
  (`design-observation.md`).
- **Relationships**: `cli` dispatches to every command module (one-way).
  `viewer` uses `export` (frame data) and `hima_dht_web.logs` (decision and
  command parsing). `export` uses `hima_dht_game.sampler` (record file written
  during re-simulation) and `hima_dht_records` (folding).
  `experiment` uses `services`, `replay`, and `workspace`
  (`design-cli-run.md`). `cli`, `services`, and `experiment` use
  `placement`. `export` contains `ReplayExporter`. All command modules use
  `workspace`.
- **Abstract**: `sc2.observer_ai.ObserverAI` (implemented by `ReplayExporter`)
- **Exceptions**: `CommandError` extends `Exception`, raised by every command module,
  handled only in `cli`
- **Dependency roles**: Data holders: the run types (`design-cli-run.md`)
  and the service types (`design-cli-services.md`).
  Orchestrators: `cli.main`; `services._lifecycle` (placement dispatch).
  Helpers: all command modules (stateless functions).
- **Axes**: three independent choices, each with its own option, its own
  environment key, and no value in common with the others, so no flag
  constrains another:
  service placement (`up --services host|container`, `HIMA_SERVICES`,
  default `host`) — where the advisor and webui processes live;
  game placement (`run --game host|container`, `HIMA_GAME`, default
  `container`) — where the SC2 client and the game loop live;
  observation surface (`run --ui none|web|pygui`, `HIMA_UI`, default
  `none`) — how a human watches, if at all. The surfaces read `tmp/` and
  `runs/`, which both game placements write, so every `--ui` value is
  valid with every `--game` value. The retail client's own window is not
  an observation surface: it is the host SC2 engine rendering itself, a
  property of `--game host` alone.
- **Defaults**: `cli` loads `.env` from the working directory on entry;
  argument defaults resolve as CLI flag > exported environment > `.env` >
  code default. Environment lookup is declared per option (typer `envvar`);
  no hand-rolled resolution or conversion. The `HIMA_*` keys are shared with
  docker compose interpolation (`.env.example`); `HIMA_SERVICES`,
  `HIMA_WEBUI`, `HIMA_LEADER_BASE_URL`, and `HIMA_LEADER_API_KEY` join
  them for `up`/`status`, `HIMA_GAME` and `HIMA_UI` for `run`;
  `SC2_LICENSE` enters `run --game container` the same way
  (envvar-backed option, accepted once in `.env`, no code default, never
  persisted by hima). Closed value sets (difficulty, race, placement,
  observation surface) are enums. Core modules never read the environment;
  they receive resolved values.
- **Extension seams**: a new LLM role adds a `ModelEndpoint` row under its
  role key in the manifest `[endpoints]` table plus its own
  `HIMA_<ROLE>_BASE_URL/MODEL/API_KEY` keys — the endpoint-verification
  mechanics are role-agnostic; a new advisor-like service adds
  a `ServiceSpec`, a `_health` probe-path row, and a compose service; a new
  way to watch a game adds an `ObservationUI` value and one `open_surface`
  branch, touching neither placement axis; run
  orchestration variants extend `RunOptions`. The command surface (nine
  domain verbs) does not grow with these extensions. In-game agent society
  changes live in `hima-dht-game`, invisible to deployment.
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

Service-subsystem types: `design-cli-services.md`. Run types:
`design-cli-run.md`.

### Placement (`placement`)
- **Responsibility**: Closed value set naming where a thing runs — `HOST`
  (processes on this machine) or `CONTAINER` (compose services). One type
  serves both axes that have this question, but never one option: `up`
  answers it for the services, `run` answers it for the game, and neither
  reads the other's answer. Persisted in the manifest for the service axis
  so `down`/`status` operate on the recorded placement, never on port
  probing.

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

Each command module exposes one public entry consumed by `cli`. Service
lifecycle entries (`up`, `down`, `status`, `ensure_game_image`, `run_game`):
`design-cli-services.md`. Run entries (`run_host`, `run_container`,
`open_surface`): `design-cli-run.md`.

- **main() -> None** (`pysc2_play`) — Responsibility: run `pysc2.bin.play`
  with the compatibility shims applied in-process. Behavior: replace
  `colors.shuffled_hue` (Python 3.11 removed `random.shuffle`'s `random`
  argument; the shim replicates the wheel's fixed shuffle) and wrap
  `run_configs.get` (a replay version newer than pysc2's table falls back
  to the installed 'latest' build), then invoke the play entry. Runs as a
  subprocess of `replay`; site-packages carries no patches, so `uv sync`
  never needs a follow-up step. s2protocol's Python 3.12 breakage is left
  alone: no code path imports it.
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
  lock, an unreachable leader endpoint or unserved leader model, a
  container game without a manifest or with an unreachable advisor, a
  host-topology
  flag combined with `--game container`, `--ui web` without a running
  webui, a missing game image without `SC2_LICENSE`, a
  process surviving SIGKILL). `cli` catches it, prints
  the message to stderr, exits 1. All other exceptions propagate with traceback.
