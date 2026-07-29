"""Typed Finance Specification IR (FSIR) v0.1 and legacy adapters.

FSIR is the audited boundary between prose interpretation and deterministic
formal-model lowering.  It intentionally uses a closed expression/update
vocabulary: arbitrary Python, TLA+, SMT, or other backend snippets are not
accepted as data.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, Optional, Union

import pydantic
from pydantic import (
    BaseModel,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    root_validator,
    validator,
)


Scalar = Union[StrictBool, StrictInt, StrictStr]
ValueType = Literal[
    "money",
    "asset_notional",
    "integer",
    "enum",
    "boolean",
    "string",
    "account_id",
    "instrument_id",
]
IntentClassification = Literal["action_plan", "no_action", "underspecified_action"]
BudgetSemantics = Literal[
    "gross_debit",
    "external_outflow",
    "net_spend",
    "not_applicable",
    "unresolved",
]


if int(pydantic.VERSION.split(".", maxsplit=1)[0]) >= 2:
    from pydantic import ConfigDict

    class ClosedModel(BaseModel):
        """Pydantic base that rejects unknown fields at every FSIR layer."""

        model_config = ConfigDict(
            extra="forbid",
            populate_by_name=True,
            validate_assignment=True,
        )

else:

    class ClosedModel(BaseModel):
        """Pydantic v1 compatibility base with the same closed contract."""

        class Config:
            extra = "forbid"
            allow_population_by_field_name = True
            validate_assignment = True


def _dump_model(model: BaseModel, **kwargs: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)  # type: ignore[attr-defined,no-any-return]
    return model.dict(**kwargs)


def _model_schema(model_type: type[BaseModel]) -> dict[str, Any]:
    if hasattr(model_type, "model_json_schema"):
        return model_type.model_json_schema()  # type: ignore[attr-defined,no-any-return]
    return model_type.schema()


def _validate_node_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", value):
        raise ValueError(
            "IDs must start with a letter and contain only letters, digits, '.', '_', or '-'"
        )
    return value


class SourceSpan(ClosedModel):
    id: str
    source_id: str
    text: str
    start: StrictInt
    end: StrictInt
    origin: Literal[
        "stated",
        "derived_deterministically",
        "selected_by_human",
        "model_proposed",
        "model_assumption",
    ]

    _id_format = validator("id", "source_id", allow_reuse=True)(_validate_node_id)

    @root_validator(skip_on_failure=True)
    def _valid_offsets(cls, values: dict[str, Any]) -> dict[str, Any]:
        start = values.get("start")
        end = values.get("end")
        text = values.get("text", "")
        if start is not None and end is not None:
            if start < 0 or end < start:
                raise ValueError("source span offsets must satisfy 0 <= start <= end")
            if end - start != len(text):
                raise ValueError("source span offsets must match the span text length")
        return values


class Derivation(ClosedModel):
    node_id: str
    method: Literal[
        "stated",
        "deterministic_adapter",
        "human_reviewed_seed",
        "human_selected",
        "model_proposed",
    ]
    source_span_ids: list[str] = Field(default_factory=list)

    _id_format = validator("node_id", allow_reuse=True)(_validate_node_id)


class Provenance(ClosedModel):
    sources: list[str] = Field(default_factory=list)
    spans: list[SourceSpan] = Field(default_factory=list)
    derivations: list[Derivation] = Field(default_factory=list)


class ToolIdentity(ClosedModel):
    name: StrictStr
    version: StrictStr


class FsirMeta(ClosedModel):
    id: str
    schema_version: Literal["fsir-0.1"] = "fsir-0.1"
    source_document_sha256: StrictStr
    domain_profile: StrictStr
    intent: IntentClassification
    currency: Literal["USD"]
    budget_semantics: BudgetSemantics
    created_by: ToolIdentity

    _id_format = validator("id", allow_reuse=True)(_validate_node_id)

    @validator("source_document_sha256")
    def _real_sha256(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("source_document_sha256 must be a lowercase 64-hex digest")
        return value


class ActorSymbol(ClosedModel):
    id: str
    role: Literal["user", "agent", "external_service"]
    label: StrictStr
    source_span_ids: list[str] = Field(default_factory=list)

    _id_format = validator("id", allow_reuse=True)(_validate_node_id)


class AccountSymbol(ClosedModel):
    id: str
    kind: Literal["cash_account"] = "cash_account"
    label: StrictStr
    currency: Literal["USD"]
    source_span_ids: list[str] = Field(default_factory=list)

    _id_format = validator("id", allow_reuse=True)(_validate_node_id)


class InstrumentSymbol(ClosedModel):
    id: str
    kind: Literal["instrument"] = "instrument"
    label: StrictStr
    source_span_ids: list[str] = Field(default_factory=list)

    _id_format = validator("id", allow_reuse=True)(_validate_node_id)


class AssetPositionSymbol(ClosedModel):
    id: str
    kind: Literal["asset_position"] = "asset_position"
    account_id: str
    instrument_id: str
    unit: Literal["USD_notional"]
    source_span_ids: list[str] = Field(default_factory=list)

    _id_format = validator(
        "id", "account_id", "instrument_id", allow_reuse=True
    )(_validate_node_id)


class SymbolTable(ClosedModel):
    actors: list[ActorSymbol] = Field(default_factory=list)
    accounts: list[AccountSymbol] = Field(default_factory=list)
    instruments: list[InstrumentSymbol] = Field(default_factory=list)
    asset_positions: list[AssetPositionSymbol] = Field(default_factory=list)

    @root_validator(skip_on_failure=True)
    def _unique_and_resolved(cls, values: dict[str, Any]) -> dict[str, Any]:
        groups = [
            values.get("actors", []),
            values.get("accounts", []),
            values.get("instruments", []),
            values.get("asset_positions", []),
        ]
        ids = [item.id for group in groups for item in group]
        _require_unique(ids, "symbol")
        account_ids = {item.id for item in values.get("accounts", [])}
        instrument_ids = {item.id for item in values.get("instruments", [])}
        for position in values.get("asset_positions", []):
            if position.account_id not in account_ids:
                raise ValueError(
                    f"asset position {position.id} references unknown account {position.account_id}"
                )
            if position.instrument_id not in instrument_ids:
                raise ValueError(
                    f"asset position {position.id} references unknown instrument "
                    f"{position.instrument_id}"
                )
        return values


class StateType(ClosedModel):
    kind: Literal["money", "asset_notional", "integer", "boolean", "enum"]
    currency: Optional[Literal["USD"]] = None
    instrument_id: Optional[str] = None
    values: list[Scalar] = Field(default_factory=list)

    _instrument_id_format = validator(
        "instrument_id", allow_reuse=True
    )(lambda value: _validate_node_id(value) if value is not None else value)

    @root_validator(skip_on_failure=True)
    def _shape(cls, values: dict[str, Any]) -> dict[str, Any]:
        kind = values.get("kind")
        currency = values.get("currency")
        instrument_id = values.get("instrument_id")
        enum_values = values.get("values", [])
        if kind == "money" and currency != "USD":
            raise ValueError("money state requires currency='USD'")
        if kind == "asset_notional":
            if currency != "USD" or not instrument_id:
                raise ValueError(
                    "asset_notional state requires currency='USD' and instrument_id"
                )
        if kind == "enum" and not enum_values:
            raise ValueError("enum state requires a non-empty values domain")
        if kind != "enum" and enum_values:
            raise ValueError("values is only valid for enum state")
        if kind not in {"money", "asset_notional"} and currency is not None:
            raise ValueError("currency is only valid for money/asset_notional state")
        if kind != "asset_notional" and instrument_id is not None:
            raise ValueError("instrument_id is only valid for asset_notional state")
        return values


class StateVariable(ClosedModel):
    id: str
    symbol_id: Optional[str] = None
    type: StateType
    initial: Optional[Scalar] = None
    initial_domain_bound_id: Optional[str] = None
    observable: StrictBool = True
    source_span_ids: list[str] = Field(default_factory=list)

    _id_format = validator("id", allow_reuse=True)(_validate_node_id)
    _symbol_id_format = validator(
        "symbol_id", allow_reuse=True
    )(lambda value: _validate_node_id(value) if value is not None else value)

    @root_validator(skip_on_failure=True)
    def _initial_matches_type(cls, values: dict[str, Any]) -> dict[str, Any]:
        initial = values.get("initial")
        initial_domain_bound_id = values.get("initial_domain_bound_id")
        state_type: StateType | None = values.get("type")
        if (initial is None) == (initial_domain_bound_id is None):
            raise ValueError(
                "state requires exactly one of initial or initial_domain_bound_id"
            )
        if initial is None or state_type is None:
            return values
        if state_type.kind in {"money", "asset_notional", "integer"}:
            if isinstance(initial, bool) or not isinstance(initial, int):
                raise ValueError(f"{state_type.kind} initial value must be an integer")
        elif state_type.kind == "boolean" and not isinstance(initial, bool):
            raise ValueError("boolean initial value must be a boolean")
        elif state_type.kind == "enum" and initial not in state_type.values:
            raise ValueError("enum initial value must be in its declared values domain")
        return values


ExpressionOp = Literal[
    "literal",
    "set_literal",
    "state_ref",
    "action_parameter_ref",
    "not",
    "and",
    "or",
    "eq",
    "neq",
    "gte",
    "gt",
    "lte",
    "lt",
    "add",
    "sub",
    "in",
    "always",
    "eventually",
    "precedence",
    "well_typed_state",
]


class Expression(ClosedModel):
    """Closed recursive expression AST."""

    op: ExpressionOp
    value: Optional[Scalar] = None
    values: list[Scalar] = Field(default_factory=list)
    value_type: Optional[ValueType] = None
    unit: Optional[Literal["USD", "USD_notional"]] = None
    state_id: Optional[str] = None
    action_id: Optional[str] = None
    parameter_name: Optional[str] = None
    event_ids: list[str] = Field(default_factory=list)
    left: Optional["Expression"] = None
    right: Optional["Expression"] = None
    args: list["Expression"] = Field(default_factory=list)

    _state_id_format = validator(
        "state_id", allow_reuse=True
    )(lambda value: _validate_node_id(value) if value is not None else value)
    _action_id_format = validator(
        "action_id", allow_reuse=True
    )(lambda value: _validate_node_id(value) if value is not None else value)

    @validator("event_ids", each_item=True)
    def _event_id_format(cls, value: str) -> str:
        return _validate_node_id(value)

    @root_validator(skip_on_failure=True)
    def _operator_shape(cls, values: dict[str, Any]) -> dict[str, Any]:
        op = values.get("op")
        present: set[str] = set()
        for field in (
            "value",
            "value_type",
            "unit",
            "state_id",
            "action_id",
            "parameter_name",
            "left",
            "right",
        ):
            if values.get(field) is not None:
                present.add(field)
        for field in ("values", "event_ids", "args"):
            if values.get(field):
                present.add(field)

        allowed: set[str]
        required: set[str]
        if op == "literal":
            allowed, required = {"value", "value_type", "unit"}, {"value", "value_type"}
        elif op == "set_literal":
            allowed, required = {"values", "value_type", "unit"}, {"values", "value_type"}
        elif op == "state_ref":
            allowed, required = {"state_id"}, {"state_id"}
        elif op == "action_parameter_ref":
            allowed, required = {"action_id", "parameter_name"}, {
                "action_id",
                "parameter_name",
            }
        elif op in {"not", "always", "eventually"}:
            allowed, required = {"args"}, {"args"}
            if len(values.get("args", [])) != 1:
                raise ValueError(f"{op} requires exactly one argument")
        elif op in {"and", "or"}:
            allowed, required = {"args"}, {"args"}
            if len(values.get("args", [])) < 2:
                raise ValueError(f"{op} requires at least two arguments")
        elif op in {"eq", "neq", "gte", "gt", "lte", "lt", "add", "sub", "in"}:
            allowed, required = {"left", "right"}, {"left", "right"}
        elif op == "precedence":
            allowed, required = {"event_ids"}, {"event_ids"}
            if len(values.get("event_ids", [])) != 2:
                raise ValueError("precedence requires [predecessor, successor]")
        elif op == "well_typed_state":
            allowed, required = set(), set()
        else:
            raise ValueError(f"unsupported expression operator: {op}")

        extra = present - allowed
        missing = required - present
        if extra:
            raise ValueError(f"{op} does not allow fields: {', '.join(sorted(extra))}")
        if missing:
            raise ValueError(f"{op} requires fields: {', '.join(sorted(missing))}")
        if op in {"literal", "set_literal"}:
            value_type = values.get("value_type")
            unit = values.get("unit")
            required_unit = {
                "money": "USD",
                "asset_notional": "USD_notional",
            }.get(value_type)
            if required_unit is not None and unit != required_unit:
                raise ValueError(
                    f"{value_type} literals require unit='{required_unit}'"
                )
            if required_unit is None and unit is not None:
                raise ValueError(
                    "unit is only valid for money/asset_notional literals"
                )
            literal_values = (
                [values.get("value")]
                if op == "literal"
                else list(values.get("values", []))
            )
            for literal_value in literal_values:
                if value_type in {"money", "asset_notional", "integer"}:
                    if isinstance(literal_value, bool) or not isinstance(literal_value, int):
                        raise ValueError(f"{value_type} literals must contain integers")
                elif value_type == "boolean" and not isinstance(literal_value, bool):
                    raise ValueError("boolean literals must contain booleans")
                elif value_type in {
                    "enum",
                    "string",
                    "account_id",
                    "instrument_id",
                } and not isinstance(
                    literal_value, str
                ):
                    raise ValueError(f"{value_type} literals must contain strings")
        return values


try:
    Expression.model_rebuild()  # type: ignore[attr-defined]
except AttributeError:
    Expression.update_forward_refs()


class ActionParameter(ClosedModel):
    name: str
    value: Scalar
    value_type: Literal["money", "account_id", "instrument_id", "string"]
    unit: Optional[Literal["USD"]] = None

    @validator("name")
    def _name_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("action parameter names must not be empty")
        return value

    @root_validator(skip_on_failure=True)
    def _money_unit(cls, values: dict[str, Any]) -> dict[str, Any]:
        value_type = values.get("value_type")
        value = values.get("value")
        if value_type == "money" and values.get("unit") != "USD":
            raise ValueError("money parameters require unit='USD'")
        if value_type != "money" and values.get("unit") is not None:
            raise ValueError("unit is only valid for money parameters")
        if value_type == "money":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("money parameter values must be integers")
        elif not isinstance(value, str):
            raise ValueError(f"{value_type} parameter values must be strings")
        return values


class StateUpdate(ClosedModel):
    op: Literal["set", "add", "sub"]
    target_state_id: str
    value: Expression

    _target_format = validator(
        "target_state_id", allow_reuse=True
    )(_validate_node_id)


class ActionOutcome(ClosedModel):
    id: str
    guard: Expression
    updates: list[StateUpdate]
    source_span_ids: list[str] = Field(default_factory=list)

    _id_format = validator("id", allow_reuse=True)(_validate_node_id)


class FsirAction(ClosedModel):
    id: str
    intent_id: str
    kind: Literal[
        "legacy_atomic",
        "submit",
        "environment_outcome",
        "conditional_outcome",
    ]
    actor_id: str
    parameters: list[ActionParameter] = Field(default_factory=list)
    guard: Expression
    updates: list[StateUpdate] = Field(default_factory=list)
    outcomes: list[ActionOutcome] = Field(default_factory=list)
    reads: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    atomicity_group: str
    source_span_ids: list[str] = Field(default_factory=list)

    _id_format = validator(
        "id", "intent_id", "actor_id", "atomicity_group", allow_reuse=True
    )(_validate_node_id)

    @validator("reads", "writes", each_item=True)
    def _state_id_format(cls, value: str) -> str:
        return _validate_node_id(value)

    @root_validator(skip_on_failure=True)
    def _outcome_shape(cls, values: dict[str, Any]) -> dict[str, Any]:
        kind = values.get("kind")
        updates = values.get("updates", [])
        outcomes = values.get("outcomes", [])
        if kind == "conditional_outcome":
            if updates or len(outcomes) < 2:
                raise ValueError(
                    "conditional_outcome requires at least two outcomes and no direct updates"
                )
        elif outcomes:
            raise ValueError("outcomes are only valid for conditional_outcome actions")
        _require_unique(
            [parameter.name for parameter in values.get("parameters", [])],
            "action parameter name",
        )
        _require_unique(
            [outcome.id for outcome in outcomes],
            "action outcome",
        )
        return values


class ControlEdge(ClosedModel):
    before: str
    after: str

    _id_format = validator("before", "after", allow_reuse=True)(_validate_node_id)


class ControlBranch(ClosedModel):
    id: str
    name: StrictStr
    action_ids: list[str]

    _id_format = validator("id", allow_reuse=True)(_validate_node_id)

    @validator("action_ids", each_item=True)
    def _action_id_format(cls, value: str) -> str:
        return _validate_node_id(value)

    @validator("name")
    def _name_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("control branch names must not be empty")
        return value


class Control(ClosedModel):
    kind: Literal["none", "sequence", "choice", "parallel", "partial_order", "ambiguous"]
    nodes: list[str] = Field(default_factory=list)
    edges: list[ControlEdge] = Field(default_factory=list)
    branches: list[ControlBranch] = Field(default_factory=list)

    @validator("nodes", each_item=True)
    def _node_format(cls, value: str) -> str:
        return _validate_node_id(value)

    @root_validator(skip_on_failure=True)
    def _shape(cls, values: dict[str, Any]) -> dict[str, Any]:
        kind = values.get("kind")
        nodes = values.get("nodes", [])
        edges = values.get("edges", [])
        branches = values.get("branches", [])
        if kind == "none" and (nodes or edges or branches):
            raise ValueError("none control must not contain nodes, edges, or branches")
        if kind == "choice":
            if len(branches) < 2:
                raise ValueError("choice control requires at least two branches")
        elif branches:
            raise ValueError("branches are only valid for choice control")
        if kind in {"sequence", "partial_order"} and nodes and len(nodes) > 1 and not edges:
            raise ValueError(f"{kind} control with multiple nodes requires ordering edges")
        return values


class Property(ClosedModel):
    id: str
    kind: Literal["invariant", "action_constraint", "trace", "liveness"]
    formula: Expression
    severity: Literal["error", "warning"]
    finding_code: Optional[StrictStr] = None
    source_span_ids: list[str] = Field(default_factory=list)

    _id_format = validator("id", allow_reuse=True)(_validate_node_id)

    @root_validator(skip_on_failure=True)
    def _property_shape(cls, values: dict[str, Any]) -> dict[str, Any]:
        kind = values.get("kind")
        formula: Expression | None = values.get("formula")
        if kind == "liveness" and formula is not None and formula.op != "eventually":
            raise ValueError("liveness properties must use an eventually formula")
        if kind == "invariant" and formula is not None and formula.op in {
            "eventually",
            "precedence",
        }:
            raise ValueError("invariants must be state formulas")
        return values


class Assumption(ClosedModel):
    id: str
    kind: Literal[
        "environment",
        "weak_fairness",
        "strong_fairness",
        "timing",
        "trusted_fact",
    ]
    formula: Optional[Expression] = None
    action_ids: list[str] = Field(default_factory=list)
    source_span_ids: list[str] = Field(default_factory=list)

    _id_format = validator("id", allow_reuse=True)(_validate_node_id)

    @validator("action_ids", each_item=True)
    def _action_id_format(cls, value: str) -> str:
        return _validate_node_id(value)

    @root_validator(skip_on_failure=True)
    def _fairness_shape(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values.get("kind") in {"weak_fairness", "strong_fairness"} and not values.get(
            "action_ids"
        ):
            raise ValueError("fairness assumptions require at least one action ID")
        return values


class DomainBound(ClosedModel):
    id: str
    kind: Literal["integer_set", "enum_set"]
    values: list[Scalar]

    _id_format = validator("id", allow_reuse=True)(_validate_node_id)

    @validator("values")
    def _non_empty_unique(cls, value: list[Scalar]) -> list[Scalar]:
        if not value:
            raise ValueError("domain bounds require at least one value")
        if len({(type(item).__name__, item) for item in value}) != len(value):
            raise ValueError("domain bound values must be unique")
        return value

    @root_validator(skip_on_failure=True)
    def _typed_values(cls, values: dict[str, Any]) -> dict[str, Any]:
        kind = values.get("kind")
        domain_values = values.get("values", [])
        if kind == "integer_set" and any(
            isinstance(item, bool) or not isinstance(item, int)
            for item in domain_values
        ):
            raise ValueError("integer_set values must all be integers")
        if kind == "enum_set" and any(
            not isinstance(item, str) for item in domain_values
        ):
            raise ValueError("enum_set values must all be strings")
        return values


class Bounds(ClosedModel):
    max_actions: StrictInt
    max_steps: StrictInt
    max_retries: StrictInt
    time_horizon: StrictInt
    domains: list[DomainBound] = Field(default_factory=list)

    @validator("max_actions", "max_steps", "max_retries", "time_horizon")
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("bounds must be non-negative")
        return value


class UnresolvedItem(ClosedModel):
    id: str
    kind: Literal[
        "missing_value",
        "ambiguous_order",
        "unknown_identity",
        "unsupported_construct",
        "conflict",
        "missing_semantics",
    ]
    severity: Literal["blocking", "warning"]
    blocks: list[str] = Field(default_factory=list)
    question: StrictStr
    source_span_ids: list[str] = Field(default_factory=list)

    _id_format = validator("id", allow_reuse=True)(_validate_node_id)

    @validator("blocks", each_item=True)
    def _block_id_format(cls, value: str) -> str:
        return _validate_node_id(value)


LegacyActionKind = Literal["buy", "sell", "swap", "deposit", "transfer", "withdraw"]


class LegacyAction(ClosedModel):
    action: LegacyActionKind
    amount: StrictInt
    source: StrictStr = Field(alias="from")
    destination: StrictStr = Field(alias="to")
    choice: Optional[StrictStr] = None

    @validator("action", "source", "destination")
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy action strings must not be empty")
        return value


class LegacyChoice(ClosedModel):
    name: StrictStr
    actions: list[LegacyAction]

    @validator("name")
    def _name_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy choice name must not be empty")
        return value

    @validator("actions")
    def _actions_non_empty(cls, value: list[LegacyAction]) -> list[LegacyAction]:
        if not value:
            raise ValueError("legacy choice actions must not be empty")
        return value


class LegacyPlan(ClosedModel):
    actions: Optional[list[LegacyAction]] = None
    choices: Optional[list[LegacyChoice]] = None

    @root_validator(skip_on_failure=True)
    def _one_representation(cls, values: dict[str, Any]) -> dict[str, Any]:
        actions = values.get("actions")
        choices = values.get("choices")
        if (actions is None) == (choices is None):
            raise ValueError("legacy plan must contain exactly one of actions or choices")
        if choices is not None and len(choices) < 2:
            raise ValueError("legacy choices must contain at least two alternatives")
        return values

    def action_count(self) -> int:
        if self.actions is not None:
            return len(self.actions)
        return sum(len(choice.actions) for choice in self.choices or [])


class LegacyIdMap(ClosedModel):
    legacy_path: StrictStr
    fsir_action_id: str

    _id_format = validator("fsir_action_id", allow_reuse=True)(_validate_node_id)


class LegacyCompatibility(ClosedModel):
    format: Literal["finance-actions-v1"] = "finance-actions-v1"
    plan: LegacyPlan
    id_map: list[LegacyIdMap] = Field(default_factory=list)


def _expression_type(
    expression: Expression,
    *,
    state_by_id: dict[str, StateVariable],
    action_by_id: dict[str, FsirAction],
) -> str:
    """Infer and validate the semantic type of a closed expression tree."""

    op = expression.op
    if op == "literal":
        return str(expression.value_type)
    if op == "set_literal":
        return f"set:{expression.value_type}"
    if op == "state_ref":
        if expression.state_id not in state_by_id:
            raise ValueError(
                f"expression references unknown state {expression.state_id}"
            )
        return state_by_id[expression.state_id].type.kind  # type: ignore[index]
    if op == "action_parameter_ref":
        if expression.action_id not in action_by_id:
            raise ValueError(
                f"expression references unknown action {expression.action_id}"
            )
        action = action_by_id[expression.action_id]  # type: ignore[index]
        parameters = {item.name: item for item in action.parameters}
        if expression.parameter_name not in parameters:
            raise ValueError(
                f"expression references unknown parameter {expression.parameter_name} "
                f"on action {action.id}"
            )
        return parameters[expression.parameter_name].value_type  # type: ignore[index]
    if op in {"well_typed_state", "precedence"}:
        return "boolean"
    if op in {"not", "always", "eventually"}:
        operand_type = _expression_type(
            expression.args[0],
            state_by_id=state_by_id,
            action_by_id=action_by_id,
        )
        if operand_type != "boolean":
            raise ValueError(f"{op} requires a boolean operand, got {operand_type}")
        return "boolean"
    if op in {"and", "or"}:
        operand_types = {
            _expression_type(
                item,
                state_by_id=state_by_id,
                action_by_id=action_by_id,
            )
            for item in expression.args
        }
        if operand_types != {"boolean"}:
            raise ValueError(f"{op} requires boolean operands, got {sorted(operand_types)}")
        return "boolean"

    left_type = _expression_type(
        expression.left,  # type: ignore[arg-type]
        state_by_id=state_by_id,
        action_by_id=action_by_id,
    )
    right_type = _expression_type(
        expression.right,  # type: ignore[arg-type]
        state_by_id=state_by_id,
        action_by_id=action_by_id,
    )
    if op == "in":
        if right_type != f"set:{left_type}":
            raise ValueError(
                f"in requires a {left_type} set on the right, got {right_type}"
            )
        return "boolean"
    if left_type != right_type:
        raise ValueError(
            f"{op} operands must have the same type, got {left_type} and {right_type}"
        )
    if op in {"eq", "neq"}:
        return "boolean"
    numeric_types = {"money", "asset_notional", "integer"}
    if left_type not in numeric_types:
        raise ValueError(f"{op} requires numeric operands, got {left_type}")
    if op in {"gte", "gt", "lte", "lt"}:
        return "boolean"
    if op in {"add", "sub"}:
        return left_type
    raise ValueError(f"cannot infer type for expression operator {op}")


def _fold_boolean(op: Literal["and", "or"], terms: list[Expression]) -> Expression:
    if not terms:
        return _literal(op == "and", "boolean")
    if len(terms) == 1:
        return terms[0]
    return Expression(op=op, args=terms)


def _fold_numeric_add(terms: list[Expression], value_type: ValueType) -> Expression:
    if not terms:
        unit = "USD" if value_type == "money" else None
        return _literal(0, value_type, unit)
    result = terms[0]
    for term in terms[1:]:
        result = Expression(op="add", left=result, right=term)
    return result


class FsirDocument(ClosedModel):
    meta: FsirMeta
    symbols: SymbolTable
    state: list[StateVariable]
    actions: list[FsirAction]
    control: Control
    properties: list[Property]
    assumptions: list[Assumption]
    bounds: Bounds
    unresolved: list[UnresolvedItem]
    provenance: Provenance
    compatibility: LegacyCompatibility

    @root_validator(skip_on_failure=True)
    def _validate_document(cls, values: dict[str, Any]) -> dict[str, Any]:
        meta: FsirMeta = values["meta"]
        symbols: SymbolTable = values["symbols"]
        state: list[StateVariable] = values.get("state", [])
        actions: list[FsirAction] = values.get("actions", [])
        properties: list[Property] = values.get("properties", [])
        assumptions: list[Assumption] = values.get("assumptions", [])
        bounds: Bounds = values["bounds"]
        unresolved: list[UnresolvedItem] = values.get("unresolved", [])
        provenance: Provenance = values["provenance"]
        control: Control = values["control"]
        compatibility: LegacyCompatibility = values["compatibility"]

        state_ids = {item.id for item in state}
        state_by_id = {item.id: item for item in state}
        action_ids = {item.id for item in actions}
        action_by_id = {item.id: item for item in actions}
        outcome_ids = {
            outcome.id for action in actions for outcome in action.outcomes
        }
        property_ids = {item.id for item in properties}
        assumption_ids = {item.id for item in assumptions}
        unresolved_ids = {item.id for item in unresolved}
        _require_unique([item.id for item in state], "state")
        _require_unique([item.id for item in actions], "action")
        _require_unique(
            [outcome.id for action in actions for outcome in action.outcomes],
            "action outcome",
        )
        _require_unique([item.id for item in properties], "property")
        _require_unique([item.id for item in assumptions], "assumption")
        _require_unique([item.id for item in unresolved], "unresolved item")
        _require_unique([item.id for item in bounds.domains], "domain bound")

        actor_ids = {item.id for item in symbols.actors}
        account_ids = {item.id for item in symbols.accounts}
        instrument_ids = {item.id for item in symbols.instruments}
        symbol_ids = {
            item.id
            for group in (
                symbols.actors,
                symbols.accounts,
                symbols.instruments,
                symbols.asset_positions,
            )
            for item in group
        }
        span_ids = {span.id for span in provenance.spans}
        source_ids = set(provenance.sources)
        _require_unique(provenance.sources, "provenance source")
        _require_unique([span.id for span in provenance.spans], "source span")
        for span in provenance.spans:
            if span.source_id not in source_ids:
                raise ValueError(
                    f"source span {span.id} references unknown source {span.source_id}"
                )

        for group in (
            symbols.actors,
            symbols.accounts,
            symbols.instruments,
            symbols.asset_positions,
        ):
            for symbol in group:
                _require_subset(
                    symbol.source_span_ids,
                    span_ids,
                    f"symbol {symbol.id} spans",
                )

        for variable in state:
            if variable.symbol_id and variable.symbol_id not in symbol_ids:
                raise ValueError(
                    f"state {variable.id} references unknown symbol {variable.symbol_id}"
                )
            _require_subset(variable.source_span_ids, span_ids, f"state {variable.id} spans")
            if variable.type.instrument_id and variable.type.instrument_id not in {
                instrument.id for instrument in symbols.instruments
            }:
                raise ValueError(
                    f"state {variable.id} references unknown instrument "
                    f"{variable.type.instrument_id}"
                )
            if variable.initial_domain_bound_id is not None:
                domain_by_id = {item.id: item for item in bounds.domains}
                if variable.initial_domain_bound_id not in domain_by_id:
                    raise ValueError(
                        f"state {variable.id} references unknown initial domain "
                        f"{variable.initial_domain_bound_id}"
                    )
                domain = domain_by_id[variable.initial_domain_bound_id]
                if variable.type.kind == "boolean":
                    raise ValueError(
                        f"state {variable.id} boolean nondeterminism requires "
                        "an explicit Boolean-domain construct"
                    )
                expected_domain_kind = (
                    "enum_set" if variable.type.kind == "enum" else "integer_set"
                )
                if domain.kind != expected_domain_kind:
                    raise ValueError(
                        f"state {variable.id} requires {expected_domain_kind}, "
                        f"got {domain.kind}"
                    )
                if variable.type.kind == "enum" and not set(domain.values).issubset(
                    set(variable.type.values)
                ):
                    raise ValueError(
                        f"state {variable.id} initial domain exceeds its enum type"
                    )

        for action in actions:
            if action.actor_id not in actor_ids:
                raise ValueError(
                    f"action {action.id} references undeclared actor {action.actor_id}"
                )
            guard_reads = _expression_state_refs(action.guard)
            expression_reads = set(guard_reads)
            referenced_states = set(action.reads) | set(action.writes) | guard_reads
            updated_states: set[str] = set()
            for update in action.updates:
                referenced_states.add(update.target_state_id)
                updated_states.add(update.target_state_id)
                value_reads = _expression_state_refs(update.value)
                expression_reads |= value_reads
                referenced_states |= value_reads
                if update.op in {"add", "sub"}:
                    expression_reads.add(update.target_state_id)
            for outcome in action.outcomes:
                outcome_guard_reads = _expression_state_refs(outcome.guard)
                expression_reads |= outcome_guard_reads
                referenced_states |= outcome_guard_reads
                for update in outcome.updates:
                    referenced_states.add(update.target_state_id)
                    updated_states.add(update.target_state_id)
                    value_reads = _expression_state_refs(update.value)
                    expression_reads |= value_reads
                    referenced_states |= value_reads
                    if update.op in {"add", "sub"}:
                        expression_reads.add(update.target_state_id)
                _require_subset(
                    outcome.source_span_ids, span_ids, f"outcome {outcome.id} spans"
                )
            _require_subset(referenced_states, state_ids, f"action {action.id} state refs")
            if set(action.reads) != expression_reads:
                raise ValueError(
                    f"action {action.id} reads must exactly equal derived dependencies "
                    f"(declared={sorted(action.reads)}, derived={sorted(expression_reads)})"
                )
            if set(action.writes) != updated_states:
                raise ValueError(
                    f"action {action.id} writes must exactly equal update targets "
                    f"(declared={sorted(action.writes)}, derived={sorted(updated_states)})"
                )
            for parameter in action.parameters:
                if parameter.value_type == "account_id":
                    if not isinstance(parameter.value, str) or parameter.value not in account_ids:
                        raise ValueError(
                            f"action {action.id} parameter {parameter.name} references "
                            f"unknown account {parameter.value}"
                        )
                elif parameter.value_type == "instrument_id":
                    if (
                        not isinstance(parameter.value, str)
                        or parameter.value not in instrument_ids
                    ):
                        raise ValueError(
                            f"action {action.id} parameter {parameter.name} references "
                            f"unknown instrument {parameter.value}"
                        )
            _require_subset(action.source_span_ids, span_ids, f"action {action.id} spans")
            if _expression_type(
                action.guard,
                state_by_id=state_by_id,
                action_by_id=action_by_id,
            ) != "boolean":
                raise ValueError(f"action {action.id} guard must be boolean")
            for update in action.updates:
                value_type = _expression_type(
                    update.value,
                    state_by_id=state_by_id,
                    action_by_id=action_by_id,
                )
                target_type = state_by_id[update.target_state_id].type.kind
                if value_type != target_type:
                    raise ValueError(
                        f"action {action.id} update of {update.target_state_id} "
                        f"requires {target_type}, got {value_type}"
                    )
                if update.op in {"add", "sub"} and target_type not in {
                    "money",
                    "asset_notional",
                    "integer",
                }:
                    raise ValueError(
                        f"action {action.id} {update.op} update requires a numeric target"
                    )
            for outcome in action.outcomes:
                if _expression_type(
                    outcome.guard,
                    state_by_id=state_by_id,
                    action_by_id=action_by_id,
                ) != "boolean":
                    raise ValueError(f"outcome {outcome.id} guard must be boolean")
                for update in outcome.updates:
                    value_type = _expression_type(
                        update.value,
                        state_by_id=state_by_id,
                        action_by_id=action_by_id,
                    )
                    target_type = state_by_id[update.target_state_id].type.kind
                    if value_type != target_type:
                        raise ValueError(
                            f"outcome {outcome.id} update of {update.target_state_id} "
                            f"requires {target_type}, got {value_type}"
                        )
                    if update.op in {"add", "sub"} and target_type not in {
                        "money",
                        "asset_notional",
                        "integer",
                    }:
                        raise ValueError(
                            f"outcome {outcome.id} {update.op} update requires "
                            "a numeric target"
                        )

        for prop in properties:
            _require_subset(
                _expression_state_refs(prop.formula),
                state_ids,
                f"property {prop.id} state refs",
            )
            _require_subset(
                _expression_event_refs(prop.formula),
                action_ids,
                f"property {prop.id} event refs",
            )
            _require_subset(prop.source_span_ids, span_ids, f"property {prop.id} spans")
            if _expression_type(
                prop.formula,
                state_by_id=state_by_id,
                action_by_id=action_by_id,
            ) != "boolean":
                raise ValueError(f"property {prop.id} formula must be boolean")

        for assumption in assumptions:
            if assumption.formula is not None:
                _require_subset(
                    _expression_state_refs(assumption.formula),
                    state_ids,
                    f"assumption {assumption.id} state refs",
                )
                _require_subset(
                    _expression_event_refs(assumption.formula),
                    action_ids,
                    f"assumption {assumption.id} event refs",
                )
                if _expression_type(
                    assumption.formula,
                    state_by_id=state_by_id,
                    action_by_id=action_by_id,
                ) != "boolean":
                    raise ValueError(
                        f"assumption {assumption.id} formula must be boolean"
                    )
            _require_subset(
                assumption.action_ids, action_ids, f"assumption {assumption.id} actions"
            )
            _require_subset(
                assumption.source_span_ids, span_ids, f"assumption {assumption.id} spans"
            )

        _require_subset(control.nodes, action_ids, "control nodes")
        if set(control.nodes) != action_ids:
            missing = sorted(action_ids - set(control.nodes))
            extra = sorted(set(control.nodes) - action_ids)
            raise ValueError(
                "control must cover every action at the node layer"
                f" (missing={missing}, extra={extra})"
            )
        for edge in control.edges:
            _require_subset({edge.before, edge.after}, action_ids, "control edge")
            if edge.before == edge.after:
                raise ValueError("control edges cannot be self-referential")
        _require_acyclic(control.nodes, control.edges)
        for branch in control.branches:
            _require_subset(branch.action_ids, action_ids, f"branch {branch.id}")
        _require_unique([branch.id for branch in control.branches], "control branch")
        if control.kind == "choice":
            branch_actions = [
                action_id
                for branch in control.branches
                for action_id in branch.action_ids
            ]
            _require_unique(branch_actions, "choice branch action")
            if set(branch_actions) != action_ids:
                raise ValueError("choice branches must cover every action exactly once")
            branch_by_action = {
                action_id: branch.id
                for branch in control.branches
                for action_id in branch.action_ids
            }
            expected_choice_edges = {
                (branch.action_ids[index], branch.action_ids[index + 1])
                for branch in control.branches
                for index in range(len(branch.action_ids) - 1)
            }
            actual_choice_edges = {(edge.before, edge.after) for edge in control.edges}
            if any(
                branch_by_action[edge.before] != branch_by_action[edge.after]
                for edge in control.edges
            ):
                raise ValueError("choice control edges cannot cross branches")
            if actual_choice_edges != expected_choice_edges:
                raise ValueError(
                    "choice control edges must connect adjacent actions within each branch"
                )
        if control.kind == "sequence":
            expected_edges = {
                (control.nodes[index], control.nodes[index + 1])
                for index in range(len(control.nodes) - 1)
            }
            actual_edges = {(edge.before, edge.after) for edge in control.edges}
            if actual_edges != expected_edges:
                raise ValueError(
                    "sequence control edges must connect adjacent nodes in order"
                )

        known_block_ids = (
            state_ids
            | action_ids
            | outcome_ids
            | property_ids
            | assumption_ids
            | unresolved_ids
        )
        for item in unresolved:
            _require_subset(item.blocks, known_block_ids, f"unresolved {item.id} blocks")
            _require_subset(item.source_span_ids, span_ids, f"unresolved {item.id} spans")

        derivable_ids = (
            {meta.id}
            | symbol_ids
            | state_ids
            | action_ids
            | outcome_ids
            | property_ids
            | assumption_ids
            | unresolved_ids
        )
        for derivation in provenance.derivations:
            if derivation.node_id not in derivable_ids:
                raise ValueError(
                    f"derivation references unknown node {derivation.node_id}"
                )
            _require_subset(
                derivation.source_span_ids,
                span_ids,
                f"derivation {derivation.node_id} spans",
            )

        legacy_count = compatibility.plan.action_count()
        if legacy_count != len(compatibility.id_map):
            raise ValueError("legacy compatibility id_map must cover every legacy action")
        _require_unique(
            [item.legacy_path for item in compatibility.id_map],
            "legacy compatibility path",
        )
        _require_unique(
            [item.fsir_action_id for item in compatibility.id_map],
            "legacy compatibility FSIR action",
        )
        _require_subset(
            {item.fsir_action_id for item in compatibility.id_map},
            action_ids,
            "legacy compatibility action IDs",
        )
        canonical_paths = [path for path, _, _ in _flatten_legacy(compatibility.plan)]
        if [item.legacy_path for item in compatibility.id_map] != canonical_paths:
            raise ValueError(
                "legacy compatibility paths must be canonical and ordered like the payload"
            )
        _validate_legacy_semantic_correspondence(
            compatibility,
            actions=action_by_id,
            state=state_by_id,
            symbols=symbols,
        )
        for (_, legacy_action, _), mapping in zip(
            _flatten_legacy(compatibility.plan),
            compatibility.id_map,
        ):
            if legacy_action.action == "swap" and not any(
                item.kind == "missing_semantics"
                and item.severity == "blocking"
                and mapping.fsir_action_id in item.blocks
                for item in unresolved
            ):
                raise ValueError(
                    f"swap action {mapping.fsir_action_id} requires a blocking "
                    "missing_semantics item"
                )

        if bounds.max_actions != len(actions):
            raise ValueError(
                f"max_actions must equal action count {len(actions)}, "
                f"got {bounds.max_actions}"
            )
        required_steps = (
            max((len(branch.action_ids) for branch in control.branches), default=0)
            if control.kind == "choice"
            else len(actions)
        )
        if bounds.max_steps != required_steps:
            raise ValueError(
                f"max_steps must equal control depth {required_steps}, "
                f"got {bounds.max_steps}"
            )

        blocking = [item for item in unresolved if item.severity == "blocking"]
        if control.kind == "ambiguous" and not any(
            item.kind == "ambiguous_order" and item.severity == "blocking"
            for item in unresolved
        ):
            raise ValueError(
                "ambiguous control requires a blocking ambiguous_order unresolved item"
            )
        if meta.intent == "no_action":
            if actions or legacy_count or blocking:
                raise ValueError(
                    "no_action requires no FSIR/legacy actions and no blocking unresolved items"
                )
        elif meta.intent == "underspecified_action":
            if not blocking:
                raise ValueError(
                    "underspecified_action requires at least one blocking unresolved item"
                )
        elif meta.intent == "action_plan" and not actions:
            raise ValueError("action_plan requires at least one action")
        return values


def fsir_json_schema() -> dict[str, Any]:
    """Return the generated JSON Schema for the closed FSIR document."""

    return _model_schema(FsirDocument)


def dump_fsir(document: FsirDocument) -> dict[str, Any]:
    return _dump_model(document, by_alias=True, exclude_none=True)


def dump_legacy(plan: LegacyPlan) -> dict[str, Any]:
    return _dump_model(plan, by_alias=True, exclude_none=True)


def fsir_to_legacy(document: FsirDocument) -> dict[str, Any]:
    """Losslessly recover the compatibility payload stored in FSIR."""

    return dump_legacy(document.compatibility.plan)


def legacy_to_fsir(
    raw_plan: dict[str, Any],
    *,
    source_text: str,
    case_id: str,
    policy: dict[str, Any],
    intent: IntentClassification | None = None,
    unresolved: list[UnresolvedItem] | None = None,
    created_by: ToolIdentity | None = None,
) -> FsirDocument:
    """Deterministically lift the legacy action/choice DTO into FSIR v0.1."""

    legacy = LegacyPlan(**raw_plan)
    requested_unresolved = list(unresolved or [])
    action_count = legacy.action_count()
    if intent is None:
        intent = "action_plan" if action_count else "no_action"

    safe_case_id = _slug(case_id)
    source_id = f"source.{safe_case_id}"
    span_id = f"span.{safe_case_id}.text"
    span = SourceSpan(
        id=span_id,
        source_id=source_id,
        text=source_text,
        start=0,
        end=len(source_text),
        origin="stated",
    )
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()

    actors = [
        ActorSymbol(
            id="actor.user",
            role="user",
            label="User",
            source_span_ids=[span_id],
        ),
        ActorSymbol(
            id="service.transfer",
            role="external_service",
            label="Transfer service",
            source_span_ids=[span_id],
        ),
        ActorSymbol(
            id="service.brokerage",
            role="external_service",
            label="Brokerage service",
            source_span_ids=[span_id],
        ),
    ]

    policy_balances = {
        str(name): int(value)
        for name, value in dict(policy.get("account_balances", {})).items()
    }
    flattened = _flatten_legacy(legacy)
    if action_count and not policy_balances:
        raise ValueError("action plans require at least one configured account balance")
    if action_count and not policy.get("allowed_destination_accounts"):
        raise ValueError("action plans require at least one allowed destination account")
    budget = int(policy.get("budget", 0))
    money_values = sorted(
        {0, budget, *policy_balances.values(), *(item.amount for _, item, _ in flattened)}
    )
    money_bound_id = f"bound.{safe_case_id}.money"
    account_names = set(policy_balances)
    account_names.update(
        str(name) for name in policy.get("allowed_destination_accounts", [])
    )
    for _, action, _ in flattened:
        account_names.add(action.source)
        account_names.add(action.destination)

    account_id_by_name = {
        name: f"account.{_slug(name)}" for name in sorted(account_names)
    }
    accounts = [
        AccountSymbol(
            id=account_id_by_name[name],
            label=name,
            currency="USD",
            source_span_ids=[span_id],
        )
        for name in sorted(account_names)
    ]
    state: list[StateVariable] = []
    state_id_by_account: dict[str, str] = {}
    for name in sorted(account_names):
        state_id = f"state.cash.{_slug(name)}"
        state_id_by_account[name] = state_id
        initial = policy_balances.get(name)
        state.append(
            StateVariable(
                id=state_id,
                symbol_id=account_id_by_name[name],
                type=StateType(kind="money", currency="USD"),
                initial=initial,
                initial_domain_bound_id=money_bound_id if initial is None else None,
                source_span_ids=[span_id],
            )
        )
        if initial is None:
            requested_unresolved.append(
                UnresolvedItem(
                    id=f"unresolved.{safe_case_id}.initial.{_slug(name)}",
                    kind="missing_value",
                    severity="warning",
                    blocks=[],
                    question=(
                        f"What is the initial cash balance for '{name}'? Until resolved, "
                        f"the model uses bounded nondeterminism from {money_bound_id}."
                    ),
                    source_span_ids=[span_id],
                )
            )

    instrument = _infer_instrument(source_text)
    needs_asset_position = any(
        action.action.lower() in {"buy", "sell", "swap"}
        for _, action, _ in flattened
    )
    instruments: list[InstrumentSymbol] = []
    positions: list[AssetPositionSymbol] = []
    position_state_by_account: dict[str, str] = {}
    if needs_asset_position:
        instrument_name = instrument or "unspecified"
        instrument_id = f"instrument.{_slug(instrument_name)}"
        instruments.append(
            InstrumentSymbol(
                id=instrument_id,
                label=instrument_name,
                source_span_ids=[span_id],
            )
        )
        for _, action, _ in flattened:
            if action.action.lower() not in {"buy", "sell", "swap"}:
                continue
            account_name = action.destination if action.action.lower() == "buy" else action.source
            position_id = f"position.{_slug(account_name)}.{_slug(instrument_name)}"
            if account_name in position_state_by_account:
                continue
            positions.append(
                AssetPositionSymbol(
                    id=position_id,
                    account_id=account_id_by_name[account_name],
                    instrument_id=instrument_id,
                    unit="USD_notional",
                    source_span_ids=[span_id],
                )
            )
            position_state_id = (
                f"state.position.{_slug(account_name)}.{_slug(instrument_name)}"
            )
            position_state_by_account[account_name] = position_state_id
            state.append(
                StateVariable(
                    id=position_state_id,
                    symbol_id=position_id,
                    type=StateType(
                        kind="asset_notional",
                        currency="USD",
                        instrument_id=instrument_id,
                    ),
                    initial=0,
                    source_span_ids=[span_id],
                )
            )
        if instrument is None:
            requested_unresolved.append(
                UnresolvedItem(
                    id=f"unresolved.{safe_case_id}.instrument",
                    kind="missing_value",
                    severity="warning",
                    blocks=[],
                    question="Which instrument or holding does the trade affect?",
                    source_span_ids=[span_id],
                )
            )

    actions: list[FsirAction] = []
    id_map: list[LegacyIdMap] = []
    branch_ids: dict[str, list[str]] = {}
    derivations: list[Derivation] = []
    for ordinal, (legacy_path, action, branch_name) in enumerate(flattened, start=1):
        action_id = f"action.{safe_case_id}.{ordinal}"
        kind = action.action.lower()
        amount_expr = _literal(action.amount, "money", "USD")
        asset_amount_expr = _literal(
            action.amount, "asset_notional", "USD_notional"
        )
        true_expr = _literal(True, "boolean")
        updates: list[StateUpdate] = []
        reads: set[str] = set()
        writes: set[str] = set()
        source_state = state_id_by_account[action.source]
        destination_state = state_id_by_account[action.destination]

        if kind in {"buy", "swap", "transfer", "withdraw"}:
            updates.append(StateUpdate(op="sub", target_state_id=source_state, value=amount_expr))
            reads.add(source_state)
            writes.add(source_state)

        if kind == "buy":
            position_state = position_state_by_account[action.destination]
            updates.append(
                StateUpdate(
                    op="add",
                    target_state_id=position_state,
                    value=asset_amount_expr,
                )
            )
            reads.add(position_state)
            writes.add(position_state)
        elif kind == "sell":
            position_state = position_state_by_account[action.source]
            updates.append(
                StateUpdate(
                    op="sub",
                    target_state_id=position_state,
                    value=asset_amount_expr,
                )
            )
            updates.append(
                StateUpdate(op="add", target_state_id=destination_state, value=amount_expr)
            )
            reads.update({position_state, destination_state})
            writes.update({position_state, destination_state})
        elif kind == "swap":
            position_state = position_state_by_account[action.source]
            updates.append(
                StateUpdate(
                    op="add",
                    target_state_id=position_state,
                    value=asset_amount_expr,
                )
            )
            reads.add(position_state)
            writes.add(position_state)
            requested_unresolved.append(
                UnresolvedItem(
                    id=f"unresolved.{safe_case_id}.swap.{ordinal}",
                    kind="missing_semantics",
                    severity="blocking",
                    blocks=[action_id],
                    question="Which source and destination instruments does this swap affect?",
                    source_span_ids=[span_id],
                )
            )
        elif kind in {"deposit", "transfer", "withdraw"}:
            updates.append(
                StateUpdate(op="add", target_state_id=destination_state, value=amount_expr)
            )
            reads.add(destination_state)
            writes.add(destination_state)

        actor_id = "service.brokerage" if kind in {"buy", "sell", "swap"} else "service.transfer"
        fsir_action = FsirAction(
            id=action_id,
            intent_id=f"intent.{safe_case_id}.{ordinal}",
            kind="legacy_atomic",
            actor_id=actor_id,
            parameters=[
                ActionParameter(
                    name="kind",
                    value=kind,
                    value_type="string",
                ),
                ActionParameter(
                    name="amount",
                    value=action.amount,
                    value_type="money",
                    unit="USD",
                ),
                ActionParameter(
                    name="source",
                    value=account_id_by_name[action.source],
                    value_type="account_id",
                ),
                ActionParameter(
                    name="destination",
                    value=account_id_by_name[action.destination],
                    value_type="account_id",
                ),
            ],
            guard=true_expr,
            updates=updates,
            reads=sorted(reads),
            writes=sorted(writes),
            atomicity_group=f"atomic.{safe_case_id}.{ordinal}",
            source_span_ids=[span_id],
        )
        actions.append(fsir_action)
        id_map.append(LegacyIdMap(legacy_path=legacy_path, fsir_action_id=action_id))
        derivations.append(
            Derivation(
                node_id=action_id,
                method="deterministic_adapter",
                source_span_ids=[span_id],
            )
        )
        if branch_name:
            branch_ids.setdefault(branch_name, []).append(action_id)

    action_ids = [action.id for action in actions]
    if legacy.choices is not None:
        branches = [
            ControlBranch(
                id=f"branch.{safe_case_id}.{index}",
                name=choice.name,
                action_ids=branch_ids.get(choice.name, []),
            )
            for index, choice in enumerate(legacy.choices, start=1)
        ]
        choice_edges = [
            ControlEdge(before=branch_action_ids[index], after=branch_action_ids[index + 1])
            for branch_action_ids in branch_ids.values()
            for index in range(len(branch_action_ids) - 1)
        ]
        control = Control(
            kind="choice",
            nodes=action_ids,
            edges=choice_edges,
            branches=branches,
        )
    elif action_ids:
        edges = [
            ControlEdge(before=action_ids[index], after=action_ids[index + 1])
            for index in range(len(action_ids) - 1)
        ]
        control = Control(kind="sequence", nodes=action_ids, edges=edges)
    else:
        control = Control(kind="none")

    cash_state_ids = [
        variable.id for variable in state if variable.type.kind == "money"
    ]
    no_negative_terms = [
        Expression(
            op="gte",
            left=Expression(op="state_ref", state_id=state_id),
            right=_literal(0, "money", "USD"),
        )
        for state_id in cash_state_ids
    ]
    properties = [
        Property(
            id=f"property.{safe_case_id}.type_ok",
            kind="invariant",
            formula=Expression(op="well_typed_state"),
            severity="error",
            source_span_ids=[span_id],
        ),
    ]
    if no_negative_terms:
        no_negative_formula = (
            no_negative_terms[0]
            if len(no_negative_terms) == 1
            else Expression(op="and", args=no_negative_terms)
        )
        properties.append(
            Property(
                id=f"property.{safe_case_id}.no_negative_cash",
                kind="invariant",
                formula=no_negative_formula,
                severity="error",
                finding_code="negative_source_balance",
                source_span_ids=[span_id],
            )
        )

    policy_groups = (
        [branch.action_ids for branch in control.branches]
        if control.kind == "choice"
        else [action_ids]
    )
    def parameter_ref(action_id: str, name: str) -> Expression:
        return Expression(
            op="action_parameter_ref",
            action_id=action_id,
            parameter_name=name,
        )

    allowed_action_types = sorted(
        str(item).lower()
        for item in policy.get(
            "allowed_action_types",
            ["buy", "sell", "swap", "deposit", "transfer", "withdraw"],
        )
    )
    if allowed_action_types:
        properties.append(
            Property(
                id=f"property.{safe_case_id}.allowed_action_kinds",
                kind="action_constraint",
                formula=_fold_boolean(
                    "and",
                    [
                        Expression(
                            op="in",
                            left=parameter_ref(action.id, "kind"),
                            right=Expression(
                                op="set_literal",
                                values=allowed_action_types,
                                value_type="string",
                            ),
                        )
                        for action in actions
                    ],
                ),
                severity="error",
                finding_code="disallowed_action_kind",
                source_span_ids=[span_id],
            )
        )

    properties.append(
        Property(
            id=f"property.{safe_case_id}.positive_amounts",
            kind="action_constraint",
            formula=_fold_boolean(
                "and",
                [
                    Expression(
                        op="gt",
                        left=parameter_ref(action.id, "amount"),
                        right=_literal(0, "money", "USD"),
                    )
                    for action in actions
                ],
            ),
            severity="error",
            finding_code="non_positive_amount",
            source_span_ids=[span_id],
        )
    )

    max_individual = int(policy.get("max_individual_action_amount", budget))
    properties.append(
        Property(
            id=f"property.{safe_case_id}.individual_action_limit",
            kind="action_constraint",
            formula=_fold_boolean(
                "and",
                [
                    Expression(
                        op="lte",
                        left=parameter_ref(action.id, "amount"),
                        right=_literal(max_individual, "money", "USD"),
                    )
                    for action in actions
                ],
            ),
            severity="error",
            finding_code="individual_action_limit_exceeded",
            source_span_ids=[span_id],
        )
    )

    allowed_destinations = sorted(
        account_id_by_name[str(name)]
        for name in policy.get("allowed_destination_accounts", [])
    )
    if allowed_destinations:
        properties.append(
            Property(
                id=f"property.{safe_case_id}.allowed_destinations",
                kind="action_constraint",
                formula=_fold_boolean(
                    "and",
                    [
                        Expression(
                            op="in",
                            left=parameter_ref(action.id, "destination"),
                            right=Expression(
                                op="set_literal",
                                values=allowed_destinations,
                                value_type="account_id",
                            ),
                        )
                        for action in actions
                    ],
                ),
                severity="error",
                finding_code="disallowed_destination",
                source_span_ids=[span_id],
            )
        )

    debit_action_ids = {
        action_id
        for action_id, (_, legacy_action, _) in zip(action_ids, flattened)
        if legacy_action.action in {"buy", "swap", "transfer", "withdraw"}
    }
    configured_sources = sorted(
        account_id_by_name[name] for name in policy_balances
    )
    if configured_sources:
        properties.append(
            Property(
                id=f"property.{safe_case_id}.known_sources",
                kind="action_constraint",
                formula=_fold_boolean(
                    "and",
                    [
                        Expression(
                            op="in",
                            left=parameter_ref(action_id, "source"),
                            right=Expression(
                                op="set_literal",
                                values=configured_sources,
                                value_type="account_id",
                            ),
                        )
                        for action_id in action_ids
                        if action_id in debit_action_ids
                    ],
                ),
                severity="error",
                finding_code="unknown_source_account",
                source_span_ids=[span_id],
            )
        )

    budget_formulas = []
    for group in policy_groups:
        debit_terms = [
            parameter_ref(action_id, "amount")
            for action_id in group
            if action_id in debit_action_ids
        ]
        budget_formulas.append(
            Expression(
                op="lte",
                left=_fold_numeric_add(debit_terms, "money"),
                right=_literal(budget, "money", "USD"),
            )
        )
    properties.append(
        Property(
            id=f"property.{safe_case_id}.gross_debit_budget",
            kind="action_constraint",
            formula=_fold_boolean("and", budget_formulas),
            severity="error",
            finding_code="budget_exceeded",
            source_span_ids=[span_id],
        )
    )
    if not actions:
        properties = [
            property_item
            for property_item in properties
            if property_item.finding_code is None
        ]

    document = FsirDocument(
        meta=FsirMeta(
            id=f"fsir.{safe_case_id}",
            source_document_sha256=source_hash,
            domain_profile="finance.safety",
            intent=intent,
            currency="USD",
            budget_semantics="gross_debit",
            created_by=created_by
            or ToolIdentity(name="tla-finance-legacy-adapter", version="fsir-0.1"),
        ),
        symbols=SymbolTable(
            actors=actors,
            accounts=accounts,
            instruments=instruments,
            asset_positions=positions,
        ),
        state=state,
        actions=actions,
        control=control,
        properties=properties,
        assumptions=[],
        bounds=Bounds(
            max_actions=action_count,
            max_steps=(
                max((len(branch.action_ids) for branch in control.branches), default=0)
                if control.kind == "choice"
                else action_count
            ),
            max_retries=0,
            time_horizon=0,
            domains=[
                DomainBound(
                    id=money_bound_id,
                    kind="integer_set",
                    values=money_values,
                )
            ],
        ),
        unresolved=_deduplicate_unresolved(requested_unresolved),
        provenance=Provenance(
            sources=[source_id],
            spans=[span],
            derivations=derivations,
        ),
        compatibility=LegacyCompatibility(plan=legacy, id_map=id_map),
    )
    return document


def _literal(
    value: Scalar,
    value_type: ValueType,
    unit: Literal["USD", "USD_notional"] | None = None,
) -> Expression:
    return Expression(op="literal", value=value, value_type=value_type, unit=unit)


def _flatten_legacy(
    plan: LegacyPlan,
) -> list[tuple[str, LegacyAction, str | None]]:
    if plan.actions is not None:
        return [
            (f"actions[{index}]", action, action.choice)
            for index, action in enumerate(plan.actions)
        ]
    flattened: list[tuple[str, LegacyAction, str | None]] = []
    for choice_index, choice in enumerate(plan.choices or []):
        for action_index, action in enumerate(choice.actions):
            flattened.append(
                (
                    f"choices[{choice_index}].actions[{action_index}]",
                    action,
                    choice.name,
                )
            )
    return flattened


def _validate_legacy_semantic_correspondence(
    compatibility: LegacyCompatibility,
    *,
    actions: dict[str, FsirAction],
    state: dict[str, StateVariable],
    symbols: SymbolTable,
) -> None:
    """Bind each compatibility entry to the canonical FSIR action semantics."""

    account_by_label: dict[str, str] = {}
    for account in symbols.accounts:
        if account.label in account_by_label:
            raise ValueError(
                f"legacy compatibility requires unique account label {account.label}"
            )
        account_by_label[account.label] = account.id
    cash_state_by_account = {
        variable.symbol_id: variable.id
        for variable in state.values()
        if variable.type.kind == "money" and variable.symbol_id is not None
    }
    position_symbol_by_id = {
        position.id: position for position in symbols.asset_positions
    }
    position_states_by_account: dict[str, list[str]] = {}
    for variable in state.values():
        if variable.type.kind != "asset_notional" or variable.symbol_id is None:
            continue
        position = position_symbol_by_id.get(variable.symbol_id)
        if position is not None:
            position_states_by_account.setdefault(position.account_id, []).append(
                variable.id
            )

    flattened = _flatten_legacy(compatibility.plan)
    for (_, legacy, _), mapping in zip(flattened, compatibility.id_map):
        action = actions[mapping.fsir_action_id]
        if action.kind != "legacy_atomic":
            raise ValueError(
                f"legacy mapping {mapping.legacy_path} must target legacy_atomic action"
            )
        expected_actor = (
            "service.brokerage"
            if legacy.action in {"buy", "sell", "swap"}
            else "service.transfer"
        )
        if action.actor_id != expected_actor:
            raise ValueError(
                f"FSIR action {action.id} actor drifts from {mapping.legacy_path}"
            )
        if not (
            action.guard.op == "literal"
            and action.guard.value is True
            and action.guard.value_type == "boolean"
        ):
            raise ValueError(
                f"FSIR action {action.id} guard drifts from {mapping.legacy_path}"
            )
        source_account_id = account_by_label.get(legacy.source)
        destination_account_id = account_by_label.get(legacy.destination)
        if source_account_id is None or destination_account_id is None:
            raise ValueError(
                f"legacy mapping {mapping.legacy_path} references an unknown account label"
            )
        expected_parameters: dict[str, tuple[Scalar, str, str | None]] = {
            "kind": (legacy.action, "string", None),
            "amount": (legacy.amount, "money", "USD"),
            "source": (source_account_id, "account_id", None),
            "destination": (destination_account_id, "account_id", None),
        }
        actual_parameters = {
            parameter.name: (
                parameter.value,
                parameter.value_type,
                parameter.unit,
            )
            for parameter in action.parameters
        }
        if actual_parameters != expected_parameters:
            raise ValueError(
                f"FSIR action {action.id} parameters drift from "
                f"{mapping.legacy_path}"
            )

        source_cash = cash_state_by_account.get(source_account_id)
        destination_cash = cash_state_by_account.get(destination_account_id)
        if source_cash is None or destination_cash is None:
            raise ValueError(
                f"FSIR action {action.id} lacks cash state for its legacy accounts"
            )
        expected_updates: list[tuple[str, str, int, str, str]] = []
        if legacy.action in {"buy", "swap", "transfer", "withdraw"}:
            expected_updates.append(
                ("sub", source_cash, legacy.amount, "money", "USD")
            )
        if legacy.action == "buy":
            positions = position_states_by_account.get(destination_account_id, [])
            if len(positions) != 1:
                raise ValueError(
                    f"FSIR buy action {action.id} requires exactly one destination position"
                )
            expected_updates.append(
                (
                    "add",
                    positions[0],
                    legacy.amount,
                    "asset_notional",
                    "USD_notional",
                )
            )
        elif legacy.action == "sell":
            positions = position_states_by_account.get(source_account_id, [])
            if len(positions) != 1:
                raise ValueError(
                    f"FSIR sell action {action.id} requires exactly one source position"
                )
            expected_updates.extend(
                [
                    (
                        "sub",
                        positions[0],
                        legacy.amount,
                        "asset_notional",
                        "USD_notional",
                    ),
                    ("add", destination_cash, legacy.amount, "money", "USD"),
                ]
            )
        elif legacy.action == "swap":
            positions = position_states_by_account.get(source_account_id, [])
            if len(positions) != 1:
                raise ValueError(
                    f"FSIR swap action {action.id} requires exactly one source position"
                )
            expected_updates.append(
                (
                    "add",
                    positions[0],
                    legacy.amount,
                    "asset_notional",
                    "USD_notional",
                )
            )
        elif legacy.action in {"deposit", "transfer", "withdraw"}:
            expected_updates.append(
                ("add", destination_cash, legacy.amount, "money", "USD")
            )

        actual_updates: list[tuple[str, str, int, str, str]] = []
        for update in action.updates:
            expression = update.value
            if (
                expression.op != "literal"
                or isinstance(expression.value, bool)
                or not isinstance(expression.value, int)
                or expression.value_type not in {"money", "asset_notional"}
                or expression.unit is None
            ):
                raise ValueError(
                    f"legacy FSIR action {action.id} must use typed literal effects"
                )
            actual_updates.append(
                (
                    update.op,
                    update.target_state_id,
                    expression.value,
                    expression.value_type,
                    expression.unit,
                )
            )
        if actual_updates != expected_updates:
            raise ValueError(
                f"FSIR action {action.id} effects drift from {mapping.legacy_path}"
            )


def _infer_instrument(text: str) -> str | None:
    candidates = re.findall(r"\b[A-Z]{2,6}\b", text)
    ignored = {"USD", "FSIR", "TLA", "JSON", "API"}
    for candidate in candidates:
        if candidate not in ignored:
            return candidate
    return None


def _expression_state_refs(expression: Expression) -> set[str]:
    refs = {expression.state_id} if expression.state_id else set()
    for child in expression.args:
        refs |= _expression_state_refs(child)
    if expression.left is not None:
        refs |= _expression_state_refs(expression.left)
    if expression.right is not None:
        refs |= _expression_state_refs(expression.right)
    return refs


def _expression_event_refs(expression: Expression) -> set[str]:
    refs = set(expression.event_ids)
    if expression.action_id is not None:
        refs.add(expression.action_id)
    for child in expression.args:
        refs |= _expression_event_refs(child)
    if expression.left is not None:
        refs |= _expression_event_refs(expression.left)
    if expression.right is not None:
        refs |= _expression_event_refs(expression.right)
    return refs


def _require_unique(values: list[str], label: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"duplicate {label} IDs: {', '.join(duplicates)}")


def _require_subset(values: set[str] | list[str], allowed: set[str], label: str) -> None:
    missing = sorted(set(values) - allowed)
    if missing:
        raise ValueError(f"{label} reference unknown IDs: {', '.join(missing)}")


def _require_acyclic(nodes: list[str], edges: list[ControlEdge]) -> None:
    successors: dict[str, set[str]] = {node: set() for node in nodes}
    indegree: dict[str, int] = {node: 0 for node in nodes}
    for edge in edges:
        if edge.after not in successors[edge.before]:
            successors[edge.before].add(edge.after)
            indegree[edge.after] += 1
    ready = [node for node in nodes if indegree[node] == 0]
    visited = 0
    while ready:
        node = ready.pop()
        visited += 1
        for successor in successors[node]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
    if visited != len(nodes):
        raise ValueError("control edges must form an acyclic relation")


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return slug or "unnamed"


def _deduplicate_unresolved(items: list[UnresolvedItem]) -> list[UnresolvedItem]:
    by_id: dict[str, UnresolvedItem] = {}
    for item in items:
        by_id[item.id] = item
    return [by_id[item_id] for item_id in sorted(by_id)]


__all__ = [
    "ActionOutcome",
    "ActionParameter",
    "ActorSymbol",
    "Assumption",
    "Bounds",
    "Control",
    "ControlBranch",
    "ControlEdge",
    "DomainBound",
    "Expression",
    "FsirAction",
    "FsirDocument",
    "FsirMeta",
    "InstrumentSymbol",
    "LegacyAction",
    "LegacyChoice",
    "LegacyCompatibility",
    "LegacyPlan",
    "Property",
    "Provenance",
    "SourceSpan",
    "StateType",
    "StateUpdate",
    "StateVariable",
    "SymbolTable",
    "ToolIdentity",
    "UnresolvedItem",
    "dump_fsir",
    "dump_legacy",
    "fsir_json_schema",
    "fsir_to_legacy",
    "legacy_to_fsir",
]
