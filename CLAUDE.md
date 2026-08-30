# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`rec` is a single-process background service that forwards receipts/invoices to a
destination email as PDFs. It has **two ingress channels** feeding **one output**:

- **Gmail/IMAP poll** (always on) — watches a Gmail label and `[rec]`-tagged inbox mail.
- **HTTP upload** (optional, `http_enabled=true`) — an authenticated `POST /upload`
  that accepts a receipt photo, e.g. from a phone automation.
- **Output** — each item is normalized to PDF and re-sent over Gmail SMTP to `DEST_EMAIL`.

There is no database and no web framework. State is a flat JSON file.

## Commands

```bash
uv sync                          # install (Python 3.13, uv-managed)
uv run pytest                    # full test suite
uv run pytest tests/test_poller.py::test_forward_upload_sends_and_dedupes  # single test
uv run python main.py            # run the service locally
```

- `test_mode=true` (env) → run one poll cycle and exit.
- Running locally still needs Infisical access (`api_keys.ini` + a reachable
  Infisical project) because Gmail credentials are fetched at runtime — see below.
- Use `.venv/bin/python -m pytest` instead of `uv run` if you want to avoid `uv`
  rewriting `uv.lock`'s self-version.
- No linter is wired into CI. There is a `.ruff_cache/` but no ruff config or dep.

## Architecture

### One thread does the work; the HTTP server only feeds it

`main.py` → `rec/poller.py::run()` is the entire process: a `while True` loop that
calls `process_once()` (IMAP), touches a heartbeat file, and sleeps `POLL_SECONDS`.

When `HTTP_ENABLED`, `run()` also starts `rec/http_server.py` (stdlib
`ThreadingHTTPServer`) in a **daemon thread**. That thread does **not** render or
send anything — its handler validates the request and puts an `HttpUpload` job on
a `queue.Queue`. The main loop drains the queue (`_drain_http_queue` →
`forward_upload`) and does all Playwright/SMTP/state work itself. This split
exists because **Playwright's sync API is bound to the thread that launched
Chromium** (`rec/pdf.py`, module-global singleton browser, `close_browser()`
wired into the SIGTERM handler and loop exit). The request handler blocks until
the loop reports the per-job outcome back through `job.result_q`, so the caller
gets a real `200 forwarded` / `502` / `504`. A failed HTTP-server startup is
caught and the loop continues email-only.

### The shared pipeline seam

Both ingress paths converge on two functions in `rec/poller.py` +
`rec/forwarder.py`:

```
normalize_to_pdfs(subject, sender, date, html_body, text_body,
                  attachments: list[(filename, content_type, bytes)])
    -> list[(filename, pdf_bytes)]
send_with_attachments(smtp_user, smtp_pass, to, subject, body,
                      attachments: list[(filename, pdf_bytes)])
```

- Attachments are always in-memory tuples; no temp files.
- `normalize_to_pdfs`: PDF attachments pass through; images
  (`_IMAGE_TYPES` = jpeg/png/heic/webp) are inlined into a minimal `<img>` HTML
  page and rendered by Chromium; the email body is rendered only when there is no
  PDF/image to carry the receipt; anything else is logged and dropped.
- Output filenames come from `rec/filenames.py::build_filename` →
  `[date]-[sender]-[amount]-[currency].pdf`. Amount/currency are **regex-scraped
  from the subject/body text**, never OCR'd from the image.
- Callers: `process_once()` (email) and `forward_upload()` (HTTP). `forward_upload`
  synthesizes `subject`/`sender`/`date` from the `X-Subject` / `X-Source` headers
  (or falls back to `photo <UTC timestamp>` / `macrodroid` / now).

### IMAP specifics (`rec/imap_watcher.py`)

- Selects `[Gmail]/All Mail`, **not** the watched label, so `-X-GM-LABELS` STOREs
  are honored when relabeling processed mail from `GMAIL_LABEL_IN` to
  `GMAIL_LABEL_OUT`.
- Candidate messages = union of two Gmail `X-GM-RAW` searches:
  `label:<GMAIL_LABEL_IN>` and `in:inbox subject:"<SUBJECT_TRIGGER>"` (default
  `[rec]`, which is also the prefix `rec` puts on everything it forwards).
- Dedup key is Gmail's cross-mailbox-stable `X-GM-MSGID`.

### Config and secrets

- `rec/config.py`: plain `os.getenv` module-level constants. Env var names are
  **lowercase**, Python constants **UPPER_CASE**. `ENV_FILE_PATH` (if set) selects
  a `.env` to load — in prod the container mounts one from the host.
- Secrets are **never** in env or `.env`. `rec/secrets.py` fetches them from
  **Infisical** via `azkees.InfisicalClient`. `.env` holds only the Infisical
  section name (`az-keyvault-smtp`) and the *secret names* to look up
  (`smtp-username`, `smtp-pwd`, `rec-http-token`). `get_gmail_credentials()` and
  `get_http_token()` raise `RuntimeError` rather than degrade if anything is
  missing. `key_http_infisical_section` defaults to the Gmail section.

