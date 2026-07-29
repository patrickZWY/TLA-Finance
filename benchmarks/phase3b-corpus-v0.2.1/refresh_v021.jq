# Inputs:
#   --slurpfile ordered <approved ordered/input.fsir.json>
#   --slurpfile concurrent <approved concurrent/input.fsir.json>
#   --slurpfile report <approved report.json>
#
# This refreshes evidence metadata only. It deliberately does not alter source
# spans, semantic/product oracles, traces, bounds, mutants, or hero projections.

def approved_commit:
  "d45efd09ffe5c77b89fcad1954d7959e54b7b8f3";

.corpus_version = "phase3b-0.2.1"
| .backend_fixtures |= map(
    if .control_kind == "sequence" then
      .frozen_commit = approved_commit
      | .fsir_document = $ordered[0]
      | .expected_tlc_verdict = $report[0].cases.ordered.expected
      | .expected_property_ids = $report[0].cases.ordered.expected_property_ids
      | .expected_manifest = $report[0].cases.ordered.manifest
      | .execution_evidence_manifest =
          $report[0].cases.ordered.execution_evidence_manifest
      | .expected_normalized_event_ids =
          $report[0].cases.ordered.normalized_event_ids
    else
      .frozen_commit = approved_commit
      | .fsir_document = $concurrent[0]
      | .expected_tlc_verdict = $report[0].cases.concurrent.expected
      | .expected_property_ids =
          $report[0].cases.concurrent.expected_property_ids
      | .expected_manifest = $report[0].cases.concurrent.manifest
      | .execution_evidence_manifest =
          $report[0].cases.concurrent.execution_evidence_manifest
      | .expected_normalized_event_ids =
          $report[0].cases.concurrent.normalized_event_ids
    end
  )
| .cases[].lowering_oracle.frozen_commit = approved_commit
