import json
from typing import Any, Dict, List

from . import storage, tool_loop

SYSTEM_PROMPT = """You are a debt elimination specialist. You help users:
- Catalog all their debts clearly
- Choose between Snowball (psychological wins) vs Avalanche (mathematically optimal) strategies
- See exactly when each debt will be paid off and total interest paid
- Find extra money to accelerate payoff
- Understand the psychological and financial trade-offs of each approach

When presenting a payoff plan, always show:
- Order of payoff, estimated date for each debt, total interest saved
- How the strategy compares to paying minimums only
- How much extra monthly payment would save in interest and time

Be motivating! Celebrate progress. Remind users that debt-free is achievable with a plan."""

TOOLS = [
    {"type": "function", "function": {
        "name": "add_debt",
        "description": "Add a debt to track",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Debt name, e.g. 'Chase Visa', 'Student Loan', 'Car Loan'"},
                "balance": {"type": "number", "description": "Current balance in dollars"},
                "annual_interest_rate": {"type": "number", "description": "Annual interest rate as percentage (e.g. 19.99 for 19.99%)"},
                "minimum_payment": {"type": "number", "description": "Minimum monthly payment"},
                "debt_type": {
                    "type": "string",
                    "enum": ["credit_card", "student_loan", "auto_loan", "mortgage", "personal_loan", "medical", "other"],
                },
            },
            "required": ["name", "balance", "annual_interest_rate", "minimum_payment"],
        },
    }},
    {"type": "function", "function": {
        "name": "get_debt_summary",
        "description": "Get a summary of all debts",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "calculate_payoff_plan",
        "description": "Calculate a month-by-month debt payoff plan using snowball or avalanche strategy",
        "parameters": {
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "enum": ["snowball", "avalanche"],
                    "description": "snowball: pay smallest balance first. avalanche: pay highest interest first",
                },
                "extra_monthly_payment": {
                    "type": "number",
                    "description": "Extra amount to pay monthly beyond all minimums (default 0)",
                },
            },
            "required": ["strategy"],
        },
    }},
    {"type": "function", "function": {
        "name": "update_debt_balance",
        "description": "Update the current balance of a debt after making payments",
        "parameters": {
            "type": "object",
            "properties": {
                "debt_name": {"type": "string"},
                "new_balance": {"type": "number"},
            },
            "required": ["debt_name", "new_balance"],
        },
    }},
    {"type": "function", "function": {
        "name": "remove_debt",
        "description": "Remove a debt that has been paid off",
        "parameters": {
            "type": "object",
            "properties": {"debt_name": {"type": "string"}},
            "required": ["debt_name"],
        },
    }},
    {"type": "function", "function": {
        "name": "compare_strategies",
        "description": "Compare snowball vs avalanche vs minimum payments side by side",
        "parameters": {
            "type": "object",
            "properties": {
                "extra_monthly_payment": {"type": "number", "description": "Extra payment beyond minimums (default 0)"}
            },
        },
    }},
]


def _simulate_payoff_simple(debts: List[Dict], extra: float, strategy: str) -> Dict:
    from datetime import date

    working = []
    for d in debts:
        working.append({
            "name": d["name"],
            "balance": float(d["balance"]),
            "rate": d["annual_interest_rate"] / 100 / 12,
            "min_payment": float(d["minimum_payment"]),
            "interest_paid": 0.0,
            "paid_off_month": None,
        })

    month = 0
    max_months = 600

    while any(d["balance"] > 0 for d in working) and month < max_months:
        month += 1
        active = [d for d in working if d["balance"] > 0]

        if strategy == "snowball":
            active_sorted = sorted(active, key=lambda x: x["balance"])
        else:
            active_sorted = sorted(active, key=lambda x: -x["rate"])

        freed = 0.0
        for i, d in enumerate(active_sorted):
            interest = d["balance"] * d["rate"]
            d["interest_paid"] += interest
            d["balance"] = d["balance"] + interest

            if i == 0:
                payment = min(d["balance"], d["min_payment"] + extra + freed)
            else:
                payment = min(d["balance"], d["min_payment"])

            d["balance"] = max(0.0, d["balance"] - payment)
            if d["balance"] == 0 and d["paid_off_month"] is None:
                d["paid_off_month"] = month
                freed += d["min_payment"]

    base = date.today()
    payoff_order = []
    for d in sorted(working, key=lambda x: x["paid_off_month"] or month):
        m = d["paid_off_month"] or month
        yr = base.year + (base.month - 1 + m) // 12
        mo = (base.month - 1 + m) % 12 + 1
        payoff_order.append({
            "name": d["name"],
            "total_interest_paid": round(d["interest_paid"], 2),
            "paid_off_in_months": m,
            "payoff_date": f"{yr}-{mo:02d}",
        })

    return {
        "strategy": strategy,
        "extra_monthly_payment": extra,
        "total_months": month,
        "total_interest_paid": round(sum(d["interest_paid"] for d in working), 2),
        "debts_in_payoff_order": payoff_order,
    }


