# Hero Demo: Clarify, Disprove, Revise, Re-verify, Approve

This script exercises `core.30`. It demonstrates bounded verification of a
proposed financial workflow; it does not execute a financial action and never
labels the plan globally safe.

The initial core has `lowering_expectation=reject_blocking`: no backend
artifacts exist until the ordering question is answered. After approval, stage
4 references the exact frozen partial-order fixture
`fixture.phase3a.lifecycle.concurrent`; stages 7–8 use the ordered fixture
`fixture.phase3a.lifecycle.ordered`. Every stage is replayable from its
`projection_snapshot` in `corpus.json`.

## Fixed scenario

User request:

> Move $300 from checking to brokerage and buy $300 of VTI as soon as possible.

Policy/profile: `policy.async`. Initial balances are checking $1,200,
brokerage $0, savings $200. The per-action limit is $500 and gross-debit budget
is $900. The verification bound is `max_steps=5`, `max_actions=3`,
`retry_limit=0`, `time_horizon=4`, amount domain `{0, 300, 600, 900}`.

Properties stay fixed throughout:

- `property.no_rejected_action`: no approved action reaches a rejected state.
- `property.no_negative_cash`: every cash balance remains nonnegative.

The only semantic revision permitted in the demo is to add
settlement-before-buy ordering. Amounts, destinations, properties, assumptions,
and bounds must not be weakened or silently changed.

## Script

### 1. Needs clarification

Product state: `clarification_required`.

The agent highlights the exact transfer and buy source spans and says:

> I need 1 answer before I can verify this plan. Does “as soon as possible”
> allow the buy to execute before the transfer settles, or must settlement be a
> prerequisite?

The user chooses: “They may start concurrently.”

Acceptance: no verification artifact, verdict, or approval control is shown
before this answer. The activity trace records the answer without rewriting the
source text.

### 2. Review interpretation

Product state: `ready_for_review`.

Show FSIR v0 with:

1. `action.submit-transfer`;
2. `action.settle-transfer`;
3. `action.execute-buy`;
4. concurrent control between transfer submission and buy availability;
5. `assumption.environment-interleaving`;
6. the two fixed properties and exact bounds above.

The user approves this interpretation for verification only.

Acceptance: the approved FSIR hash and source-span map are visible. Approval
does not authorize execution.

### 3. Verification in progress

Product state: `verification_running`.

Show stage-specific status: extraction complete, policy checks complete,
deterministic lowering complete, TLC running. Evidence identifies
`fsir-tla-source-map-0.1`, `fsir-tla-manifest-0.1`, the model/config hashes, and
the exact approved FSIR version.

Acceptance: a backend failure must transition to **Verification unavailable**
with a structured reason and no safety conclusion; it must not fabricate a pass.

### 4. Plan blocked

Product state: `violation_found`.

Name the first violated property and earliest bad state:

> `property.no_negative_cash` is violated when the attempted buy executes
> before the transfer settles and debits an unfunded brokerage balance.

Show the frozen fixture's shortest normalized path:

1. `event.buy.submit` with brokerage cash $0;
2. `event.buy.execute` with brokerage cash still $0;
3. the configured property is violated before settlement.

Acceptance: source-map links select `action.execute-buy` and the original buy
span. The UI offers inspect evidence, revise, or stop—not approval.

### 5. Safer revision proposed

Product state: `revision_proposed`.

The agent proposes FSIR v1 with one diff: add
`action.settle-transfer → action.execute-buy`. It explains that this blocks the
displayed counterexample. The user can approve, edit, or reject the revision.

Acceptance: v0 remains inspectable; the projection snapshot's contract hash
proves properties, assumptions, and bounds are unchanged. Deleting the violated
property or shrinking the bound must be rejected by the preservation gate.

### 6. Changes need verification

Product state: `reverification_required`.

After the user accepts the edit, invalidate the v0 evidence and require explicit
approval to verify FSIR v1.

Acceptance: the v0 model hash is recorded as stale evidence against v1. No
stale evidence may authorize v1.

### 7. No configured guardrail was violated

Product state: `checks_passed`.

Re-run the same policy and TLC checks. Show the positive normalized trace:

1. `action.submit-transfer`;
2. `action.settle-transfer`;
3. `action.execute-buy`.

Report that both named properties pass under the exact recorded assumptions and
`max_steps=5`.

Acceptance: the heading is exactly **No configured guardrail was violated**.
The v1 model hash differs from v0, the preserved-contract hash is unchanged,
and the UI does not say “safe,” imply suitability, or generalize beyond the
bound.

### 8. Ready for bounded approval

Product state: `bounded_approval_required`.

Request approval for:

- the exact FSIR v1/model hash;
- transfer $300 checking→brokerage;
- settlement as a mandatory prerequisite;
- buy at most $300 of VTI from brokerage;
- the named assumptions, bounds, and verified properties;
- a user-selected expiry before execution.

Acceptance: approve, edit, reject, and stop remain available. Any edit returns
to **Changes need verification**. Stop transitions to **Agent stopped**,
preserves the evidence trace, and performs no further tool or financial action.

## Demo pass criteria

The demo passes when all eight states occur in order, every transition is
versioned in `activity`, the counterexample replays with the expected event IDs,
the revision blocks that same trace without weakening the contract, re-
verification uses fresh hashes, and final approval is limited to the exact
actions, amounts, expiry, FSIR/model version, properties, assumptions, and
bounds shown above.
