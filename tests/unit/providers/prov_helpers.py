"""Constants and fakes shared by the provider tests (not a test module)."""
from __future__ import annotations

# Fake keys are assembled at run time so this file never holds a key-shaped literal.
FAKE_ANTHROPIC = "sk-" + "ant-" + "api03-" + "Zq8Lm2" * 5
FAKE_OPENAI = "sk-" + "proj-" + "Ab3dE6" * 6
FAKE_OPENROUTER = "sk-" + "or-v1-" + "0a1b2c3d" * 5
FAKE_GEMINI = "AI" + "za" + "SyD4e5f6" * 5


class FakeKeyring:
    """Stands in for the ``keyring`` module; counts nothing, stores in memory."""

    def __init__(self):
        self.store = {}

    def get_password(self, service, name):
        return self.store.get((service, name))

    def set_password(self, service, name, value):
        self.store[(service, name)] = value

    def delete_password(self, service, name):
        self.store.pop((service, name), None)
