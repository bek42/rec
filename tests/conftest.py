import os

# rec/config.py loads .env at module-import time. Point it at a path that
# doesn't exist so test collection never picks up the developer's real
# repo-root .env — tests must only see explicit env vars / hardcoded defaults.
os.environ.setdefault("ENV_FILE_PATH", "/nonexistent/.env")
