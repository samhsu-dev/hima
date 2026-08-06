# Design — HIMA Operations CLI (`cli/`)

Command interface wrapping the project's internal behaviors: model services, experiment
runs, metric aggregation, replay playback, and replay-to-HTML export. Installed as the
`hima` console script via `pyproject.toml`. Phases Model and Spec are skipped: pure
infrastructure, no domain semantics, no non-trivial algorithm.

## Design Overview

- **Classes**: `ServiceSpec`, `ReplayExporter`, `CommandError`
- **Modules**: `main` (dispatch), `workspace` (paths), `services`, `patches`,
  `experiment`, `metrics`, `replay`, `export`, `viewer`
- **Relationships**: `main` dispatches to every command module (one-way).
  `viewer` uses `export` (frame data) and `workspace`. `experiment` uses `services`
  (health precheck) and `workspace`. `services` contains `ServiceSpec`.
  `export` contains `ReplayExporter`. All command modules use `workspace`.
- **Abstract**: `sc2.observer_ai.ObserverAI` (implemented by `ReplayExporter`)
- **Exceptions**: `CommandError` extends `Exception`, raised by every command module,
  handled only in `main`
- **Dependency roles**: Data holders: `ServiceSpec`. Orchestrator: `main.main`.
  Helpers: all command modules (stateless functions).
- **Assets**: `player_template.html` — self-contained canvas player; `viewer` injects
  exported JSON into its placeholder to produce one standalone HTML file per replay.

## Class / Type Specifications

### ServiceSpec (`services`)
- **Responsibility**: Describe one managed background service.
- **Fields**: `name: str`, `argv: list[str]`, `health_url: str`,
  `pid_file: Path`, `log_file: Path`, `process_keyword: str`.
- **Methods**: none (data holder). `process_keyword` guards `stop`: a stored PID is
  killed only when its command line contains this keyword.

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

Each command module exposes one public entry consumed by `main`.

- **setup() -> None** (`patches`) — Responsibility: make a fresh checkout runnable.
  Behavior: run `uv sync`, re-apply the three site-packages source patches
  (idempotent, marker-guarded), verify `sc2`/`pysc2`/`s2protocol` import.
  Errors: `CommandError` on sync failure or failed import.
- **apply_patches() -> list[str]** (`patches`) — Behavior: patch
  `pysc2/lib/colors.py` (Python 3.12 `random.shuffle` removal),
  `pysc2/bin/play.py` (replay version newer than pysc2's table),
  `s2protocol/versions/__init__.py` (`imp` module removal). Output: per-patch status.
  Errors: `CommandError` when a target file is missing.
- **start(port, model, skip_pull) -> None** (`services`) — Behavior: launch the advisor
  FastAPI server (`uvicorn app:app`) and `ollama serve` when not already healthy;
  poll health endpoints a bounded number of attempts; pull the leader model when
  absent unless `skip_pull`. Errors: `CommandError` when health is not reached
  within the attempt bound.
- **stop() -> None** (`services`) — Behavior: terminate PIDs recorded in pid files
  after verifying the process command line matches `process_keyword`; never touches
  other processes. Output: per-service status lines.
- **status(port, model) -> None** (`services`) — Behavior: report advisor health, Ollama
  health, leader model presence, SC2 installation path, and patch state.
- **run(options) -> None** (`experiment`) — Responsibility: one full experiment game.
  Behavior: precheck services, invoke `main.py` with `--num_server 1` (keeps the
  advisor port independent of `--seed`), stream its output, then archive
  `tmp/{command,input,output,prompt}.txt`, `metric.json`, and the result-named
  replay into `runs/<replay-stem>/`, and print the metric summary.
  Input: difficulty, enemy race, seed, port, leader model, base URL, realtime flag.
  Errors: `CommandError` on unhealthy services or non-zero exit of `main.py`.
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
  `logs_dir`, inject all data into `player_template.html`, write one standalone
  HTML next to the replay (or `out`). Output: written path.
  Errors: `CommandError` when the replay is missing; engine failures propagate.
- **view(path) -> None** (`viewer`) — Behavior: `export` when given a replay (reuse
  an existing export when present), then open the HTML in the default browser.

## Exception / Error Types

- `CommandError(Exception)` — raised by command modules on any user-facing failure
  (missing file, unhealthy service, subprocess failure). `main` catches it, prints
  the message to stderr, exits 1. All other exceptions propagate with traceback.
