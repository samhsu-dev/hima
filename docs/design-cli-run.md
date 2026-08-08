# Design — CLI Game Runs (`hima_dht_cli.experiment`)

Run subsystem of the operations CLI: the game-placement axis and the
observation axis. Command surface, defaults, and the axis overview:
`design-cli.md`. Managed services and the game job it calls:
`design-cli-services.md`. Deployment artifacts: `design-deployment.md`.

## Design Overview

- **Classes**: `ObservationUI`, `ObservationOptions`, `RunOptions`,
  `ContainerRunOptions`; the placement value set `Placement`
  (`hima_dht_cli.placement`, `design-cli.md`).
- **Modules**: `experiment` (public entries `run_host`, `run_container`,
  `open_surface`).
- **Relationships**: `experiment` uses `services` (health precheck,
  manifest read, container game job), `replay` (the pygui surface),
  `workspace` (run layout), and `placement`; `experiment` contains
  `ObservationUI`, `ObservationOptions`, `RunOptions`, and
  `ContainerRunOptions`. `RunOptions` and `ContainerRunOptions` each
  contain one `ObservationOptions`.
- **Dependency roles**: Data holders: `ObservationOptions`, `RunOptions`,
  `ContainerRunOptions`. Helpers: `experiment` entries (stateless
  functions; `cli` dispatches on the resolved game placement).
- **Exceptions**: `CommandError` on every user-facing failure, handled only
  in `cli` (`design-cli.md`).
- **Independence**: the game placement and the observation surface never
  read each other. Both surfaces consume the `runs/` and `tmp/` trees,
  which a host game and a container game write alike, so every `--ui`
  value is valid with every `--game` value. The retail client's own window
  is not a surface — it is the host SC2 engine rendering itself.

## Class / Type Specifications

### ObservationUI (`experiment`)
- **Responsibility**: Closed value set naming the observation surface a run
  opens — `NONE` (default: the run prints its summary and nothing opens),
  `WEB` (the browser page served by the managed webui, live during the
  game), `PYGUI` (the pysc2 renderer on the archived replay, after the
  game).

### ObservationOptions (`experiment`)
- **Responsibility**: The observation choice for one run, carried as one
  field by both run option holders so neither repeats the pair.
- **Fields**: `ui: ObservationUI`, `webui_url: str` (where `WEB` looks for
  a page; the same host-published endpoint `up` records, whichever
  placement served it).
- **Methods**: none (data holder).

### RunOptions (`experiment`)
- **Responsibility**: One host game's settings, resolved by `cli` through
  the configuration chain.
- **Fields**: difficulty, enemy race, seed, port, advisor host (default
  `localhost`, forwarded as `--advisor_host`), leader model, leader base
  URL, leader API key (default `ollama` — Ollama ignores it; a remote
  provider needs its real key, forwarded as `--LLM_api_key`), realtime
  flag, `observation: ObservationOptions`.
- **Methods**: none (data holder).

### ContainerRunOptions (`experiment`)
- **Responsibility**: One container game's settings: what to forward into
  the job, plus what the host itself checks before starting it.
- **Fields**: the game-semantic flags the user passed explicitly on the
  host command line (forwarded verbatim as an in-container `hima run`
  command override; `cli` derives them from click's parameter source, so
  environment- and default-sourced values never freeze into container
  flags), the resolved leader model and API key for the host-side
  precheck, the `SC2_LICENSE` value (envvar-backed option, never
  persisted), `observation: ObservationOptions`.
- **Methods**: none (data holder).

## Function Specifications

- **run_host(options) -> None** — Responsibility: one full experiment game
  on this machine. Behavior: open the pre-game observation surface, precheck
  the advisor health endpoint and the leader endpoint's OpenAI-compatible
  model list (`GET {base_url}/models` with the bearer key —
  endpoint-agnostic: Ollama, vLLM, or a hosted provider), invoke
  `python -m hima_dht_game` with `--num_server 1` (keeps the advisor port
  independent of `--seed`), stream its output, then archive
  `tmp/{command,input,output,prompt}.txt`, `metric.json`, `frames.jsonl`,
  and the result-named replay into `runs/<replay-stem>/`, print the metric
  summary, and open the post-game surface. Input: `RunOptions`. Output:
  none. Errors: `CommandError` on unhealthy services or a non-zero exit of
  `hima_dht_game`.
- **run_container(options) -> None** — Responsibility: one containerized
  experiment game, the default game placement. Behavior: require a manifest
  recording the `CONTAINER` service placement (the job joins the compose
  network and reaches the advisor by service name; no implicit placement
  switch), open the pre-game surface, precheck the recorded leader
  `ModelEndpoint` from the host (`GET {url}/models` with the
  chain-resolved bearer key, listing the resolved model), ensure the game
  image (`ensure_game_image`), then run the game job (`run_game`),
  streaming output; the in-container `hima run` archives under the
  bind-mounted `runs/` and prints the metric summary itself, so the
  post-game surface opens on the newest `runs/` entry. Input:
  `ContainerRunOptions`. Output: none. Errors: `CommandError` on a missing
  or host-placement manifest, an unreachable leader endpoint or unserved
  model, a missing game image without `SC2_LICENSE`, a failed build, or a
  non-zero game exit.
- **open_surface(options, phase, run_dir) -> None** — Responsibility: open
  the requested observation surface at the point in a run where it can show
  something. Behavior: `NONE` returns; `WEB` opens before the game — verify
  the webui endpoint answers, then open the live page in the default
  browser; `PYGUI` opens after the game — hand the archived replay to
  `replay.play`. A phase the surface does not use is a no-op, so both run
  entries call it before and after unconditionally. Input:
  `ObservationOptions`, the run phase, the archive directory (absent
  before the game). Output: none. Errors: `CommandError` when `WEB` finds
  no webui answering, naming `hima up --webui` as the fix — an observation
  the user asked for and cannot get is a failed request, not a silent
  downgrade.

## Exception / Error Types

- `CommandError` — the CLI-wide user-facing failure type; raising sites
  above, full catalog and handling in `design-cli.md`.
