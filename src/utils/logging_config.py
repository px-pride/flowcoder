"""
Logging Configuration for FlowCoder

Provides secure logging with sensitive data sanitization.
"""

import logging
import re
from typing import Pattern, List


class SanitizingFormatter(logging.Formatter):
    """
    Logging formatter that sanitizes sensitive information.

    Removes:
    - API keys (various patterns)
    - File paths with sensitive directories
    - Bearer tokens
    - Passwords
    """

    # Patterns for sensitive data
    SENSITIVE_PATTERNS: List[tuple[Pattern, str]] = [
        # API keys (Anthropic format: sk- followed by chars)
        (re.compile(r'sk-[a-zA-Z0-9]{20,}'), '[API_KEY_REDACTED]'),
        (re.compile(r'api[_-]?key["\s:=]+[a-zA-Z0-9_-]{20,}', re.IGNORECASE), 'api_key=[API_KEY_REDACTED]'),

        # Bearer tokens
        (re.compile(r'Bearer\s+[a-zA-Z0-9._-]+', re.IGNORECASE), 'Bearer [TOKEN_REDACTED]'),

        # Passwords in URLs or config
        (re.compile(r'password["\s:=]+[^\s"]+', re.IGNORECASE), 'password=[PASSWORD_REDACTED]'),

        # Sensitive file paths
        (re.compile(r'(?:/home/[^/]+/|C:\\Users\\[^\\]+\\)\.(?:ssh|aws|config|env|credentials)', re.IGNORECASE), '[SENSITIVE_PATH_REDACTED]'),
        (re.compile(r'\.env|credentials\.json|\.ssh/', re.IGNORECASE), '[SENSITIVE_FILE_REDACTED]'),
    ]

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record and sanitize sensitive information.

        Args:
            record: Log record to format

        Returns:
            Formatted and sanitized log message
        """
        # Format the message first
        formatted = super().format(record)

        # Apply sanitization patterns
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            formatted = pattern.sub(replacement, formatted)

        return formatted

    @staticmethod
    def sanitize_message(message: str) -> str:
        """
        Sanitize a message string.

        Args:
            message: Message to sanitize

        Returns:
            Sanitized message
        """
        for pattern, replacement in SanitizingFormatter.SENSITIVE_PATTERNS:
            message = pattern.sub(replacement, message)
        return message


def configure_secure_logging(level: int = logging.INFO, log_dir: str = "logs") -> None:
    """
    Configure secure logging for the application with rotation.

    Args:
        level: Logging level (default: INFO)
        log_dir: Base directory for logs (default: "logs")
    """
    import os
    from logging.handlers import RotatingFileHandler

    # Ensure log directories exist
    os.makedirs(os.path.join(log_dir, "application"), exist_ok=True)
    os.makedirs(os.path.join(log_dir, "errors"), exist_ok=True)

    # Create sanitizing formatter
    formatter = SanitizingFormatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add console handler with sanitizing formatter
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Add rotating file handler for main application log
    # 10MB max size, keep 5 backup files
    app_log_path = os.path.join(log_dir, "application", "flowcoder.log")
    file_handler = RotatingFileHandler(
        app_log_path,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Add separate error log handler (errors and warnings only)
    error_log_path = os.path.join(log_dir, "errors", "errors.log")
    error_handler = RotatingFileHandler(
        error_log_path,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=3
    )
    error_handler.setLevel(logging.WARNING)  # Only warnings and errors
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)
