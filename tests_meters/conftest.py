"""The live meters (meters.py and its websocket command), against a small fake processor run here with aiohttp.
These need no processor software, so they run everywhere (the full tests in tests/ need plus-audio-bmp)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations, socket_enabled):
    yield
