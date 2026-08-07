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
  samples (`src/hima_dht/export.py`); `BotAI` and `ObserverAI` expose that shared surface.
- **[asyncio]** live tail = poll loop: read new lines from a saved byte offset, then
  `await asyncio.sleep(interval)`; no external tailing library.

## Libraries

- fastapi 0.141.1 (locked) — HTTP routes and SSE.
- uvicorn 0.52.1 (locked) — server runner.
- No new dependencies; no `sse-starlette`, no websockets.

## Developer instructions

- Record file writes: hold one file handle, `write` + `flush` per record line.
- Template injection: reuse the placeholder replacement `viewer.py` performs on
  `src/hima_dht/player_template.html`; the server injects per request.
- SSE probe pattern for tests: uvicorn server on a thread, `urllib` client
  (scratchpad `sse_probe.py` shape).

## Design-specific

- Browser side uses the native `EventSource` API; the page enters live mode on the
  payload flag `live: true`.
- Mid-game join without gap: fold the record file's complete lines, remember their
  byte length (`stream.records` in the live payload), start the stream from that
  offset; a trailing line without a newline is mid-write and stays out of both.
- Decision entries span multiple `output.txt` lines, so byte offsets are unsafe for
  logs; the stream re-parses both logs each poll and resumes by entry count.
- Ports 8080, 8765, 8090, 11434 are occupied on the development host; the server
  default port stays off these.
