"""Guard against committing secrets in the configuration template."""

import re

from tests.helpers import DATA_DIR

ENV_EXAMPLE = DATA_DIR.parent / ".env.example"
SECRET_NAME = re.compile(r"(API_KEY|TOKEN|SECRET)$")


def test_env_example_leaves_every_credential_empty() -> None:
    for number, raw in enumerate(ENV_EXAMPLE.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = (part.strip() for part in line.split("=", 1))
        if SECRET_NAME.search(name):
            assert value == "", f".env.example:{number}: {name} must be empty (it is committed)"
