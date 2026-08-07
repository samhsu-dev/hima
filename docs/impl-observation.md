# Implementation Notes — Game Observation (`design-observation.md`)

## APIs

- **[FastAPI]** `from fastapi.responses import StreamingResponse` —
  `StreamingResponse(gen(), media_type="text/event-stream")` with an async generator
  yielding `event: <kind>\ndata: <json>\n\n`; verified end-to-end on the locked stack
  (curl received correct `text/event-stream` framing).
- **[FastAPI]** `from fastapi.responses import HTMLResponse` — observation page route
  returns the injected template.
- **[uvicorn]** `uvicorn.run(app, host=host, port=port)` — in-process runner for
  `serve()`; a bound port exits via `sys.exit(3)` (`uvicorn.config.STARTUP_FAILURE`),
  never raises `OSError` to the caller — catch `SystemExit` and check `code`.
- **[burnysc2]** sampler reads the same AI fields `ReplayExporter.on_step` already
  samples (`hima_dht_cli.export`); `BotAI` and `ObserverAI` expose that shared surface.
- **[asyncio]** live tail = poll loop: read new lines from a saved byte offset, then
  `await asyncio.sleep(interval)`; no external tailing library.

## Libraries

- fastapi 0.141.1 (locked) — HTTP routes and SSE.
- uvicorn 0.52.1 (locked) — server runner.
- No new dependencies; no `sse-starlette`, no websockets.

## Developer instructions

- Record file writes: hold one file handle, `write` + `flush` per record line.
- Template injection: `server.render` replaces the payload placeholder in
  `hima_dht_web/_resources/templates/player_template.html`; `hima_dht_cli.viewer`
  reuses it for the standalone export.
- SSE probe pattern for tests: uvicorn server on a thread, `urllib` client
  (scratchpad `sse_probe.py` shape).

## Design-specific

- JHU design system source: Johns Hopkins visual identity
  (brand.jhu.edu/visual-identity) — palette and type verified against the local
  render-doc stylesheet; tokens are inlined per page, no external fetch.
- Light tokens: heritage `#002d72`, spirit `#68ace5`, green `#008767`,
  red `#a6192e`, sand `#8a6a2f`, paper `#ffffff`, ink `#1c1a17`,
  ink-quiet `#5d5750`, rule `#c9c5be`, rule-faint `#e6e3dd`, wash `#f5f3ef`.
- Dark tokens: heritage `#9dc4ee`, green `#5cb99f`, red `#e08b7c`,
  sand `#cba052`, paper `#14161a`, ink `#e4e1db`, ink-quiet `#a49e95`,
  rule `#3b3f47`, rule-faint `#262a30`, wash `#1b1e23`; spirit unchanged.
- Type stacks: serif `"Source Serif 4", Charter, Georgia, serif`; sans
  `"Work Sans", "Helvetica Neue", system-ui, sans-serif`; mono
  `ui-monospace, Menlo, monospace`. Named faces degrade to system faces.
- Theme switch: `@media (prefers-color-scheme: dark)` plus `:root[data-theme]`
  overrides in both directions; canvas colors come from
  `getComputedStyle(document.documentElement).getPropertyValue`, re-read on a
  `matchMedia("(prefers-color-scheme: dark)")` change event.
- Browser side uses the native `EventSource` API; the page enters live mode on the
  payload flag `live: true`.
- Mid-game join without gap: fold the record file's complete lines, remember their
  byte length (`stream.records` in the live payload), start the stream from that
  offset; a trailing line without a newline is mid-write and stays out of both.
- Decision entries span multiple `output.txt` lines, so byte offsets are unsafe for
  logs; the stream re-parses both logs each poll and resumes by entry count.
- Ports 8080, 8765, 8090, 11434 are occupied on the development host; the server
  default port stays off these.
