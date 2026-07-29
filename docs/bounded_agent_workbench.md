# Bounded-agent workbench

The workbench now has two deliberately separate trust paths.

`POST /api/semantic-check` remains the legacy prose-to-normalized-action
endpoint. Its UI projection is labeled heuristic and grants no execution
authority.

`POST /api/bounded-workbench` is the closed FSIR path. Its request is an
exclusive tagged union:

```json
{"source":"corpus_case","case_id":"core.18"}
```

or:

```json
{
  "source": "canonical_fsir",
  "fsir": {"meta": "...complete closed FSIR v0.1 document..."},
  "run_model_checker": false
}
```

The bounded endpoint never accepts prose as FSIR and never falls back to model
extraction. It validates `FsirDocument`, lowers only the approved bounded
subset, verifies deterministic artifacts, preserves exact FSIR/source-map IDs,
and keeps `passed`, `property_violation`, `temporal_violation`, and
`infrastructure_failure` distinct. Raw TLC output, commands, and local paths
remain server-side.

## Frozen evidence

`fixtures/phase3b-corpus-v0.2.1` contains the approved corpus plus the ordered
and concurrent standalone canonical fixtures. Runtime loading checks the corpus
hash, closed FSIR validation, canonical FSIR/model/config/source-map hashes,
TLC classification, strict normalized trace, and execution-evidence manifest.
The approved lowering anchor is
`d45efd09ffe5c77b89fcad1954d7959e54b7b8f3`.

Before any fixture is labeled or returned, the hash-pinned
`evidence-identities.json` contract independently binds the requested case and
fixture IDs to the exact artifact directory, module, FSIR ID and canonical
hash, source/policy/model/config/source-map hashes, classification, return
code, violated property and normalized event IDs, lowering/execution-manifest
hashes, and complete filename-to-hash inventory. Bundle swaps or renames,
coherent report/manifest substitutions, added or deleted artifacts, and
identity drift fail closed rather than returning fresh trusted evidence. The
response fixture label is taken only from that verified identity.

- `core.17` is the canonical ordered passing run.
- `core.18` is the canonical concurrent property violation.
- `core.06` is an intentional zero-action result. It is not extraction failure
  and offers no execution approval.
- other `unsupported` or `reject_blocking` corpus cases return fail-closed
  projections without claiming artifacts.

## Core 30 correction

The eight authored core.30 snapshots are available for contract inspection,
but they are not exact source-linked verification evidence. The projection and
packaged lifecycle fixtures differ in source document/spans, FSIR ID, action
granularity/IDs, property contract, and bounds. The API
therefore reports:

```text
evidence_applicability = reference_only
contract_match = false
approval_eligible = false
```

Core.30-derived FSIR/model/config/source-map hashes, classification, property
verdict, freshness, and approval scope remain `null`. The separately identified
core.17/core.18 fixture evidence stays inspectable and is labeled fixture-only.
The one reference-only property correspondence is
`property.no_negative_cash` to
`property.safe_transfer_then_buy_order_sensitive.no_negative_cash`;
`property.no_rejected_action` is unsupported by the fixture. The UI shows three
business nodes as projection context and six lifecycle events as the fixture
TLC step bound. It never combines those contracts into a verdict.

The accepted reference-only oracle is checked in separately from corpus
evidence at `contracts/phase4b-core30-reference-audit-v0.1/`. Its
`reference-links.json` and stage-4 decision are hash-pinned to the independently
validated audit archive (`0a3088c0…6ccdb`, PASS; 10/10 negative mutants
rejected). API responses expose the exact selected link and decision under
`reference_evidence`; they are explicitly marked `corpus_evidence = false`.

## State-driven controls

Every API response includes a closed Boolean envelope for:

`approve`, `edit`, `reject`, `stop`, `revise`, `rerun`, `clarify`,
`inspect_evidence`, `resume`, `new_goal`, and `verify`.

The browser validates that envelope against the local closed state matrix
before rendering it. During `verification_running`, only Stop remains
available. `stopped` exposes only Resume and New goal. A change invalidates
prior evidence, and reference-only/stale/infrastructure/unsupported states
cannot enable bounded approval. Approval also requires all canonical nodes to
be reviewed and a future expiry to be selected. This sandbox records the
bounded scope but never executes a financial action.

## Local demo

Use the existing project environment (or install `requirements.txt`), then:

```bash
SAFETY_RUN_TLC=0 python3 -m uvicorn api.index:app --host 127.0.0.1 --port 8000
```

Open:

- <http://127.0.0.1:8000/?case=core.17> — canonical ordered pass;
- <http://127.0.0.1:8000/?case=core.18> — canonical concurrent violation;
- <http://127.0.0.1:8000/?case=core.06> — intentional no-action pass;
- <http://127.0.0.1:8000/?case=core.30&stage=4> — fail-closed
  reference-only hero audit.

The original deterministic UI fixtures remain available with
`/?fixture=hero_safe`, `hero_unsafe`, or `hero_clarification`, but are visibly
labeled as fixture replay rather than canonical FSIR evidence.

To run TLC for a submitted canonical FSIR, set `TLA_TOOLS_JAR` to the approved
jar whose SHA-256 is
`936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`.
Absent or mismatched tooling returns `infrastructure_failure`; it does not
silently use another jar.

## Verification

```bash
SAFETY_RUN_TLC=0 python3 -m unittest discover -s tests -v
```

Focused checks:

```bash
python3 -m unittest tests.test_bounded_workbench tests.test_frontend_workbench -v
```

The tests cover the exclusive API union, preserved semantic-check route,
canonical hashes/IDs, strict counterexample linkage, zero-action rendering,
all corpus fail-closed dispositions, core.30 reference-only separation, closed
state controls, bundle swap/rename/substitution/inventory rejection, bounded
approval expiry, responsive markers, and accessibility labels/live regions.

## Browser retention

Goal, advice, and guardrail drafts are stored in browser `localStorage`; this
is disclosed beside the inputs. **Clear local data** removes the draft and
resets review, approval, activity, fixture, and verifier state. Frozen corpus
inputs are resolved server-side and cannot be mutated by editing the displayed
form.
