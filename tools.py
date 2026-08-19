"""Mock tools. Deterministic strings — no network, no filesystem, no clock.

Failure is a function of the attempt number, never of a random draw or a wall
clock, so "fails once then succeeds" reproduces exactly on every run.
"""


class ToolError(Exception):
    """A tool failed. The loop decides whether to retry or give up."""


# A "flaky_hard" step keeps failing until its attempt count passes this. It is
# set above the loop's per-run attempt allowance on purpose: no number of
# in-run retries clears it, so the run reaches FAILED and only a resume — which
# carries the persisted attempt_count forward — gets past it.
HARD_FAILURE_ATTEMPTS = 3


def mock_tool(tool_name: str, tool_input: str, attempt: int = 1) -> str:
    """Run a tool and return its output. Raises ToolError on failure.

    attempt is the step's cumulative attempt_count, read from the database, so
    it survives a process restart and keeps counting across a resume.
    """
    if tool_name == "flaky":
        # Fails on the first attempt only; the loop's own retry recovers it.
        if attempt == 1:
            raise ToolError(f"{tool_name} transient failure on attempt {attempt}")
        return f"[{tool_name}] recovered on attempt {attempt}: {tool_input!r}"

    if tool_name == "flaky_hard":
        # Outlasts the in-run retries; only a resume gets past it.
        if attempt <= HARD_FAILURE_ATTEMPTS:
            raise ToolError(f"{tool_name} failure on attempt {attempt}")
        return f"[{tool_name}] recovered on attempt {attempt}: {tool_input!r}"

    if tool_name == "web_search":
        return f"[web_search] 3 results for {tool_input!r}"

    return f"[{tool_name}] ok: {tool_input}"
