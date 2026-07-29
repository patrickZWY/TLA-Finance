# Bounded-agent workbench

The Phase 3C frontend turns the existing semantic safety check into an
inspectable agent loop without changing the backend contract.

## Live path

The primary action still sends:

```text
POST /api/semantic-check
```

with the existing `user_message`, `finance_advice`, `policy`, and
`run_model_checker` fields. The UI projects returned normalized actions into a
reviewable FSIR view; this projection is explicitly labeled as UI-generated
until the backend exposes the canonical FSIR contract.

## Deterministic demo paths

Enable **Replay deterministic demo evidence** after choosing one of the three
hero scenarios, or open:

- `/?fixture=hero_safe`
- `/?fixture=hero_unsafe`
- `/?fixture=hero_clarification`

Fixture replay is visibly labeled and never impersonates a live model or TLC
run. The fixture contract lives in `public/workbench-demo-fixtures.json`.

The unsafe flow supports a counterexample-guided reorder:

1. replay `hero_unsafe`;
2. inspect the source-linked action nodes and earliest violating state;
3. choose **Propose safer revision**;
4. re-run the revised plan with `hero_safe` or the live endpoint;
5. approve every FSIR action;
6. record bounded approval for the displayed model version and bounds.

The sandbox records approval but never executes a trade or transfer.

## Trust and retention

The header begins in the neutral **Verifier status not checked** state. A ready
or local verifier is never inferred from page load. The badge changes only
after live endpoint evidence, deterministic fixture replay, or a request
failure, and it directs the reviewer to the bounded evidence for configuration
details.

Goal, advice, and guardrail drafts are stored in browser `localStorage`. This is
disclosed beside the input controls. **Clear local data** removes the stored
draft, restores example defaults, clears result/review/activity state, disables
fixture replay, restores the TLC preference, and returns verifier status to
unchecked.

## Explicit UI states

- `clarification_required`
- `ready_for_review`
- `verification_running`
- `violation_found`
- `verification_unavailable`
- `revision_proposed`
- `reverification_required`
- `checks_passed`
- `bounded_approval_required`
- `stopped`

Changing the goal, plan, policy, or model-checker setting invalidates prior
evidence and blocks approval until the plan is verified again.

## Regression check

```bash
python3 -m unittest tests.test_frontend_workbench
```

The checks cover the preserved endpoint contract, UI-state matrix, agent/review
controls, bounded verdict metadata, fixture outcomes, shortest counterexample,
and baseline responsive/accessibility markers.

## Current boundary

The current endpoint returns normalized actions rather than canonical FSIR
source maps, properties, hashes, and approval metadata. Therefore:

- source spans are best-effort UI matches and are labeled as such;
- the displayed FSIR version is a run-scoped UI projection;
- approval is local UI state only;
- no backend action or execution authority is added.

These limitations keep the slice honest and allow later integration with the
typed FSIR/lowering work without coupling this branch to backend files.
