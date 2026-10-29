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

## Package layout

`rec/` is split into three sub-packages by role:

```
rec/
  core/      config.py  secrets.py  state.py  logging_setup.py  text.py
  ingest/    imap_watcher.py  http_server.py
  pipeline/  poller.py  forwarder.py  filenames.py  ocr.py  pdf.py
```

- **`core/`** — process-wide plumbing with no `rec`-internal deps beyond each
  other (`config` ← `secrets`/`state`/`logging_setup`; `text` is standalone).
- **`ingest/`** — the two request/message readers. Import from `..core` only.
- **`pipeline/`** — normalize-to-PDF, name, and send. `poller.py` is the
  orchestrator and the only module that reaches across into `..ingest`.

Import direction is one-way: `core → ingest → pipeline`. `main.py` →
`rec.pipeline.poller.run()`. Tests import the fully-qualified path
(`rec.pipeline.ocr`, `rec.core.state`, …).

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

`main.py` → `rec/pipeline/poller.py::run()` is the entire process: a `while True`
loop that calls `process_once()` (IMAP), touches a heartbeat file, and sleeps
`POLL_SECONDS`.

When `HTTP_ENABLED`, `run()` also starts `rec/ingest/http_server.py` (stdlib
`ThreadingHTTPServer`) in a **daemon thread**. That thread does **not** render or
send anything — its handler validates the request and puts an `HttpUpload` job on
a `queue.Queue`. The main loop drains the queue (`_drain_http_queue` →
`forward_upload`) and does all Playwright/OCR/SMTP/state work itself. This split
exists because **Playwright's sync API is bound to the thread that launched
Chromium** (`rec/pipeline/pdf.py`, module-global singleton browser,
`close_browser()` wired into the SIGTERM handler and loop exit); Tesseract and
pypdf are subprocess/pure-Python and thread-agnostic but run there anyway. The
request handler blocks until
the loop reports the per-job outcome back through `job.result_q`, so the caller
gets a real `200 forwarded` / `502` / `504`. A failed HTTP-server startup is
caught and the loop continues email-only.

### The shared pipeline seam

