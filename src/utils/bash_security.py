"""
Bash Security Validator for FlowCoder

Provides security validation for bash commands to prevent dangerous operations.
"""

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)


# Dangerous command patterns that should trigger warnings
DANGEROUS_PATTERNS = [
    # Destructive file operations
    (r'rm\s+(-[rf]+\s+)?/', "Dangerous: rm command with root path"),
    (r'rm\s+-rf\s+~', "Dangerous: rm -rf on home directory"),
    (r'dd\s+if=', "Dangerous: dd command can overwrite disks"),

    # Fork bombs and resource exhaustion
    (r':\(\)\s*\{\s*:\|:\&\s*\};:', "Dangerous: Fork bomb detected"),
    (r'while\s+true.*do.*done', "Warning: Infinite loop detected"),

    # Network attacks
    (r'curl.*\|\s*bash', "Dangerous: Piping curl to bash"),
    (r'wget.*\|\s*bash', "Dangerous: Piping wget to bash"),
    (r'curl.*\|\s*sh', "Dangerous: Piping curl to sh"),
    (r'wget.*\|\s*sh', "Dangerous: Piping wget to sh"),

    # System modification
    (r'mkfs', "Dangerous: Filesystem creation detected"),
    (r'fdisk', "Dangerous: Disk partitioning command"),
    (r'parted', "Dangerous: Disk partitioning command"),

    # Privilege escalation attempts
    (r'sudo\s+rm', "Warning: sudo rm detected"),
    (r'sudo\s+dd', "Warning: sudo dd detected"),

    # Potentially destructive operations
    (r'>\s*/dev/sd[a-z]', "Dangerous: Writing to block device"),
    (r'>\s*/dev/null', "Info: Redirecting to /dev/null"),
]


# Patterns that are generally safe to ignore
SAFE_PATTERNS = [
    r'echo\s+',
    r'cat\s+',
    r'ls\s+',
    r'pwd',
    r'date',
    r'whoami',
]


class BashSecurityValidator:
    """Validator for bash commands to detect potentially dangerous operations."""

    @staticmethod
    def validate_command(command: str) -> Tuple[bool, List[str]]:
        """
        Validate a bash command for security issues.

        Args:
            command: The bash command to validate

        Returns:
            Tuple of (is_safe, warnings)
            - is_safe: True if command passed all checks, False if critical issues found
            - warnings: List of warning/error messages
        """
        warnings = []
        is_safe = True

        if not command or not command.strip():
            return True, []

        # Normalize whitespace for pattern matching
        normalized_command = ' '.join(command.split())

        # Check against dangerous patterns
        for pattern, message in DANGEROUS_PATTERNS:
            if re.search(pattern, normalized_command, re.IGNORECASE):
                # Determine severity based on message prefix
                if message.startswith("Dangerous:"):
                    is_safe = False
                    logger.warning(f"SECURITY: {message} in command: {command}")

                warnings.append(message)

        # Log command execution for audit trail
        logger.info(f"Bash command validated: {command[:100]}... (safe={is_safe}, warnings={len(warnings)})")

        return is_safe, warnings

    @staticmethod
    def is_safe_command(command: str) -> bool:
        """
        Quick check if a command is known to be safe.

        Args:
            command: The bash command to check

        Returns:
            True if command matches known safe patterns
        """
        if not command or not command.strip():
            return True

        normalized_command = ' '.join(command.split())

        for pattern in SAFE_PATTERNS:
            if re.match(pattern, normalized_command, re.IGNORECASE):
                return True

        return False

    @staticmethod
    def get_confirmation_message(warnings: List[str]) -> str:
        """
        Generate a user-friendly confirmation message for warnings.

        Args:
            warnings: List of warning messages

        Returns:
            Formatted confirmation message
        """
        if not warnings:
            return ""

        message_parts = [
            "⚠️ Security Warning ⚠️",
            "",
            "The following issues were detected in your bash command:",
            ""
        ]

        for warning in warnings:
            message_parts.append(f"  • {warning}")

        message_parts.extend([
            "",
            "This command may be dangerous and could:",
            "  - Delete files or data",
            "  - Modify system settings",
            "  - Consume excessive resources",
            "  - Compromise system security",
            "",
            "Are you sure you want to execute this command?"
        ])

        return "\n".join(message_parts)
