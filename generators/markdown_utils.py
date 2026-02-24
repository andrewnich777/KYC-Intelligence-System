"""Shared markdown utilities for brief generators."""


def esc(text: str, max_len: int = 0) -> str:
    """Escape pipe characters for markdown tables, optionally truncate at word boundary."""
    s = str(text).replace("|", "\\|")
    if not max_len or len(s) <= max_len:
        return s
    # Truncate at last space before limit, add ellipsis
    truncated = s[: max_len - 3]
    last_space = truncated.rfind(" ")
    if last_space > max_len // 2:
        truncated = truncated[:last_space]
    return truncated + "..."
