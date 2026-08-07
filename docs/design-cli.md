# Design — HIMA Operations CLI (`packages/hima-dht-cli/`)

Command interface wrapping the project's internal behaviors: model services, experiment
runs, metric aggregation, replay playback, and replay-to-HTML export. Workspace member
`hima-dht-cli` (`design-packages.md`), import package `hima_dht_cli`, installed as the
`hima` console script. Phases Model and Spec are skipped: pure
infrastructure, no domain semantics, no non-trivial algorithm.

## Design Overview

- **Classes**: `ServiceSpec`, `ServiceOptions`, `ReplayExporter`, `CommandError`
- **Modules**: `cli` (typer application: one typed command function per
  subcommand), `workspace` (run layout), `services`, `patches`,
  `experiment`, `metrics`, `replay`, `export`, `viewer`. The observation webui
  is the separate member `hima-dht-web` (`design-observation.md`).
- **Relationships**: `cli` dispatches to every command module (one-way).
  `viewer` uses `export` (frame data) and `hima_dht_web.logs` (decision and
  command parsing). `export` uses `hima_dht_game.sampler` (record file written
  during re-simulation) and `hima_dht_records` (folding).
  `experiment` uses `services` (health precheck) and `workspace`. `services`
  contains `ServiceSpec` and uses `hima_dht_web.server` (webui default port and
  app factory for the managed webui). `export` contains `ReplayExporter`. All
  command modules use `workspace`.
- **Abstract**: `sc2.observer_ai.ObserverAI` (implemented by `ReplayExporter`)
- **Exceptions**: `CommandError` extends `Exception`, raised by every command module,
  handled only in `cli`
- **Dependency roles**: Data holders: `ServiceSpec`, `ServiceOptions`.
  Orchestrator: `cli.main`. Helpers: all command modules (stateless functions).
- **Defaults**: `cli` loads `.env` from the working directory on entry;
  argument defaults resolve as CLI flag > exported environment > `.env` >
  code default. Environment lookup is declared per option (typer `envvar`);
  no hand-rolled resolution or conversion. The `HIMA_*` keys are shared with
  docker compose interpolation (`.env.example`). Closed value sets
  (difficulty, race) are enums. Core modules never read the environment;
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

### ServiceSpec (`services`)
- **Responsibility**: Describe one managed background service.
- **Fields**: `name: str`, `argv: list[str]`, `health_url: str`,
  `pid_file: Path`, `log_file: Path`, `process_keyword: str`.
- **Methods**: none (data holder). `process_keyword` guards `down`: a stored PID is
  killed only when its command line contains this keyword.

### ServiceOptions (`services`)
- **Responsibility**: Endpoint and model selection for the managed services,
  resolved by `cli` and passed as one parameter object.
- **Fields**: `advisor_port: int`, `webui_port: int`, `model: str` — each
  defaulting to the owning module's constant.
- **Methods**: none (data holder).

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

- **setup() -> None** (`patches`) — Responsibility: make a fresh checkout runnable.
  Behavior: run `uv sync`, re-apply the three site-packages source patches
  (idempotent, marker-guarded), verify `sc2`/`pysc2`/`s2protocol` import.
  Errors: `CommandError` on sync failure or failed import.
- **apply_patches() -> list[str]** (`patches`) — Behavior: patch
  `pysc2/lib/colors.py` (Python 3.12 `random.shuffle` removal),
  `pysc2/bin/play.py` (replay version newer than pysc2's table),
  `s2protocol/versions/__init__.py` (`imp` module removal). Output: per-patch status.
  Errors: `CommandError` when a target file is missing.
- **up(options, skip_pull) -> None** (`services`) — Behavior: ensure the managed
  services in dependency order — `ollama serve`, the leader model (pulled when
  absent unless `skip_pull`), the advisor FastAPI server (`uvicorn --factory` on
  `hima_dht_advisor.server`), the
  observation webui (`uvicorn --factory` on `hima_dht_web.server`) — skipping any service
  already healthy; poll health endpoints a bounded number of attempts.
  Errors: `CommandError` when health is not reached within the attempt bound.
- **down() -> None** (`services`) — Behavior: terminate PIDs recorded in pid files in
  reverse launch order (webui, advisor, ollama) after verifying the process command
  line matches `process_keyword`; never touches other processes. Output: per-service
  status lines.
- **status(options) -> None** (`services`) — Behavior: report advisor health, webui
  health, Ollama health, leader model presence, SC2 installation path, and patch state.
- **run(options) -> None** (`experiment`) — Responsibility: one full experiment game.
  Behavior: precheck services, invoke `python -m hima_dht_game` with `--num_server 1` (keeps the
  advisor port independent of `--seed`), stream its output, then archive
  `tmp/{command,input,output,prompt}.txt`, `metric.json`, `frames.jsonl`, and the
  result-named replay into `runs/<replay-stem>/`, and print the metric summary.
  Input: difficulty, enemy race, seed, port, advisor host (default `localhost`,
  forwarded as `--advisor_host` for containerized runs), leader model,
  base URL, realtime flag.
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
  (missing file, unhealthy service, subprocess failure). `cli` catches it, prints
  the message to stderr, exits 1. All other exceptions propagate with traceback.
