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
