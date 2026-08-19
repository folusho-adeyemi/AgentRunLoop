"""Mock tools. Deterministic strings — no network, no filesystem, no clock."""


def mock_tool(tool_name: str, tool_input: str) -> str:
    """Run a tool and return its output as a string."""
    if tool_name == "web_search":
        return f"[web_search] 3 results for {tool_input!r}"
    # Unknown tools still return something rather than raising; tool *failure*
    # handling arrives next.
    return f"[{tool_name}] ok: {tool_input}"
