"""
Prompt Sanitizer for FlowCoder

Sanitizes user inputs before inserting into Claude prompts to prevent
injection attacks and prompt stuffing.
"""

from typing import Any, Dict
import re


class PromptSanitizer:
    """Sanitize user inputs before inserting into prompts."""

    MAX_LENGTH = 1000  # Prevent prompt stuffing

    # Control characters to remove (except common whitespace)
    CONTROL_CHARS_PATTERN = re.compile(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]')

    # Patterns that could be used for prompt injection
    SUSPICIOUS_PATTERNS = [
        r'ignore\s+(?:all\s+)?(?:previous|prior)\s+(?:instructions|prompts?)',
        r'disregard\s+(?:all\s+)?(?:previous|prior)\s+(?:instructions|prompts?)',
        r'forget\s+(?:all\s+)?(?:previous|prior)\s+(?:instructions|prompts?)',
        r'new\s+(?:instructions|prompt|rules)',
        r'you\s+are\s+now',
        r'your\s+new\s+(?:role|task|purpose)',
    ]

    @staticmethod
    def sanitize_argument(arg: str) -> str:
        """
        Sanitize command argument.

        Args:
            arg: User-provided argument

        Returns:
            Sanitized argument safe for prompt insertion
        """
        if not isinstance(arg, str):
            arg = str(arg)

        # Remove control characters (except tabs, newlines)
        arg = PromptSanitizer.CONTROL_CHARS_PATTERN.sub('', arg)

        # Limit length (prevent prompt stuffing)
        if len(arg) > PromptSanitizer.MAX_LENGTH:
            arg = arg[:PromptSanitizer.MAX_LENGTH] + "...[truncated]"

        # Check for suspicious patterns
        arg_lower = arg.lower()
        for pattern in PromptSanitizer.SUSPICIOUS_PATTERNS:
            if re.search(pattern, arg_lower, re.IGNORECASE):
                # Log warning but don't block completely
                # Could add more aggressive filtering if needed
                pass

        return arg

    @staticmethod
    def sanitize_variable(value: Any) -> Any:
        """
        Sanitize variable value from structured output.

        Args:
            value: Variable value (any type)

        Returns:
            Sanitized value
        """
        if isinstance(value, str):
            return PromptSanitizer.sanitize_argument(value)
        elif isinstance(value, (int, float, bool)):
            # Primitives are safe
            return value
        elif isinstance(value, list):
            return [PromptSanitizer.sanitize_variable(v) for v in value]
        elif isinstance(value, dict):
            return {k: PromptSanitizer.sanitize_variable(v) for k, v in value.items()}
        elif value is None:
            return None
        else:
            # Unknown type - convert to string and sanitize
            return PromptSanitizer.sanitize_argument(str(value))

    @staticmethod
    def sanitize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize all values in a dictionary.

        Args:
            data: Dictionary with potentially unsafe values

        Returns:
            Dictionary with sanitized values
        """
        return {k: PromptSanitizer.sanitize_variable(v) for k, v in data.items()}

    @staticmethod
    def is_potentially_malicious(text: str) -> bool:
        """
        Check if text contains potentially malicious patterns.

        Args:
            text: Text to check

        Returns:
            True if text contains suspicious patterns
        """
        if not isinstance(text, str):
            return False

        text_lower = text.lower()
        for pattern in PromptSanitizer.SUSPICIOUS_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True

        return False
