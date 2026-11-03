# Contributing

Thanks for helping with Task. Bug reports and ideas are welcome as [issues](https://github.com/Kogoro/ha-task/issues); for code changes please open a pull request.

## Development setup

Task needs a recent Home Assistant, which requires a recent Python (3.14 for current releases).

```bash
uv venv --python 3.14 .venv
source .venv/bin/activate
uv pip install -r requirements_test.txt
uv pip install "$(python -c "import json, pathlib, homeassistant; print(json.loads((pathlib.Path(homeassistant.__file__).parent / 'components/frontend/manifest.json').read_text())['requirements'][0])")"
```

The second install provides the frontend package that the integration depends on.

## Checks

```bash
ruff check custom_components tests
pytest
```

CI runs the same checks, plus the HACS and hassfest validation.

## Guidelines

- Add or update tests in `tests/` for behaviour changes.
- Put every user-facing text into `strings.json` and both translations (`en`, `de`).
- Keep entity IDs and `unique_id`s stable; changing them orphans users' entities.
- If stored data changes shape, make loading tolerate older data.
- Update the README (and `README.de.md`) when services, entities, events or options change.

## Releases

Bump `version` in `custom_components/task/manifest.json` and the `?v=` of `FRONTEND_SCRIPT_URL` in `__init__.py` (it busts the browser cache of the card), add an entry to `CHANGELOG.md`, then publish a GitHub release tagged `vX.Y.Z`. The release workflow attaches `task.zip`.
