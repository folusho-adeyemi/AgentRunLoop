"""Mock planner: decides the next action. Deterministic, no model, no network.

The planner is a pure function of (goal, history), so the same goal always
produces the same sequence of actions. That is what makes a resume safe: after
a crash, replaying the planner with the checkpointed history yields exactly the
action that was in flight, not a different plan.
"""

# A default goal runs this many steps, each costing this much.
DEFAULT_STEPS = 3
STEP_COST = 10

# Goals containing "fail" run longer so that a mid-sequence step exists.
FAILING_STEPS = 5
# The step that misbehaves. Index 3 is mid-run: steps 0-2 have already
# succeeded and been charged by the time it is reached.
FAILING_STEP_INDEX = 3


def mock_planner(goal: str, history: list[str]) -> dict:
    """Return the next action, or {"done": True, "output": ...} when finished.

    An action is {"tool_name": str, "tool_input": str, "cost": int}.
    Decisions depend only on the goal and how many steps have completed.
    """
    lowered = goal.lower()
    step_index = len(history)
    step_number = step_index + 1

    # "loop": never returns done. Exercises the MAX_STEPS backstop and the
    # budget check — the only two things that can stop a runaway plan.
    if "loop" in lowered:
        return {
            "tool_name": "web_search",
            "tool_input": f"{goal} #{step_number}",
            "cost": STEP_COST,
        }

    # "fail" / "failhard": same shape, but step 3 uses a flaky tool. Check
    # "failhard" first — it also contains the substring "fail".
    if "fail" in lowered:
        if step_index < FAILING_STEPS:
            if step_index == FAILING_STEP_INDEX:
                tool = "flaky_hard" if "failhard" in lowered else "flaky"
                return {
                    "tool_name": tool,
                    "tool_input": f"{goal} #{step_number}",
                    "cost": STEP_COST,
                }
            return {
                "tool_name": "web_search",
                "tool_input": f"{goal} #{step_number}",
                "cost": STEP_COST,
            }
        return _done(goal, history)

    if step_index < DEFAULT_STEPS:
        return {
            "tool_name": "web_search",
            "tool_input": f"{goal} #{step_number}",
            "cost": STEP_COST,
        }

    return _done(goal, history)


def _done(goal: str, history: list[str]) -> dict:
    return {
        "done": True,
        "output": f"Completed '{goal}' in {len(history)} steps: "
        + "; ".join(history),
    }
