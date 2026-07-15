"""Python-side mirror of the v1 TLA safety invariants."""

from __future__ import annotations

from dataclasses import dataclass

from safety.models import CREDIT_ACTION_TYPES, DEBIT_ACTION_TYPES, FinanceAction, SafetyPolicy


@dataclass(frozen=True)
class SafetyFinding:
    code: str
    message: str
    action_index: int | None = None
    severity: str = "error"
    choice: str | None = None

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.action_index is not None:
            payload["action_index"] = self.action_index
        if self.choice is not None:
            payload["choice"] = self.choice
        return payload


def evaluate_policy(actions: list[FinanceAction], policy: SafetyPolicy) -> list[SafetyFinding]:
    """Evaluate the deterministic v1 security policy.

    This is not a substitute for TLC. It gives immediate, explainable findings
    and is kept aligned with the generated TLA invariants.
    """

    choice_names = {action.choice for action in actions if action.choice is not None}
    if choice_names:
        if len(choice_names) < 2 or any(action.choice is None for action in actions):
            return [SafetyFinding(
                code="invalid_choice_structure",
                message="Choice actions must contain at least two fully named alternatives.",
            )]
        findings: list[SafetyFinding] = []
        for choice in dict.fromkeys(action.choice for action in actions):
            branch = [action for action in actions if action.choice == choice]
            findings.extend(
                SafetyFinding(
                    code=finding.code,
                    message=finding.message,
                    action_index=finding.action_index,
                    severity=finding.severity,
                    choice=choice,
                )
                for finding in _evaluate_sequence(branch, policy)
            )
        return findings
    return _evaluate_sequence(actions, policy)


def _evaluate_sequence(actions: list[FinanceAction], policy: SafetyPolicy) -> list[SafetyFinding]:
    findings: list[SafetyFinding] = []
    balances = dict(policy.account_balances)
    total_outflow = 0

    for index, action in enumerate(actions, start=1):
        if action.action not in policy.allowed_action_types:
            findings.append(
                SafetyFinding(
                    code="disallowed_action_kind",
                    action_index=index,
                    message=(
                        f"Action {index} uses '{action.action}', which is not in the "
                        "user-approved action type set."
                    ),
                )
            )

        if action.amount <= 0:
            findings.append(
                SafetyFinding(
                    code="non_positive_amount",
                    action_index=index,
                    message=f"Action {index} has a non-positive amount: {action.amount}.",
                )
            )

        if action.amount > policy.max_individual_action_amount:
            findings.append(
                SafetyFinding(
                    code="individual_action_limit_exceeded",
                    action_index=index,
                    message=(
                        f"Action {index} amount {action.amount} exceeds the per-action limit "
                        f"of {policy.max_individual_action_amount}."
                    ),
                )
            )

        if action.destination not in policy.allowed_destination_accounts:
            findings.append(
                SafetyFinding(
                    code="disallowed_destination",
                    action_index=index,
                    message=(
                        f"Action {index} sends money to '{action.destination}', which is not "
                        "an allowed destination account."
                    ),
                )
            )

        if action.action in DEBIT_ACTION_TYPES:
            if action.source not in balances:
                findings.append(
                    SafetyFinding(
                        code="unknown_source_account",
                        action_index=index,
                        message=(
                            f"Action {index} debits '{action.source}', but that source account "
                            "is not present in account_balances."
                        ),
                    )
                )
                continue

            total_outflow += action.amount
            balances[action.source] -= action.amount

            if total_outflow > policy.budget:
                findings.append(
                    SafetyFinding(
                        code="budget_exceeded",
                        action_index=index,
                        message=(
                            f"Action {index} brings total planned outflow to {total_outflow}, "
                            f"which exceeds the user budget of {policy.budget}."
                        ),
                    )
                )

            if balances[action.source] < 0:
                findings.append(
                    SafetyFinding(
                        code="negative_source_balance",
                        action_index=index,
                        message=(
                            f"Action {index} would make '{action.source}' negative "
                            f"({balances[action.source]})."
                        ),
                    )
                )

        if action.action in CREDIT_ACTION_TYPES and action.destination in balances:
            balances[action.destination] += action.amount

    return findings
