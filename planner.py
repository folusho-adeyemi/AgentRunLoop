"""Mock planner: decides the next action. Deterministic, no model, no network.

The planner is a pure function of (goal, history), so the same goal always
produces the same sequence of actions and a run is reproducible.
"""

# A default goal runs this many steps, each costing this much.
DEFAULT_STEPS = 3
STEP_COST = 10


def mock_planner(goal: str, history: list[str]) -> dict:
    """Return the next action, or {"done": True, "output": ...} when finished.

    An action is {"tool_name": str, "tool_input": str, "cost": int}.
    Decisions depend only on the goal and how many steps have completed.
    """
    lowered = goal.lower()
    step_number = len(history) + 1

    # "loop": never returns done. Exercises the MAX_STEPS backstop and the
    # budget check — the only two things that can stop a runaway plan.
    if "loop" in lowered:
        return {
            "tool_name": "web_search",
            "tool_input": f"{goal} #{step_number}",
            "cost": STEP_COST,
        }

    if len(history) < DEFAULT_STEPS:
        return {
            "tool_name": "web_search",
            "tool_input": f"{goal} #{step_number}",
            "cost": STEP_COST,
        }

    return {
        "done": True,
        "output": f"Completed '{goal}' in {len(history)} steps: "
        + "; ".join(history),
    }
