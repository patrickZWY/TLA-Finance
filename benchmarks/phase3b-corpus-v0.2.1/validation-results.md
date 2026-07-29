# Phase 3B v0.2.1 Final Validation

Date: 2026-07-29

## Closed-schema mode

Command:

```bash
python3 validate_corpus.py
```

Result:

```text
valid: 30 cases; schema=passed; levels={'L0': 8, 'L1': 8, 'L2': 8, 'L3': 6}; verdicts={'pass': 12, 'fail': 10, 'needs_clarification': 7, 'inconclusive': 1}; lowering={'unsupported': 20, 'reject_blocking': 8, 'lower': 2}; mutants=32
```

## Frozen-environment mode

Command:

```bash
python3 -S validate_corpus.py
```

Result:

```text
valid: 30 cases; schema=skipped (jsonschema unavailable; semantic gates still ran); levels={'L0': 8, 'L1': 8, 'L2': 8, 'L3': 6}; verdicts={'pass': 12, 'fail': 10, 'needs_clarification': 7, 'inconclusive': 1}; lowering={'unsupported': 20, 'reject_blocking': 8, 'lower': 2}; mutants=32
```

## Focused validator mutations

All four were rejected at the intended gate:

- missing semantic action-map key;
- empty semantic property map;
- altered model digest;
- altered raw TLC-output digest.

See `validator-mutation-results.json`.

## Mutant scope

- Corpus semantic mutant oracles: 32/32 defined, 0/32 executed because no
  corpus→exact-FSIR materializer exists.
- Approved `d45efd0` backend integrity/classification mutants: 8/8 executed and
  rejected in `backend-evidence.json`.

## Evidence anchor

- Lowering commit:
  `d45efd09ffe5c77b89fcad1954d7959e54b7b8f3`.
- Pinned TLC jar SHA-256:
  `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`.
- Ordered fixture: `passed`.
- Concurrent fixture: `property_violation` on
  `property.safe_transfer_then_buy_order_sensitive.no_negative_cash`, normalized
  events `event.buy.submit → event.buy.execute`.
- v0.2 case/oracle fingerprint excluding only refreshed commit metadata:
  `d5745e96cab0c94a0388ed9e5d39c6a9a7308a54e2c931a0d333e76d274fb793`.
