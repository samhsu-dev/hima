# Implementation Notes — Workspace Packages

Verified against uv 0.12.1 (official docs + live test workspace) for
`design-packages.md`.

## APIs

**[uv]** root `pyproject.toml` with `[tool.uv.workspace] members = ["packages/*"]`
and no `[project]` table -- supported virtual root; `uv sync` there installs
every member (editable) plus closures into the single root `.venv`, no
`--all-packages` needed.
**[uv]** `uv run hima` at the virtual root -- works directly once members are
synced; the member must have a `[build-system]` or it is not installed (only
its dependencies are).
**[uv]** member dependency on a sibling: `dependencies = ["hima-dht-records"]`
plus `[tool.uv.sources] hima-dht-records = { workspace = true }` in the
depending member's own pyproject -- a root-level source is optional
deduplication, never required; workspace deps install editable.
**[uv]** `uv sync --locked --package <member>` -- exact-prunes the venv to that
member, its workspace deps, and its third-party closure; root dev group is
pruned, the member's own dev group is kept; add `--no-dev` to drop it.
**[uv]** `uv sync --package <member> --extra <name>` -- applies a member's
optional-dependency group; a member may also depend on
`"hima-dht-cli[advisor]"` with a workspace source. Extras never sync by
default.
**[uv]** root `[dependency-groups] dev` -- installed by default at the virtual
root; member dev groups are installed too (`default-groups` defaults to
`["dev"]`).
**[uv]** interim root-as-member layout (`[project]` + `[tool.uv.workspace]`) --
supported, but plain `uv sync` then installs only the root closure and
uninstalls the members; use `uv sync --all-packages` during the migration.
Converting to a virtual root later: `uv lock` removes the root package entry
cleanly; `uv add` (non-dev) stops working at a non-project root.
**[hatchling]** `packages/<dist>/src/<import_name>/__init__.py` with only
`[build-system] requires = ["hatchling"]` -- wheel auto-detects the src
layout via dash-to-underscore name normalization; no
`[tool.hatch.build.targets.wheel]` needed.
**[pytest]** root `[tool.pytest.ini_options] testpaths = ["packages"]` --
collects every member's tests from the shared venv; per-member run:
`uv run --package <member> pytest`.

## Developer instructions

- One `uv.lock` at the root covers all members; `uv lock` relocks the whole
  workspace.
- Docker per-member image: bind-mount `uv.lock` + pyprojects,
  `uv sync --frozen --no-install-workspace` (deps-only layer), copy
  `packages/`, then `uv sync --locked --package $PACKAGE --no-dev`; set
  `UV_COMPILE_BYTECODE=1` and `UV_LINK_MODE=copy`.
- With the old repo venv active, uv warns `VIRTUAL_ENV ... does not match`
  and ignores it -- harmless; silence with `--active` or by unsetting
  `VIRTUAL_ENV`.
- Root `[tool.uv]` settings (override-dependencies, sources, indexes) and
  root `[dependency-groups]` stay valid on a virtual root.
