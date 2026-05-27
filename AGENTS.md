# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

This is **ha-task**, a custom Home Assistant integration (HACS component) for managing recurring household tasks and device maintenance. The entire codebase lives in `custom_components/task/`. There is no `requirements.txt`, `pyproject.toml`, or test suite in this repo.

### Python & Home Assistant version

The code uses PEP 695 `type` statements (Python 3.12+) and HA APIs such as `ConfigSubentryFlow` / `SubentryFlowResult` which require **Home Assistant ≥ 2025.4**. Since HA 2025.2+ requires **Python ≥ 3.13**, you must use a Python 3.13 virtual environment. The update script installs Python 3.13 from `deadsnakes/ppa` and creates a venv at `/workspace/.venv`.

### Running the dev environment

```bash
source /workspace/.venv/bin/activate

# Lint (matches CI)
ruff check custom_components/task/

# Start Home Assistant with the integration loaded
hass -c /workspace/ha-config --skip-pip-packages homeassistant
```

HA will start on `http://localhost:8123`. First run requires onboarding (create user, etc.). The `ha-config/custom_components/task` symlink points back to the repo source so edits are picked up on HA restart.

### Gotchas

- **No automated tests exist** in this repo. CI runs `ruff check` (lint) and HACS/hassfest validation only.
- **DNS resolution errors** (`aiodns` / `getaddrinfo` TypeError) appear in logs at startup — these are harmless in an isolated VM and do not affect the integration.
- **Token expiry**: the HA access token expires after 30 minutes. If you need a fresh token, authenticate again via the REST API (`POST /auth/token` with `grant_type=authorization_code`).
- **Config flow API**: use `POST /api/config/config_entries/flow` (REST) to initiate config flows and `POST /api/config/config_entries/subentries/flow` for subentry flows. WebSocket `config_entries/flow` command is not registered in this HA version.
- **Hot reload**: editing Python source files requires restarting HA (`hass` process). The Lovelace JS card (`www/task-card.js`) is served statically and cached, so append a query param or hard-refresh to pick up changes.