Both ingress paths converge on two functions in `rec/pipeline/poller.py` +
`rec/pipeline/forwarder.py`:

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
  PDF/image to carry the receipt; anything else is logged and dropped. When
  there's no genuine PDF attachment and the body has real content (see
  `_body_has_content`) alongside one or more images — a booking confirmation
  with the receipt in the HTML body and a route map attached, say — all of it
  renders as **one** multi-page PDF (`pdf.py::wrap_email_as_html`'s `images`
  param, one `page-break-before` per image) instead of a separate PDF per
  piece: one logical receipt, one file, so there's one thing to upload to an
  expense system instead of two. A
  declared `application/octet-stream` (some senders mislabel photo
  attachments this way — observed from Gmail's own forward of a camera
  upload) is first resolved against the attachment's magic bytes via
  `rec/ingest/http_server.py::sniff_image_type` — the same sniff the HTTP
  upload channel uses — before falling through to "no PDF/image" and
  rendering a near-empty body PDF instead. HEIC is deliberately excluded from
  the sniffed fallback (no browser engine can paint it in an `<img>`, same
  reasoning as the HTTP channel's explicit HEIC rejection). Internally it now
  carries a `(pdf_bytes, doc_text, id_seed)` triple per output so the
  filename can be built per-attachment.
- Output filenames come from `rec/pipeline/filenames.py::build_filename` →
  **`vendor-category-CUR-amount-id.pdf`** (e.g.
  `starbucks-meal-EUR-499-a3f9k.pdf`). The fields are read from the *document*:
  - **image** → Tesseract OCR (`rec/pipeline/ocr.py::ocr_image`, langs `OCR_LANGS`,
    default `eng+deu`). EXIF orientation is corrected (`ImageOps.exif_transpose`)
    before OCR — phone cameras commonly store pixels landscape with the real
    orientation only in EXIF, and without this a portrait photo held sideways
    gets OCR'd sideways into near-garbage text.
  - **PDF attachment** → its embedded text layer (`ocr.py::pdf_text`, pypdf).
  - **rendered email body / no usable text** → fall back to the sender slug +
    the old subject/body amount regex (`extract_amount_and_currency`).
  - `amount` = digits only, last two always the minor unit, left-zero-padded
    to at least 4 digits (`£495.86`→`49586`, `12,00`→`1200`, bare `90`→`9000`,
    `4.99`→`0499`). `currency`: a **non-GBP** amount always
    wins over a GBP one (foreign receipts, Amex/Lloyds statements), tagged with
    the detected code or `EUR` if unresolved; GBP only when it's the sole
    currency; `unknown` when no amount is found at all. `id` = 5 chars of
    `sha1(source-bytes)` — deterministic, so a retry can't rename a duplicate.
  - `category` (ordered keyword match, EN+DE, `misc` default):
    `statement, flight, train, taxi, hotel, fuel, seats, meal`.
  - Any OCR/parse failure returns `""` and degrades to the fallback — it never
    raises into the loop.
  - **Optional OpenAI pass** (`rec/pipeline/llm_classify.py::classify_with_llm`,
    off by default, `OPENAI_ENABLED`): when on, the OCR'd `doc_text` is sent to
    OpenAI (text only — never the image/PDF itself) asking it to read the
    *itemized line items*, not just the vendor/document type, e.g. "2x Flat
    White" → `coffee` rather than the keyword matcher's single `meal` bucket
    (which has no `coffee`/`water` split and doesn't contain "flat white" at
    all). The vendor is capped to 2 words / 20 chars (prompted for a short
    brand name, e.g. `MINT42` not `Genuss & Harmonie / MINT42`, and
    truncated as a safety net regardless of what comes back) then run through
    the same `sanitize_slug` every regex-derived vendor gets — the first live
    response returned `Genuss & Harmonie` unsanitized straight into a
    filename before this was added. `build_filename`'s `llm_fields` param
    takes whichever of vendor/category/currency/amount it returns and falls
    back to the regex path per-field for the rest. A category outside the
    configured `RECEIPT_CATEGORIES` list is dropped (treated as not
    returned). Every
    failure mode (disabled, no key, network, timeout, bad JSON) returns
    `None` — same "never raises into the loop" contract as OCR itself. Only
    called when `doc_text` is non-empty (image/PDF path) — never for a
    rendered-email-body-only output, which has nothing itemized to read.
    **Tried local Ollama on the robot first** (both a vision model reading
    the photo directly, and a small text model reading OCR'd text) — ruled
    out empirically: a vision model took >15 minutes per receipt and pegged
    all 4 CPU cores hard enough to degrade rec's own services; even a 1.7B
    text model misclassified an unambiguous coffee receipt twice in a row
    despite explicit prompting. The robot is ARM/CPU-only, no GPU.
- Callers: `process_once()` (email) and `forward_upload()` (HTTP). `forward_upload`
  synthesizes `subject`/`sender`/`date` from the `X-Subject` / `X-Source` headers
  (or falls back to `photo <UTC timestamp>` / `macrodroid` / now).

### IMAP specifics (`rec/ingest/imap_watcher.py`)

- Selects `[Gmail]/All Mail`, **not** the watched label, so `-X-GM-LABELS` STOREs
  are honored when relabeling processed mail from `GMAIL_LABEL_IN` to
  `GMAIL_LABEL_OUT`.
- Candidate messages = union of two Gmail `X-GM-RAW` searches:
  `label:<GMAIL_LABEL_IN>` and `in:inbox subject:"<SUBJECT_TRIGGER>"` (default
  `[rec]`, which is also the prefix `rec` puts on everything it forwards).
- Dedup key is Gmail's cross-mailbox-stable `X-GM-MSGID`.

### Config and secrets

- `rec/core/config.py`: plain `os.getenv` module-level constants. Env var names
  are **lowercase**, Python constants **UPPER_CASE**. `ENV_FILE_PATH` (if set)
  selects a `.env` to load — in prod the container mounts one from the host.
  OCR knobs: `ocr_enabled` (default `true`), `ocr_langs` (`eng+deu`),
  `tesseract_cmd` (empty → PATH), `ocr_timeout` (`30`s). `http_upload_path`
  (default `upload`, leading/trailing `/` stripped) overrides the single
  accepted `POST` path — set it to an unguessable value when the endpoint sits
  behind a public reverse proxy that skips bot-challenge middleware for one
  exact path (see "HTTP ingress in production"). `http_result_timeout`
  (default `120`s) is how long the HTTP handler waits for the poll-loop
  thread's result before returning 504 — padded above bare render+SMTP cost
  to leave room for an OpenAI call, not sized for a local Ollama's
  minutes-per-receipt (see below). OpenAI knobs: `openai_enabled` (default
  `false`), `openai_model` (default `gpt-4o-mini` — verify against current
  OpenAI pricing before trusting the default), `openai_timeout` (`30`s),
  `receipt_categories` (comma-separated, default
  `coffee,water,meal,taxi,train,flight,hotel,fuel,seats,statement,misc`).
- Secrets are **never** in env or `.env`. `rec/core/secrets.py` fetches them from
  **Infisical** via `azkees.InfisicalClient`. `.env` holds only the Infisical
  section name (`az-keyvault-smtp`) and the *secret names* to look up
  (`smtp-username`, `smtp-pwd`, `rec-http-token`). `get_gmail_credentials()` and
  `get_http_token()` raise `RuntimeError` rather than degrade if anything is
  missing. `key_http_infisical_section` defaults to the Gmail section.
  **Exception**: `openai_api_key` is read directly from the process
  environment (`OPENAI_API_KEY` config var) rather than through
  `secrets.py`/Infisical — there's no Infisical entry set up for it yet. In
  prod it's delivered via a host-side secrets `env_file`
  (`/home/bharani/secrets/rec-openai-api-key.env`, same convention
  `bek42/containers` already uses for e.g. Cloudflare tokens), not the
  mounted fin-config `.env` — the value still never touches git.

### State and health

- `rec/core/state.py`: flat JSON at `DEDUP_STATE_PATH` (`/app/state/dedup_state.json`).
  Keys: `X-GM-MSGID` for email, `http:<sha256(image bytes)>` for uploads (so a
  MacroDroid retry can't double-send). The whole file is loaded, mutated, and
  rewritten per item — safe only because it is single-threaded.
- No HTTP health endpoint. `_touch_heartbeat()` writes `/app/state/heartbeat`
  every loop iteration; the Docker `HEALTHCHECK` fails if its mtime is older than
  `2 * poll_seconds`. CI's deploy verification gates on this.

### Logging

`rec/core/logging_setup.py` → `log = logpy.log.get_logger(__name__)` (the `pylogpy`
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
  `pyproject.toml`/`uv.lock` (so editing `rec/**/*.py` doesn't bust it), then an
  `apt-get install tesseract-ocr tesseract-ocr-{eng,deu}` layer, then
  `playwright install --with-deps chromium`, then the source copy. The two apt
  layers are kept separate so bumping one doesn't invalidate the other.
  `pillow`/`pypdf` are pure-Python wheels (no system packages). `EXPOSE 8080` is
  documentation only.
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
- `tests/test_config.py` tests env parsing by `importlib.reload(config)` (imported
  as `from rec.core import config`) inside a helper that sets env vars first.
- Playwright is stubbed by `monkeypatch.setattr(poller, "render_html_to_pdf", …)`;
  OCR by `_stub_ocr` (`monkeypatch.setattr(poller, "ocr_image"/"pdf_text", …)`) —
  the test suite never needs a real `tesseract` binary.
- `normalize_to_pdfs`, `http_server.handle_upload`, and the `ocr.py` heuristics
  (`classify_category`, `extract_vendor`, `extract_amount_and_currency`,
  `filenames.build_filename`) are pure functions tested directly with literal
  inputs — no sockets, no IMAP/SMTP, no images. There are **no IMAP or SMTP
  integration tests**.
- **CI does not run the test suite.** Tests are a local/dev gate only.
