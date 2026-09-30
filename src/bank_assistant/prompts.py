"""Versioned prompts, stored as files under `prompts/<name>/<version>.md`.

The version (and a hash of the exact text, to catch edits made without bumping the
version) is attached to every trace and evaluation report.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:12]

    @property
    def label(self) -> str:
        return f"{self.name}@{self.version}#{self.sha256}"


def load_prompt(prompts_dir: Path, name: str, version: str) -> Prompt:
    path = prompts_dir / name / f"{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return Prompt(name=name, version=version, text=path.read_text(encoding="utf-8").strip())
