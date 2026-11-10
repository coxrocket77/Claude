"""Model wiring. One place to pick models and build judges."""
from __future__ import annotations

import os
from pathlib import Path

from .classify import (REVIEWER_SYSTEM, ClaudeClassifier, GLReviewer, HeuristicClassifier)

CLASSIFIER_MODEL = os.environ.get("RECOUP_CLASSIFIER_MODEL", "claude-sonnet-5-5")
REVIEWER_MODEL = os.environ.get("RECOUP_REVIEWER_MODEL", "claude-opus-5-5")
PROPOSER_MODEL = os.environ.get("RECOUP_PROPOSER_MODEL", "claude-opus-5-5")
DEFAULT_PLAYBOOK = Path(__file__).resolve().parent.parent / "playbook.md"


def have_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def make_client():
    import anthropic
    return anthropic.Anthropic()


def make_judges(offline: bool, client=None, playbook: Path | None = DEFAULT_PLAYBOOK):
    """Return (classifier, reviewer). Offline mode needs no key and no network."""
    if offline:
        return HeuristicClassifier(), GLReviewer()
    client = client or make_client()
    classifier = ClaudeClassifier(client, CLASSIFIER_MODEL, playbook=playbook, label="classifier")
    reviewer = ClaudeClassifier(client, REVIEWER_MODEL, system_template=REVIEWER_SYSTEM,
                                include_gl=True, label="reviewer")
    classifier.name, reviewer.name = f"claude:{CLASSIFIER_MODEL}", f"claude:{REVIEWER_MODEL}"
    return classifier, reviewer
