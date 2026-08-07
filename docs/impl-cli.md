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

## Libraries

- python-dotenv==1.2.2 — `.env` loading at the CLI entry point. `uv add python-dotenv`.
- typer==0.27.1 — CLI parsing, env-backed option defaults. `uv add typer`;
  already in `uv.lock` transitively via transformers at the same version.

## Developer instructions

- `.env` is read from `REPO_ROOT`, the same file docker compose interpolates;
  precedence: CLI flag > exported environment > `.env` > code default.
- Environment keys the entry point reads: `HIMA_ADVISOR_HOST`, `HIMA_ADVISOR_PORT`,
  `HIMA_WEBUI_HOST`, `HIMA_WEBUI_PORT`, `HIMA_LEADER_MODEL`, `HIMA_LEADER_BASE_URL`.
- Core modules never read `os.environ`; env-backed values enter through typer
  `envvar` option declarations in `cli` only (`rules/code/constants.md`).