def _handle_tool(name: str, inp: Dict[str, Any]) -> str:
    inp = inp or {}
    data = storage.load()

    if name == "add_debt":
        debt = {
            "name": inp["name"],
            "balance": inp["balance"],
            "annual_interest_rate": inp["annual_interest_rate"],
            "minimum_payment": inp["minimum_payment"],
            "debt_type": inp.get("debt_type", "other"),
        }
        data["debts"] = [d for d in data["debts"] if d["name"].lower() != debt["name"].lower()]
        data["debts"].append(debt)
        storage.save(data)
        return json.dumps({"status": "added", "debt": debt})

    if name == "get_debt_summary":
        debts = data["debts"]
        total_balance = sum(d["balance"] for d in debts)
        total_minimum = sum(d["minimum_payment"] for d in debts)
        avg_rate = sum(d["annual_interest_rate"] * d["balance"] for d in debts) / total_balance if total_balance else 0
        return json.dumps({
            "total_debts": len(debts),
            "total_balance": round(total_balance, 2),
            "total_minimum_payments": round(total_minimum, 2),
            "weighted_avg_interest_rate": round(avg_rate, 2),
            "debts": sorted(debts, key=lambda x: -x["balance"]),
        })

    if name == "calculate_payoff_plan":
        debts = data["debts"]
        if not debts:
            return json.dumps({"error": "No debts tracked yet. Add debts first."})
        extra = inp.get("extra_monthly_payment", 0)
        strategy = inp["strategy"]
        result = _simulate_payoff_simple(debts, extra, strategy)
        return json.dumps(result)

    if name == "update_debt_balance":
        target = next((d for d in data["debts"] if d["name"].lower() == inp["debt_name"].lower()), None)
        if not target:
            return json.dumps({"error": f"Debt '{inp['debt_name']}' not found"})
        target["balance"] = inp["new_balance"]
        storage.save(data)
        return json.dumps({"status": "updated", "debt": target})

    if name == "remove_debt":
        before = len(data["debts"])
        data["debts"] = [d for d in data["debts"] if d["name"].lower() != inp["debt_name"].lower()]
        storage.save(data)
        removed = before - len(data["debts"])
        return json.dumps({"status": "removed" if removed else "not_found"})

    if name == "compare_strategies":
        debts = data["debts"]
        if not debts:
            return json.dumps({"error": "No debts tracked yet."})
        extra = inp.get("extra_monthly_payment", 0)
        snowball = _simulate_payoff_simple(debts, extra, "snowball")
        avalanche = _simulate_payoff_simple(debts, extra, "avalanche")
        minimums = _simulate_payoff_simple(debts, 0, "avalanche")
        return json.dumps({
            "comparison": {
                "minimums_only": {
                    "months": minimums["total_months"],
                    "total_interest": minimums["total_interest_paid"],
                },
                "snowball_with_extra": {
                    "months": snowball["total_months"],
                    "total_interest": snowball["total_interest_paid"],
                    "interest_saved_vs_minimums": round(minimums["total_interest_paid"] - snowball["total_interest_paid"], 2),
                    "months_saved": minimums["total_months"] - snowball["total_months"],
                },
                "avalanche_with_extra": {
                    "months": avalanche["total_months"],
                    "total_interest": avalanche["total_interest_paid"],
                    "interest_saved_vs_minimums": round(minimums["total_interest_paid"] - avalanche["total_interest_paid"], 2),
                    "months_saved": minimums["total_months"] - avalanche["total_months"],
                },
            },
            "extra_monthly_payment": extra,
        })

    return json.dumps({"error": f"Unknown tool: {name}"})


def run(task: str) -> str:
    return tool_loop.run(SYSTEM_PROMPT, task, TOOLS, _handle_tool)
