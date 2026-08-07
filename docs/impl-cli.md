# Implementation — HIMA Operations CLI

Library findings for `design-cli.md`. Verified against local installs and
vendor documentation.

## APIs

- **[python-dotenv]** `from dotenv import load_dotenv; load_dotenv(REPO_ROOT / ".env")` —
  `override=False` (default) keeps exported environment variables ahead of `.env`
  values; a missing file returns `False` silently (no error path needed).
- **[uvicorn]** `python -m uvicorn --factory cli.web.server:create_default_app --host H --port P` —
  `--factory` treats the import string as a zero-argument callable returning the app;
  verified to boot and serve `/api/games` from the workspace layout.
- **[psutil]** `psutil.Process(pid).cmdline()` — raises `psutil.NoSuchProcess` for a
  dead PID; join to one string before keyword matching (`down` PID-reuse guard).

## Libraries

- python-dotenv==1.2.2 — `.env` loading at the CLI entry point. `uv add python-dotenv`.

## Developer instructions

- `.env` is read from `REPO_ROOT`, the same file docker compose interpolates;
  precedence: CLI flag > exported environment > `.env` > code default.
- Environment keys the entry point reads: `HIMA_ADVISOR_HOST`, `HIMA_ADVISOR_PORT`,
  `HIMA_WEBUI_HOST`, `HIMA_WEBUI_PORT`, `HIMA_LEADER_MODEL`, `HIMA_LEADER_BASE_URL`.
- Core modules never read `os.environ`; env-backed values enter through argparse
  defaults in `main` only (`rules/code/constants.md`).
