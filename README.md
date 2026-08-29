# rec

Watches a Gmail label for receipts/invoices and forwards each to a destination
email, normalizing to PDF where needed.

## Configuration

Copy `.env.example` to `.env` and fill in the non-secret values. Gmail
credentials (username + App Password) are fetched from Infisical at runtime
via `azkees` — see `.env.example` for the section/key-name indirection.

## Local development

```bash
uv sync
uv run pytest
uv run python main.py
```

Set `test_mode=true` to run a single poll cycle and exit.

## HTTP upload channel

Besides the Gmail watch, `rec` can accept receipt photos over HTTP — e.g. a
phone automation (MacroDroid) that captures a picture and posts it straight to
the container. Uploads go through the same normalize-to-PDF + forward pipeline;
the email flow is unaffected.

Enable it by setting `http_enabled=true` (see `.env.example` for the rest). The
listener is off by default.

**Contract** — `POST /upload`:

| | |
|---|---|
| Auth | `Authorization: Bearer <token>` (token stored in Infisical as `key_http_token`) |
| Body | the image as a raw body (`Content-Type: image/jpeg`/`png`/`webp`) **or** a `multipart/form-data` file field |
| `X-Subject` | optional — used as the email subject and to derive the PDF filename (put the merchant/amount here) |
| `X-Source` | optional — sender label in the filename (default `macrodroid`) |
| Response | `200 {"status":"forwarded","files":[...]}`, or `401` / `413` / `415` / `502` / `504` |

HEIC is rejected — configure the capture to save JPEG or PNG. Identical bytes
are de-duplicated, so a client retry won't double-send.

**Exposing it.** The container listens on `:8080` but publishes nothing itself.
On the deploy host, put it on the internet with Tailscale Funnel (reuses the
existing tailnet, gives automatic HTTPS, no firewall changes):

```bash
tailscale funnel --bg --https=443 http://127.0.0.1:8080
```

For no public exposure, use `tailscale serve` instead and run Tailscale on the
phone — same endpoint, no code change.
