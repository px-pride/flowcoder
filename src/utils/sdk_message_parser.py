"""
SDK Message Parser for FlowCoder

Parses raw Claude Agent SDK message objects into structured
(text_content, verbose_content, message_type) tuples. Used by both
the GUI (SessionTabWidget) and CLI (CLIAgent) for streaming output.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Pre-compiled regex patterns for extracting text from StreamEvent content_block_delta
# These handle various quote combinations from Python's repr() of SDK objects.
_TEXT_DELTA_PATTERNS = [
    re.compile(r"'text':\s*'((?:[^'\\]|\\.)*)'"),         # 'text': '...'
    re.compile(r'"text":\s*"((?:[^"\\]|\\.)*)"'),          # "text": "..."
    re.compile(r"\\'text\\':\s*\"((?:[^\"\\]|\\.)*?)\""),  # \'text\': "..."
    re.compile(r"'text':\s*\"((?:[^\"\\]|\\.)*?)\""),      # 'text': "..."
]

# Markers that indicate a structured SDK message (vs raw plain text)
_STRUCTURED_MARKERS = ("AssistantMessage", "SystemMessage", "ResultMessage", "StreamEvent", "UserMessage")

# StreamEvent types that are control messages (no user-visible content)
_SYSTEM_EVENT_TYPES = ("message_start", "message_stop", "content_block_stop", "message_delta")


def _unescape_text(text: str) -> str:
    """Unescape common escape sequences in extracted text."""
    text = text.replace('\\n', '\n')
    text = text.replace('\\t', '\t')
    text = text.replace('\\r', '\r')
    text = text.replace("\\'", "'")
    text = text.replace('\\"', '"')
    text = text.replace('\\\\', '\\')
    return text


def _extract_text_delta(message_str: str) -> str | None:
    """Extract text from a content_block_delta/text_delta StreamEvent.

    Returns:
        Extracted and unescaped text, or None if no match.
    """
    for pattern in _TEXT_DELTA_PATTERNS:
        match = pattern.search(message_str)
        if match:
            return _unescape_text(match.group(1))
    return None


def _build_verbose_content(message_str: str, text_content: str) -> str:
    """Build a human-readable verbose representation of a structured message."""
    verbose_lines = []

    if "AssistantMessage" in message_str:
        verbose_lines.append("📤 Assistant Message:")
        if text_content:
            verbose_lines.append(f"   Content: {text_content[:100]}...")

    elif "SystemMessage" in message_str:
        verbose_lines.append("⚙️  System Message:")
        if "session_id" in message_str:
            sid_start = message_str.find("'session_id': '") + len("'session_id': '")
            sid_end = message_str.find("'", sid_start)
            if sid_end != -1:
                session_id = message_str[sid_start:sid_end]
                verbose_lines.append(f"   Session: {session_id}")

    elif "ResultMessage" in message_str:
        verbose_lines.append("✅ Result Message:")
        if "duration_ms" in message_str:
            dur_start = message_str.find("duration_ms=") + len("duration_ms=")
            dur_end = message_str.find(",", dur_start)
            if dur_end != -1:
                duration = message_str[dur_start:dur_end]
                verbose_lines.append(f"   Duration: {duration}ms")
        if "total_cost_usd" in message_str:
            cost_start = message_str.find("total_cost_usd=") + len("total_cost_usd=")
            cost_end = message_str.find(",", cost_start)
            if cost_end != -1:
                cost = message_str[cost_start:cost_end]
                verbose_lines.append(f"   Cost: ${cost}")

    return "\n".join(verbose_lines) if verbose_lines else message_str


def _parse_engine_dict(msg: dict) -> tuple[str, str, str]:
    """Parse an engine-format dict message (from flowcoder_engine.ClaudeSession).

    Engine yields raw stream-json dicts:
      {"type": "system", ...}
      {"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}, ...]}}
      {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "..."}}}
      {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}}
      {"type": "result", "result": "...", "duration_ms": ..., "total_cost_usd": ..., "session_id": "..."}
    """
    msg_type = msg.get("type")

    if msg_type == "stream_event":
        event = msg.get("event", {})
        evt_type = event.get("type")

        if evt_type == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta":
                text = delta.get("text", "")
                return (text, f"[StreamEvent] {text}", "text_delta")
            return ("", "", "system")

        if evt_type == "content_block_start":
            block = event.get("content_block", {})
            if block.get("type") == "text":
                return ("", "", "content_block_start")
            return ("", "", "system")

        return ("", "", "system")

    if msg_type == "assistant":
        message = msg.get("message", {})
        content = message.get("content", [])
        text_parts = []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
        elif isinstance(content, str):
            text_parts.append(content)
        text = "".join(text_parts)
        return (text, f"📤 Assistant Message:\n   Content: {text[:100]}...", "assistant")

    if msg_type == "system":
        sid = msg.get("session_id", "")
        verbose = f"⚙️  System Message:\n   Session: {sid}" if sid else "⚙️  System Message"
        return ("[System initialization]", verbose, "system")

    if msg_type == "user":
        return ("", "[User Message]", "result")

    if msg_type == "result":
        result_text = msg.get("result", "") or ""
        duration = msg.get("duration_ms", 0)
        cost = msg.get("total_cost_usd", 0.0)
        verbose = f"✅ Result Message:\n   Duration: {duration}ms\n   Cost: ${cost}"
        return (result_text, verbose, "result")

    return ("", str(msg), "unknown")


def parse_sdk_message(sdk_message) -> tuple[str, str, str]:
    """
    Parse a stream message and extract text content and metadata.

    Handles both engine dict format (from flowcoder_engine.ClaudeSession)
    and SDK object format (from claude-agent-sdk). Engine dicts are
    detected by isinstance(msg, dict) and routed to _parse_engine_dict.

    Args:
        sdk_message: Either a dict (engine format) or an SDK message
                     object, or a plain text fallback.

    Returns:
        tuple of (text_content, verbose_content, message_type) where:
            text_content: The user-visible text extracted from the message
            verbose_content: Detailed representation for debug/verbose display
            message_type: One of:
                "text_delta"      - StreamEvent text chunk (streaming)
                "assistant"       - AssistantMessage with TextBlock (complete)
                "assistant_plain" - Plain text chunk (unstructured fallback)
                "content_block_start" - Start of new content block
                "system"          - System/control message
                "result"          - ResultMessage with metadata
                "unknown"         - Unrecognized message
    """
    if isinstance(sdk_message, dict):
        return _parse_engine_dict(sdk_message)

    message_str = str(sdk_message)
    message_type = "unknown"
    text_content = ""
    verbose_content = message_str

    is_structured = any(marker in message_str for marker in _STRUCTURED_MARKERS)

    try:
        # StreamEvent (new Claude Agent SDK format)
        if "StreamEvent" in message_str and "event=" in message_str:

            # content_block_delta with text_delta — the main streaming text path
            if "content_block_delta" in message_str and "text_delta" in message_str:
                extracted = _extract_text_delta(message_str)
                if extracted is not None:
                    logger.debug(f"Parsed StreamEvent chunk: {len(extracted)} chars")
                    return (extracted, f"[StreamEvent] {extracted}", "text_delta")

            # content_block_start — paragraph break signal (text blocks only)
            if "content_block_start" in message_str:
                if "'type': 'text'" in message_str:
                    return ("", "", "content_block_start")
                return ("", "", "system")

            # Other system-level events — suppress
            if any(evt in message_str for evt in _SYSTEM_EVENT_TYPES):
                logger.debug("Ignoring StreamEvent system message")
                return ("", "", "system")

        # AssistantMessage — complete response with TextBlocks
        elif "AssistantMessage" in message_str:
            message_type = "assistant"
            # Try double quotes first: TextBlock(text="...")
            start = message_str.find('TextBlock(text="')
            if start != -1:
                start += len('TextBlock(text="')
                end = message_str.find('")', start)
                if end != -1:
                    text_content = message_str[start:end].replace('\\n', '\n')
            else:
                # Try single quotes: TextBlock(text='...')
                start = message_str.find("TextBlock(text='")
                if start != -1:
                    start += len("TextBlock(text='")
                    end = message_str.find("')", start)
                    if end != -1:
                        text_content = message_str[start:end].replace('\\n', '\n')

        elif "SystemMessage" in message_str:
            message_type = "system"
            text_content = "[System initialization]"

        elif "UserMessage" in message_str:
            message_type = "result"
            text_content = ""

        elif "ResultMessage" in message_str:
            message_type = "result"
            start = message_str.find("result=\"")
            if start != -1:
                start += len("result=\"")
                end = message_str.find('")', start)
                if end == -1:
                    end = message_str.rfind('"')
                if end != -1:
                    text_content = message_str[start:end].replace('\\n', '\n')

        # Build verbose output for structured messages
        try:
            pretty = _build_verbose_content(message_str, text_content)
            if pretty != message_str:
                verbose_content = pretty
        except Exception:
            pass  # Fall back to raw string

    except Exception as e:
        logger.warning(f"Failed to parse SDK message: {e}")
        text_content = message_str

    # Plain text fallback (unstructured messages)
    if not is_structured and not text_content and message_str.strip():
        message_type = "assistant_plain"
        text_content = message_str
        logger.debug(f"Parsed plain text chunk: {len(text_content)} chars")

    return (text_content, verbose_content, message_type)
