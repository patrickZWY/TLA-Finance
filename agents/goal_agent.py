import json
from datetime import datetime
from typing import Any, Dict

from . import storage, tool_loop

SYSTEM_PROMPT = """You are a financial goal planning specialist. You help users:
- Define clear, time-bound financial goals (emergency fund, home purchase, vacation, retirement)
- Calculate exactly how much they need to save each month to hit their targets
- Track progress and adjust plans when life changes
- Celebrate milestones and keep motivation high

Be specific with numbers. Always show: target amount, current savings, amount remaining,
months remaining, required monthly savings (with and without investment returns), and % complete.
Use the tools to manage goal data, then provide a clear narrative around the numbers."""

TOOLS = [
    {"type": "function", "function": {
        "name": "add_goal",
        "description": "Create a new financial goal to track",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Goal name, e.g. 'Emergency Fund', 'House Down Payment'"},
                "target_amount": {"type": "number", "description": "Target amount in dollars"},
                "deadline": {"type": "string", "description": "Target date in YYYY-MM-DD format"},
                "current_savings": {"type": "number", "description": "Amount already saved (default 0)"},
                "description": {"type": "string", "description": "Optional notes about the goal"},
                "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "Priority level"},
            },
            "required": ["name", "target_amount", "deadline"],
        },
    }},
    {"type": "function", "function": {
        "name": "update_goal_progress",
        "description": "Update how much has been saved towards a goal",
        "parameters": {
            "type": "object",
            "properties": {
                "goal_name": {"type": "string"},
                "amount_saved": {"type": "number", "description": "New total saved amount (replaces current)"},
                "add_amount": {"type": "number", "description": "Amount to ADD to current savings (use instead of amount_saved)"},
            },
            "required": ["goal_name"],
        },
    }},
    {"type": "function", "function": {
        "name": "get_goals_status",
        "description": "Get status of all goals including progress and time remaining",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "calculate_savings_plan",
        "description": "Calculate monthly savings needed to reach a goal, with and without investment returns",
        "parameters": {
            "type": "object",
            "properties": {
                "goal_name": {"type": "string"},
                "annual_return_rate": {
                    "type": "number",
                    "description": "Expected annual investment return as decimal (e.g. 0.07 for 7%). Use 0 for simple savings.",
                },
            },
            "required": ["goal_name"],
        },
    }},
    {"type": "function", "function": {
        "name": "remove_goal",
        "description": "Remove a completed or cancelled goal",
        "parameters": {
            "type": "object",
            "properties": {"goal_name": {"type": "string"}},
            "required": ["goal_name"],
        },
    }},
]


def _months_between(start: datetime, end: datetime) -> int:
    return max(0, (end.year - start.year) * 12 + (end.month - start.month))


def _monthly_payment_with_growth(pv: float, rate: float, n: int) -> float:
    if rate == 0 or n == 0:
        return pv / n if n > 0 else pv
    r = rate / 12
    return pv * r / (1 - (1 + r) ** -n)


def _handle_tool(name: str, inp: Dict[str, Any]) -> str:
    inp = inp or {}
    data = storage.load()
    today = datetime.now()

    if name == "add_goal":
        goal = {
            "name": inp["name"],
            "target_amount": inp["target_amount"],
            "deadline": inp["deadline"],
            "current_savings": inp.get("current_savings", 0),
            "description": inp.get("description", ""),
            "priority": inp.get("priority", "medium"),
            "created": today.strftime("%Y-%m-%d"),
        }
        data["goals"] = [g for g in data["goals"] if g["name"].lower() != goal["name"].lower()]
        data["goals"].append(goal)
        storage.save(data)
        return json.dumps({"status": "created", "goal": goal})

    if name == "update_goal_progress":
        goals = data["goals"]
        target = next((g for g in goals if g["name"].lower() == inp["goal_name"].lower()), None)
        if not target:
            return json.dumps({"error": f"Goal '{inp['goal_name']}' not found"})
        if "amount_saved" in inp:
            target["current_savings"] = inp["amount_saved"]
        elif "add_amount" in inp:
            target["current_savings"] = target.get("current_savings", 0) + inp["add_amount"]
        storage.save(data)
        pct = target["current_savings"] / target["target_amount"] * 100
        return json.dumps({"status": "updated", "goal": target["name"], "saved": target["current_savings"],
                           "target": target["target_amount"], "percent_complete": round(pct, 1)})

    if name == "get_goals_status":
        results = []
        for g in data["goals"]:
            deadline = datetime.strptime(g["deadline"], "%Y-%m-%d")
            months_left = _months_between(today, deadline)
            saved = g.get("current_savings", 0)
            remaining = g["target_amount"] - saved
            pct = saved / g["target_amount"] * 100 if g["target_amount"] else 0
            results.append({
                "name": g["name"],
                "target": g["target_amount"],
                "saved": saved,
                "remaining": round(remaining, 2),
                "percent_complete": round(pct, 1),
                "deadline": g["deadline"],
                "months_remaining": months_left,
                "monthly_needed_no_growth": round(remaining / months_left, 2) if months_left > 0 else "PAST DUE",
                "priority": g.get("priority", "medium"),
                "on_track": pct / 100 >= (1 - months_left / max(1, (deadline - today).days / 30)),
            })
        return json.dumps({"goals": results, "total_goals": len(results)})

    if name == "calculate_savings_plan":
        goals = data["goals"]
        g = next((x for x in goals if x["name"].lower() == inp["goal_name"].lower()), None)
        if not g:
            return json.dumps({"error": f"Goal '{inp['goal_name']}' not found"})
        deadline = datetime.strptime(g["deadline"], "%Y-%m-%d")
        months = _months_between(today, deadline)
        saved = g.get("current_savings", 0)
        remaining = g["target_amount"] - saved
        rate = inp.get("annual_return_rate", 0)
        monthly_no_growth = remaining / months if months > 0 else remaining
        monthly_with_growth = _monthly_payment_with_growth(remaining, rate, months) if rate > 0 else monthly_no_growth
        return json.dumps({
            "goal": g["name"],
            "target": g["target_amount"],
            "already_saved": saved,
            "amount_remaining": round(remaining, 2),
            "months_remaining": months,
            "monthly_savings_needed_no_growth": round(monthly_no_growth, 2),
            "monthly_savings_with_returns": round(monthly_with_growth, 2) if rate > 0 else None,
            "assumed_annual_return": f"{rate*100:.1f}%" if rate > 0 else "N/A",
            "savings_from_growth": round(monthly_no_growth - monthly_with_growth, 2) if rate > 0 else 0,
        })

    if name == "remove_goal":
        before = len(data["goals"])
        data["goals"] = [g for g in data["goals"] if g["name"].lower() != inp["goal_name"].lower()]
        storage.save(data)
        removed = before - len(data["goals"])
        return json.dumps({"status": "removed" if removed else "not_found", "count_removed": removed})

    return json.dumps({"error": f"Unknown tool: {name}"})


def run(task: str) -> str:
    return tool_loop.run(SYSTEM_PROMPT, task, TOOLS, _handle_tool)
