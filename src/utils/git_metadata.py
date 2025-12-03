"""
Utilities for validating git metadata fields collected from the UI.

Phase 5.2 introduces optional git configuration per session. These helpers keep
validation logic in one place so both the NewSessionDialog and SessionTabWidget
apply consistent rules.
"""

from __future__ import annotations

import re
from typing import Tuple

# Accepted branch characters roughly match git-check-ref-format (simplified).
BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9._\-\/]+$")


def validate_git_repo_url(repo_url: str) -> Tuple[bool, str]:
    """
    Validate a git repository URL.

    Args:
        repo_url: Raw repo URL entered by the user.

    Returns:
        Tuple of (is_valid, message). Message is empty on success.
    """
    repo_url = repo_url.strip()
    if not repo_url:
        return True, ""

    if " " in repo_url:
        return False, "Repository URL cannot contain spaces."

    # Basic remote patterns we support (https, http, ssh, git@).
    allowed_prefixes = ("https://", "http://", "ssh://", "git@")
    if not repo_url.startswith(allowed_prefixes):
        return False, (
            "Repository URL should start with https://, http://, ssh://, or git@. "
            "Example: https://github.com/org/repo.git"
        )

    if repo_url.startswith("git@") and ":" not in repo_url:
        return False, "SSH URLs must include the host separator (e.g., git@github.com:org/repo.git)."

    return True, ""


def validate_git_branch_name(branch: str) -> Tuple[bool, str]:
    """
    Validate a git branch name (simplified rules).

    Args:
        branch: Raw branch name entered by the user.

    Returns:
        Tuple of (is_valid, message). Message is empty on success.
    """
    branch = branch.strip()
    if not branch:
        return True, ""

    if branch in {".", ".."} or branch.endswith(".lock"):
        return False, "Branch name cannot be '.' '..' or end with '.lock'."

    if branch.startswith("/") or branch.endswith("/") or "//" in branch:
        return False, "Branch name cannot start/end with '/' or contain '//'."

    if not BRANCH_PATTERN.match(branch):
        return False, "Branch name may only contain letters, numbers, '.', '_', '-' and '/'."

    return True, ""
