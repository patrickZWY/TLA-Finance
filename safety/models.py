"""Data models for the finance safety gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ALLOWED_ACTION_TYPES = {
    "buy",
    "sell",
    "swap",
    "deposit",
    "transfer",
    "withdraw",
}

DEBIT_ACTION_TYPES = {
    "buy",
    "swap",
    "transfer",
    "withdraw",
}

CREDIT_ACTION_TYPES = {
    "buy",
    "sell",
    "swap",
    "deposit",
    "transfer",
    "withdraw",
}


class SafetyInputError(ValueError):
    """Raised when action or policy input cannot be checked safely."""


@dataclass(frozen=True)
class FinanceAction:
    """A concrete action proposed by the finance agent."""

    action: str
    amount: int
    source: str
    destination: str
    choice: str | None = None

    @classmethod
    def from_json(cls, raw: dict[str, Any], index: int) -> "FinanceAction":
        missing = [key for key in ("action", "amount", "from", "to") if key not in raw]
        if missing:
            raise SafetyInputError(f"action {index} missing required field(s): {', '.join(missing)}")

        action = str(raw["action"]).strip().lower()
        source = str(raw["from"]).strip()
        destination = str(raw["to"]).strip()
        amount = _parse_integer_amount(raw["amount"], f"action {index} amount")

        if not action:
            raise SafetyInputError(f"action {index} has an empty action type")
        if not source:
            raise SafetyInputError(f"action {index} has an empty from account")
        if not destination:
            raise SafetyInputError(f"action {index} has an empty to account")

        choice_raw = raw.get("choice")
        choice = str(choice_raw).strip() if choice_raw is not None else None
        if choice == "":
            raise SafetyInputError(f"action {index} has an empty choice name")
        return cls(action=action, amount=amount, source=source, destination=destination, choice=choice)

    def to_json(self) -> dict[str, Any]:
        payload = {
            "action": self.action,
            "amount": self.amount,
            "from": self.source,
            "to": self.destination,
        }
        if self.choice is not None:
            payload["choice"] = self.choice
        return payload


@dataclass(frozen=True)
class SafetyPolicy:
    """User-designated safety policy used as TLA constants."""

    budget: int
    max_individual_action_amount: int
    account_balances: dict[str, int]
    allowed_destination_accounts: set[str]
    allowed_action_types: set[str]

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "SafetyPolicy":
        missing = [
            key
            for key in ("budget", "account_balances", "allowed_destination_accounts")
            if key not in raw
        ]
        if missing:
            raise SafetyInputError(f"policy missing required field(s): {', '.join(missing)}")

        budget = _parse_integer_amount(raw["budget"], "policy budget")
        if budget < 0:
            raise SafetyInputError("policy budget must be non-negative")

        max_individual_action_amount = _parse_integer_amount(
            raw.get("max_individual_action_amount", budget),
            "policy max_individual_action_amount",
        )
        if max_individual_action_amount < 0:
            raise SafetyInputError("policy max_individual_action_amount must be non-negative")

        balances_raw = raw["account_balances"]
        if not isinstance(balances_raw, dict) or not balances_raw:
            raise SafetyInputError("policy account_balances must be a non-empty object")

        balances: dict[str, int] = {}
        for account, amount in balances_raw.items():
            name = str(account).strip()
            if not name:
                raise SafetyInputError("policy account_balances contains an empty account name")
            balances[name] = _parse_integer_amount(amount, f"balance for {name}")

        destinations_raw = raw["allowed_destination_accounts"]
        if not isinstance(destinations_raw, list) or not destinations_raw:
            raise SafetyInputError("policy allowed_destination_accounts must be a non-empty list")
        destinations = {str(account).strip() for account in destinations_raw}
        if "" in destinations:
            raise SafetyInputError("policy allowed_destination_accounts contains an empty account name")

        action_types_raw = raw.get("allowed_action_types", sorted(ALLOWED_ACTION_TYPES))
        if not isinstance(action_types_raw, list) or not action_types_raw:
            raise SafetyInputError("policy allowed_action_types must be a non-empty list")
        action_types = {str(action).strip().lower() for action in action_types_raw}
        if "" in action_types:
            raise SafetyInputError("policy allowed_action_types contains an empty action type")

        return cls(
            budget=budget,
            max_individual_action_amount=max_individual_action_amount,
            account_balances=balances,
            allowed_destination_accounts=destinations,
            allowed_action_types=action_types,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "budget": self.budget,
            "max_individual_action_amount": self.max_individual_action_amount,
            "account_balances": dict(sorted(self.account_balances.items())),
            "allowed_destination_accounts": sorted(self.allowed_destination_accounts),
            "allowed_action_types": sorted(self.allowed_action_types),
        }


def load_actions(raw: dict[str, Any], allow_empty: bool = False) -> list[FinanceAction]:
    if "choices" in raw:
        if raw.get("actions") is not None:
            raise SafetyInputError("choices JSON must not also contain an actions list")
        choices_raw = raw["choices"]
        if not isinstance(choices_raw, list) or len(choices_raw) < 2:
            raise SafetyInputError("choices JSON must contain at least two choices")
        actions: list[FinanceAction] = []
        for choice_index, choice_raw in enumerate(choices_raw, start=1):
            if not isinstance(choice_raw, dict):
                raise SafetyInputError(f"choice {choice_index} must be an object")
            name = str(choice_raw.get("name", "")).strip()
            branch_actions = choice_raw.get("actions")
            if not name:
                raise SafetyInputError(f"choice {choice_index} has an empty name")
            if not isinstance(branch_actions, list) or not branch_actions:
                raise SafetyInputError(f"choice {choice_index} must contain a non-empty actions list")
            for action_index, action_raw in enumerate(branch_actions, start=1):
                if not isinstance(action_raw, dict):
                    raise SafetyInputError(f"choice {choice_index} action {action_index} must be an object")
                actions.append(FinanceAction.from_json({**action_raw, "choice": name}, action_index))
        return actions
    actions_raw = raw.get("actions")
    if not isinstance(actions_raw, list):
        raise SafetyInputError("actions JSON must contain an actions list")
    if not actions_raw and not allow_empty:
        raise SafetyInputError("actions list must not be empty")

    actions: list[FinanceAction] = []
    for index, item in enumerate(actions_raw, start=1):
        if not isinstance(item, dict):
            raise SafetyInputError(f"action {index} must be an object")
        actions.append(FinanceAction.from_json(item, index))
    return actions


def dump_actions(actions: list[FinanceAction]) -> dict[str, Any]:
    choice_names = [name for name in dict.fromkeys(action.choice for action in actions) if name is not None]
    if choice_names:
        return {"choices": [
            {"name": name, "actions": [
                {key: value for key, value in action.to_json().items() if key != "choice"}
                for action in actions if action.choice == name
            ]}
            for name in choice_names
        ]}
    return {"actions": [action.to_json() for action in actions]}


def _parse_integer_amount(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise SafetyInputError(f"{label} must be an integer amount")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
    raise SafetyInputError(f"{label} must be an integer amount")
