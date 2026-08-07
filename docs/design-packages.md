# Design — Workspace Packages (`packages/`)

Repository-level software structure: the uv workspace, its member packages, and
the contracts between them. Per-member internals: `design-cli.md`,
`design-observation.md`, `design-deployment.md`. Deployment concepts:
`concept-deployment.md`.

## Design Overview

- **Packages**: `hima-dht-records`, `hima-dht-game`, `hima-dht-web`,
  `hima-dht-cli` — workspace members under `packages/<dist-name>/`
  with import packages `hima_dht_records`, `hima_dht_game`, `hima_dht_web`,
  `hima_dht_cli` under `src/`.
- **Relationships** (one-way, declared in member metadata):
  - `hima-dht-game` uses `hima-dht-records` (writes record files)
  - `hima-dht-web` uses `hima-dht-records` (reads and folds record files)
  - `hima-dht-cli` uses `hima-dht-game`, `hima-dht-web`, `hima-dht-records`
  - `hima-dht-records` uses no internal package
- **Dependency roles**: Contract holder: `hima-dht-records`. Orchestrator:
  `hima-dht-cli`. Service: `hima-dht-web`. Game runtime and advisor service:
  `hima-dht-game` (the advisor's heavy closure sits behind the `advisor`
  extra so game-only installs stay slim).
- **Root**: virtual workspace root — `pyproject.toml` with `[tool.uv.workspace]`
  (members `packages/*`), the shared dependency groups (`dev`, and `advisor` =
  `hima-dht-game[advisor]`, both in `default-groups` so plain `uv sync` readies
  the native-advisor dev machine), resolution overrides (`s2clientprotocol`
  exclusion, torch CPU index), and pytest configuration.
  One `uv.lock`, one `.venv`. The root is not a distribution.

## Package Specifications

### hima-dht-records
- **Responsibility**: The observation record contract shared by writer and
  readers: record file name, record schema constants, folding into the game
  payload, and the run-layout directory names where record files land.
- **Modules**: `records.py` (public; re-exported from `__init__.py`).
- **Contents**: `RECORD_FILE`, `RUNS_DIRNAME`, `TMP_DIRNAME`,
  `DEFAULT_SAMPLE_INTERVAL`, `FRAME_FIELDS`, `fold_records`, `fold_lines`.
- **Third-party closure**: none (stdlib only).

### hima-dht-game
- **Responsibility**: The StarCraft II game runtime — game entry, the HIMA
  bot, race bots and agent baselines, prompts, action vocabulary, record
  sampling during play — and the advisor inference service the bot's agent
  logic talks to. Co-located on user decision: agent-logic changes evolve
  the bot side and the advisor interface together, in one package.
- **Modules**: `main.py` (entry: argument parsing + `main()`), `__main__.py`
  (`sys.exit(main())`), `bot.py`, `sampler.py` (`GameSampler`, moved from the
  web records module — the sc2-dependent record writer), `utils.py`,
  `constants.py`, `prompt.py`, `bots/`, `prompts/`; `app.py` (the advisor
  service: model trio constant, model loading, serialized generation — MPS
  single-worker constraint — request schema, routes, `create_app(advisors)`
  and the zero-argument `create_default_app`). `app.py` is addressed by
  module path only, never imported by `__init__.py` or the game modules: it
  needs the `advisor` extra, and bot↔advisor interaction stays HTTP.
- **Invocation**: game — `python -m hima_dht_game`; output folders resolve
  from `--save_path` as given (absolute, or relative to the invoking
  process's working directory); the package never computes a repository
  root. Advisor — `uvicorn --factory hima_dht_game.app:create_default_app`;
  models load in the application lifespan: import stays side-effect free and
  `/health` reachability still implies readiness.
- **Value placement**: the model trio is a constant (no run overrides it);
  no new run-settings.
- **Third-party closure**: burnysc2, numpy, openai, requests; `advisor`
  extra adds fastapi, uvicorn, pydantic, transformers, torch, accelerate.

### hima-dht-web
- **Responsibility**: The observation webui: game store, payload endpoints,
  live stream, log parsing, page serving.
- **Modules**: `server.py`, `games.py`, `logs.py`, `stream.py` (unchanged
  split; `records.py` leaves for the records and game packages); asset
  `_resources/templates/player_template.html` read via `importlib.resources`
  — `server.render` injects payloads for the observation page and for
  `hima_dht_cli.viewer`'s standalone export.
- **Invocation**: `uvicorn --factory hima_dht_web.server:create_default_app`;
  the factory anchors `runs/` and `tmp/` to the working directory using the
  run-layout names from `hima_dht_records`.
- **Third-party closure**: fastapi, uvicorn.

### hima-dht-cli
- **Responsibility**: The `hima` operations CLI: managed services, experiment
  runs, metrics, site-package patches, replay tools, page export.
- **Modules**: `cli.py` (entry, `[project.scripts] hima`), `services.py`,
  `experiment.py`, `metrics.py`, `patches.py`, `replay.py`, `export.py`,
  `viewer.py`, `workspace.py`, `errors.py`.
- **Run layout**: `workspace.py` anchors `tmp/`, `runs/`, and the service
  state directory to the invoking process's working directory (`RUN_ROOT`);
  `hima` runs from the repository root or any chosen run directory. The
  repository-root path arithmetic is removed. `SC2_APP` stays an absolute
  macOS constant.
- **Extras**: `advisor` — installs `hima-dht-game[advisor]` for host-native
  `hima up` advisor launch; absent in the game image.
- **Third-party closure**: burnysc2, pysc2, pys2clientprotocol, s2protocol,
  mpyq, psutil, pygame, python-dotenv, requests, typer, uvicorn (the in-process
  `hima serve` runner).

## Contracts

- **Record contract** (`hima-dht-records`): record file name, schema constants,
  folding semantics, and run-layout directory names. Writer (`sampler.py` in
  the game package) and readers (web, cli export) both import it; neither owns
  it.
- **Run layout**: every entry point (cli, web factory) anchors the layout to
  its working directory. Compose services receive the layout through
  `WORKDIR` and bind mounts; native runs receive it by invoking `hima` at the
  repository root.
- **Run-settings** (`.env`): the `HIMA_*` keys and precedence are unchanged
  (`design-cli.md`); the `.env` file is read from the working directory.
- **HTTP contracts**: advisor and web endpoint paths, schemas, and the
  `Suggestion A/B/C` aggregation format are unchanged.

## Image Mapping

One image per service (`design-deployment.md`): advisor image installs
`hima-dht-game[advisor]`; webui image installs `hima-dht-web`; game image
installs `hima-dht-cli` without the `advisor` extra. Each install is the
member plus its dependency closure, nothing else.

## Distribution Policy

Members are deployment products, not published distributions: none uploads to
an index; version streams stay at `0.1.0` until a release decision exists.

## Exception / Error Types

Unchanged: `CommandError` stays in `hima_dht_cli.errors`; service HTTP errors
stay with their packages (`design-cli.md`, `design-observation.md`).