### State and health

- `rec/state.py`: flat JSON at `DEDUP_STATE_PATH` (`/app/state/dedup_state.json`).
  Keys: `X-GM-MSGID` for email, `http:<sha256(image bytes)>` for uploads (so a
  MacroDroid retry can't double-send). The whole file is loaded, mutated, and
  rewritten per item — safe only because it is single-threaded.
- No HTTP health endpoint. `_touch_heartbeat()` writes `/app/state/heartbeat`
  every loop iteration; the Docker `HEALTHCHECK` fails if its mtime is older than
  `2 * poll_seconds`. CI's deploy verification gates on this.

### Logging

`rec/logging_setup.py` → `log = logpy.log.get_logger(__name__)` (the `pylogpy`
dist imports as `logpy`). Convention: `log.info("<module>: <message>", *args)`,
`log.exception(...)` for caught loop errors, `log.warning(...)` for skips.

## CI/CD

Two workflows in `.github/workflows/`. **Everything is triggered by a push to
`main`; commit subjects MUST be conventional commits** (`feat:` → minor, `fix:` →
patch) or nothing releases.

1. **`bumpversion.yml`** (push to `main`, unless subject starts `bump:`):
   commitizen bumps `pyproject.toml` + regenerates `CHANGELOG.md`, commits
   `bump: …` (pushed with `PERSONAL_ACCESS_TOKEN` so the tag push triggers the
   next workflow), and creates a GitHub Release with tag `vX.Y.Z`.
2. **`release.yml`** (tag `v*`, guarded to `bek42/rec`):
   - **build** — `docker buildx bake debian-multi` (amd64 + arm64) →
     `reg.greatsky.co.uk/rec` (`${{ vars.DOCKERHUB_REPO }}`), tagged `latest` + the version.
   - **deploy** — joins the Tailscale tailnet via GitHub OIDC, then
     `tailscale ssh bharani@$DEPLOY_HOST` ("the robot") into a checkout of the
     **separate `bek42/containers` repo** at `$DEPLOY_PATH`, `sed`s the `image:`
     tag in `rec/docker-compose.yml`, commits/pushes that back, then
     `docker compose pull && up -d`.
   - **verify** — `tailscale ssh` again; asserts the running `rec` container's
     image matches and `State.Health.Status == healthy` (heartbeat healthcheck).

Notes for future changes:

- **`bek42/containers/rec/docker-compose.yml` is hand-maintained.** CI only ever
  rewrites its one `image:` line. Ports and env (`http_enabled=true`,
  `ports: ["127.0.0.1:8080:8080"]`) are one-time manual edits in that repo, not
  something the deploy job injects.
- **`uv.lock`'s self-referential `rec` version lags the bump.** `uv sync --frozen
  --no-install-project` tolerates it (verified); it is periodically resynced with
  a `chore: sync uv.lock` commit.
- Runtime config on the robot: host-mounted `.env` (`ENV_FILE_PATH=/app/.env` from
  `/home/bharani/fin-config/.env`) + host-mounted `api_keys.ini`; state and logs
  on host bind mounts (`/app/state`, `/var/log/rec/`). Container runs **as root**
  (deliberate — avoids uid-mismatch write failures on the bind-mounted
  `/app/state`).
- `docker/Dockerfile.debian` is two-stage: a deps-only `uv sync` layer keyed on
  `pyproject.toml`/`uv.lock` (so editing `rec/*.py` doesn't bust it), then
  `playwright install --with-deps chromium`, then the source copy. `EXPOSE 8080`
  is documentation only.
- `.dockerignore` excludes `tests/`, `*.md`, `docker/`, `.github/` — image size
  and cache keys are unaffected by test/doc changes.

### HTTP ingress in production

The container publishes only `127.0.0.1:8080`. It is exposed to the internet with
**Tailscale Funnel** on the robot (`tailscale funnel --bg 8080` →
`https://<robot>.<tailnet>.ts.net/`), which proxies HTTPS:443 to that local port.
`POST /upload` requires `Authorization: Bearer <rec-http-token>`;
`X-Subject` / `X-Source` headers set the forwarded email subject
(`[rec] <X-Subject>`) and the PDF filename. HEIC is rejected (415) — clients must
send JPEG/PNG.

## Testing conventions

- `pytest` + `pytest-mock`. `tests/conftest.py` sets
  `ENV_FILE_PATH=/nonexistent/.env` so tests never read a real `.env`.
- `tests/test_config.py` tests env parsing by `importlib.reload(config)` inside a
  helper that sets env vars first.
- Playwright is stubbed by `monkeypatch.setattr(poller, "render_html_to_pdf", …)`.
- `normalize_to_pdfs` and `http_server.handle_upload` are written as pure
  functions and tested directly with literal inputs — no sockets, no IMAP/SMTP.
  There are **no IMAP or SMTP integration tests**.
- **CI does not run the test suite.** Tests are a local/dev gate only.
