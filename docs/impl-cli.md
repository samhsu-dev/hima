# Implementation — HIMA Operations CLI

Library findings for `design-cli.md`. Verified against local installs and
vendor documentation.

## APIs

- **[python-dotenv]** `from dotenv import load_dotenv; load_dotenv(REPO_ROOT / ".env")` —
  `override=False` (default) keeps exported environment variables ahead of `.env`
  values; a missing file returns `False` silently (no error path needed).
- **[uvicorn]** `python -m uvicorn --factory hima_dht.web.server:create_default_app --host H --port P` —
  `--factory` treats the import string as a zero-argument callable returning the app;
  verified to boot and serve `/api/games` from the workspace layout.
- **[psutil]** `psutil.Process(pid).cmdline()` — raises `psutil.NoSuchProcess` for a
  dead PID; join to one string before keyword matching (`down` PID-reuse guard).
- **[psutil]** `psutil.AccessDenied` — raised when the pid was reused by another
  user's process; not a `NoSuchProcess` subclass, catch it separately.
  `ZombieProcess` is a `NoSuchProcess` subclass. `psutil.pid_exists(pid)` is the
  bare liveness test (`status` foreign-process check).
- **[os]** `os.getpgid(pid) == pid` — process-group-leader test;
  `start_new_session=True` at spawn makes the child its own group leader, and
  `os.killpg(pid, sig)` then signals the whole group (ollama's model-runner
  children).
- **[fcntl]** `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)` — raises
  `BlockingIOError` when held; releases on close or process exit, so a crashed
  holder never wedges the lock. Conflicts between two open file descriptions
  even within one process (testable without a second process).
- **[pathlib]** `Path.replace(target)` — atomic rename on the same filesystem;
  scratch file + replace persists the manifest without torn writes.
- **[requests]** `response.ok` — status < 400; a foreign server's 404 on the
  health path is not health.
- **[typer]** `typer.Typer(add_completion=False, pretty_exceptions_enable=False)` —
  default standalone mode prints concise usage errors and exits 2; a plain
  `CommandError` raised in a command propagates out of `app()` for `main()` to
  catch (exit 1, no traceback).
- **[typer]** `typer.Option(default, envvar="HIMA_X")` — resolves flag >
  exported environment > declared default; a non-int env value is reported as a
  usage error naming the env var. With `load_dotenv(override=False)` before
  `app()`, exported environment stays ahead of `.env`.
- **[typer]** snake_case parameters become kebab-case options
  (`advisor_port` → `--advisor-port`); a `str`-Enum parameter renders its values
  as choices; a bool option with an explicit `"--realtime"` name suppresses the
  `--no-realtime` pair; `Annotated[T, typer.Option(...)]` is the documented
  parameter style.
- **[tomli-w]** `tomli_w.dumps(doc)` — nested dicts become `[section]` /
  `[section.sub]` tables; round-trips with stdlib `tomllib.loads` (verified);
  `None` values are unsupported — omit absent keys instead.
- **[docker compose]** `docker compose ps --format json` — NDJSON, one object
  per line with `Service` and `Name` keys, since v2.21; earlier versions emit
  one JSON array — parse both (verified against compose 5.1.2);
  `up -d --wait` blocks on healthchecks (services without one wait for
  running) and needs no extra timeout — healthcheck retries bound it.
- **[docker compose]** `docker compose run --rm <service>` — propagates the
  container's exit code verbatim (verified: exit 7 → 7); argv after the
  service name overrides the compose-file `command` for that invocation
  only; `depends_on` services are started and waited on. Targeting a
  profiled service auto-activates its profile — hima still passes
  `--profile game` explicitly.
- **[docker]** `docker image inspect <name>` — exit 0 when the image exists
  locally, 1 when absent (verified); the game-image presence probe.
- **[click]** `ctx.get_parameter_source("param")` on a `typer.Context`
  parameter — returns `ParameterSource.COMMANDLINE`, `.ENVIRONMENT`, or
  `.DEFAULT` (verified, click 8.4 via typer 0.27); distinguishes an explicit
  flag from env/default values for headless flag forwarding. typer 0.27
  vendors click as `typer._click` with no public re-export: import
  `ParameterSource` from `typer._click.core` — the standalone `click`
  distribution's enum is a different class, so identity checks against it
  always fail (verified via mypy comparison-overlap and at runtime).
- **[ollama]** `OLLAMA_HOST=127.0.0.1:<port>` — environment consumed by both
  `ollama serve` (bind address) and the `ollama pull` client (target server).

## Libraries

- python-dotenv==1.2.2 — `.env` loading at the CLI entry point. `uv add python-dotenv`.
- typer==0.27.1 — CLI parsing, env-backed option defaults. `uv add typer`;
  already in `uv.lock` transitively via transformers at the same version.
- tomli-w==1.2.0 — service manifest TOML writing (stdlib `tomllib` reads).
  `uv add --package hima-dht-cli tomli-w`.

## Developer instructions

- `.env` is read from `REPO_ROOT`, the same file docker compose interpolates;
  precedence: CLI flag > exported environment > `.env` > code default.
- Environment keys the entry point reads: `HIMA_ADVISOR_HOST`, `HIMA_ADVISOR_PORT`,
  `HIMA_WEBUI_HOST`, `HIMA_WEBUI_PORT`, `HIMA_LEADER_MODEL`, `HIMA_LEADER_BASE_URL`,
  `HIMA_LEADER_API_KEY`, `HIMA_SERVICE_BACKEND`, `HIMA_OLLAMA_PORT`, and
  `SC2_LICENSE` (`run --headless` only; no default, never persisted).
- `docker compose` subprocesses run with `cwd=RUN_ROOT`; the docker backend
  requires `docker-compose.yml` in the run root.
- Core modules never read `os.environ`; env-backed values enter through typer
  `envvar` option declarations in `cli` only (`rules/code/constants.md`).
