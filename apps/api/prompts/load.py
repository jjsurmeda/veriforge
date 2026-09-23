"""Load a versioned prompt file, stripping its `---` front matter header.

python.md: every prompt starts with a version header; the header is for
eval diffs, never part of the prompt text sent to the model.
"""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt(name: str) -> str:
    text = (_PROMPTS_DIR / name).read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()
