import copy
from contextvars import ContextVar
import json
import os
from typing import Any, Dict, Optional

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "finance_data.json")

DEFAULT_DATA: Dict[str, Any] = {
    "transactions": [],
    "budget_limits": {},
    "goals": [],
    "debts": [],
    "risk_profile": None,
}

# When set, all reads/writes go to request-local memory instead of disk.
# The CLI leaves this unset and continues to use DATA_FILE.
_session: ContextVar[Optional[Dict[str, Any]]] = ContextVar("finance_agent_session", default=None)


def init_session(data: Optional[Dict[str, Any]] = None) -> None:
    session = copy.deepcopy(data) if data is not None else copy.deepcopy(DEFAULT_DATA)
    for key, val in DEFAULT_DATA.items():
        if key not in session:
            session[key] = copy.deepcopy(val)
    _session.set(session)


def get_session() -> Optional[Dict[str, Any]]:
    session = _session.get()
    return copy.deepcopy(session) if session is not None else None


def clear_session() -> None:
    _session.set(None)


def load() -> Dict[str, Any]:
    session = _session.get()
    if session is not None:
        return copy.deepcopy(session)
    if not os.path.exists(DATA_FILE):
        return copy.deepcopy(DEFAULT_DATA)
    with open(DATA_FILE) as f:
        data = json.load(f)
    for key, val in DEFAULT_DATA.items():
        if key not in data:
            data[key] = copy.deepcopy(val)
    return data


def save(data: Dict[str, Any]) -> None:
    if _session.get() is not None:
        _session.set(copy.deepcopy(data))
        return
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)
