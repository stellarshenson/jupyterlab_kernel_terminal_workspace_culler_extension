"""The agent skill the wheel installs is the one in the repository."""

import sys
from pathlib import Path

SKILL = "jupyterlab-kernel-terminal-workspace-culler-extension/SKILL.md"


def test_installed_skill_matches_repository():
    repository = Path(__file__).parents[2] / ".agents" / "skills" / SKILL
    installed = Path(sys.prefix) / "share" / "jupyter" / "agents" / "skills" / SKILL

    assert installed.read_text() == repository.read_text()
