"""Shared fixtures for the Task integration tests."""

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow Home Assistant to load the integration from custom_components."""


@pytest.fixture(autouse=True)
def mock_frontend() -> Generator[None]:
    """Skip registering the Lovelace card; the frontend is not under test."""
    from unittest.mock import patch

    with patch("custom_components.task.add_extra_js_url"):
        yield
