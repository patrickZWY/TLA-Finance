"""Browser-safe, explanatory graphs for unsafe finance action plans.

The graph in this module is deliberately derived from the same normalized
actions and Python policy mirror used by the safety gate.  It never affects a
safety decision; it makes a failed decision easier to inspect.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from safety.models import CREDIT_ACTION_TYPES, DEBIT_ACTION_TYPES, FinanceAction, SafetyPolicy
from safety.validator import SafetyFinding, evaluate_policy


def build_violation_visualization(
    actions: list[FinanceAction],
    policy: SafetyPolicy,
    findings: list[SafetyFinding],
    *,
    tlc_status: str,
    dot_path: Path | None = None,
) -> dict[str, Any]:
    """Return TLC graph data for every completed run, plus a journey if unsafe."""

    policy_findings = evaluate_policy(actions, policy)
    choice_names = [name for name in dict.fromkeys(action.choice for action in actions) if name is not None]
    if choice_names:
        return {
            "journey": None,
            "choices": [
                {
                    "name": name,
                    "safe": not any(finding.choice == name for finding in policy_findings),
                    "findings": [finding.to_json() for finding in policy_findings if finding.choice == name],
                }
                for name in choice_names
            ],
            "tlc_graph": _tlc_graph(tlc_status, dot_path),
            "finding_codes": [finding.code for finding in findings],
        }
    if not policy_findings:
        return {
            "journey": None,
            "tlc_graph": _tlc_graph(tlc_status, dot_path),
            "finding_codes": [finding.code for finding in findings],
        }

    by_action: dict[int, list[SafetyFinding]] = {}
    for finding in policy_findings:
        if finding.action_index is not None:
            by_action.setdefault(finding.action_index, []).append(finding)

    balances = dict(policy.account_balances)
    total_outflow = 0
    nodes: list[dict[str, Any]] = [{
        "state_number": 0,
        "kind": "initial",
        "balances": dict(sorted(balances.items())),
        "total_outflow": total_outflow,
        "budget": policy.budget,
        "violations": [],
    }]
    edges: list[dict[str, Any]] = []
    first_violating_state: int | None = None
    for index, action in enumerate(actions, start=1):
        # Preserve the policy mirror's ordering, including its early continue
        # for a missing debit source account.
        if action.action in DEBIT_ACTION_TYPES and action.source in balances:
            total_outflow += action.amount
            balances[action.source] -= action.amount
            if action.action in CREDIT_ACTION_TYPES and action.destination in balances:
                balances[action.destination] += action.amount
        elif action.action not in DEBIT_ACTION_TYPES:
            if action.action in CREDIT_ACTION_TYPES and action.destination in balances:
                balances[action.destination] += action.amount

        violations = [_visual_finding(finding, policy) for finding in by_action.get(index, [])]
        if violations and first_violating_state is None:
            first_violating_state = index
        nodes.append({
            "state_number": index,
            "kind": "violation" if violations else "state",
            "action_index": index,
            "action": action.to_json(),
            "balances": dict(sorted(balances.items())),
            "total_outflow": total_outflow,
            "budget": policy.budget,
            "violations": violations,
        })
        edges.append({
            "from": index - 1,
            "to": index,
            "label": _action_label(action),
            "counterexample": first_violating_state is None or index <= first_violating_state,
        })

    return {
        "journey": {
            "nodes": nodes,
            "edges": edges,
            "initial_state": 0,
            "first_violating_state": first_violating_state,
            "counterexample_path": list(range((first_violating_state or 0) + 1)),
            "deterministic": True,
        },
        "tlc_graph": _tlc_graph(tlc_status, dot_path),
        # The source-of-truth findings are included as context only. This
        # includes TLC setup findings while node violations remain policy-only.
        "finding_codes": [finding.code for finding in findings],
    }


def _action_label(action: FinanceAction) -> str:
    return f"{action.action} {action.amount}: {action.source} → {action.destination}"


def _visual_finding(finding: SafetyFinding, policy: SafetyPolicy) -> dict[str, Any]:
    payload = dict(finding.to_json())
    values: dict[str, Any] = {
        "budget_exceeded": policy.budget,
        "individual_action_limit_exceeded": policy.max_individual_action_amount,
        "disallowed_destination": sorted(policy.allowed_destination_accounts),
        "disallowed_action_kind": sorted(policy.allowed_action_types),
    }
    if finding.code in values:
        payload["policy_value"] = values[finding.code]
    return payload


def _tlc_graph(tlc_status: str, dot_path: Path | None) -> dict[str, Any]:
    if tlc_status == "skipped":
        return {"status": "unavailable", "message": "TLC was disabled for this run."}
    if dot_path is None or not dot_path.is_file():
        return {"status": "unavailable", "message": "TLC did not produce a readable state graph."}
    try:
        dot = dot_path.read_text(encoding="utf-8", errors="replace")
        nodes, edges = parse_tlc_dot(dot)
    except (OSError, ValueError):
        return {"status": "unavailable", "message": "TLC state graph could not be parsed."}
    if not nodes:
        return {"status": "unavailable", "message": "TLC state graph contained no states."}
    return {
        "status": "available",
        "nodes": nodes,
        "edges": edges,
        "dot": dot,
        # The generated v1 model is deterministic, so every explored edge on
        # a failed TLC run is its counterexample path. Future branching models
        # can replace this with an exact trace subset without changing the UI.
        "counterexample_node_ids": [node["id"] for node in nodes] if tlc_status == "failed" else [],
        "violating_node_ids": [node["id"] for node in nodes if _tlc_node_has_violation(node)],
    }


def parse_tlc_dot(dot: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Parse TLC's simple DOT state/edge declarations without trusting HTML."""

    if "digraph" not in dot:
        raise ValueError("invalid DOT output")
    nodes: dict[str, dict[str, str]] = {}
    edges: list[dict[str, str]] = []
    for raw in dot.splitlines():
        line = raw.strip().rstrip(";")
        edge = re.match(r'^"?([^"\s]+)"?\s*->\s*"?([^"\s]+)"?(?:\s*\[(.*)\])?$', line)
        if edge:
            source, target, attrs = edge.groups()
            edges.append({"from": source, "to": target, "label": _dot_label(attrs or "")})
            nodes.setdefault(source, {"id": source, "label": source})
            nodes.setdefault(target, {"id": target, "label": target})
            continue
        node = re.match(r'^"?([^"\s\[\]]+)"?\s*\[(.*)\]$', line)
        if node:
            node_id, attrs = node.groups()
            if node_id in {"node", "edge", "graph"}:
                continue
            nodes[node_id] = {"id": node_id, "label": _dot_label(attrs) or node_id}
    return list(nodes.values()), edges


def _dot_label(attrs: str) -> str:
    match = re.search(r'label\s*=\s*"((?:\\.|[^"\\])*)"', attrs)
    if not match:
        return ""
    return match.group(1).replace(r"\n", "\n").replace(r'\"', '"')


def _tlc_node_has_violation(node: dict[str, str]) -> bool:
    return bool(re.search(r"violations\s*=\s*\{\s*(?!\})", node.get("label", "")))
