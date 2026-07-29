def trace_event_map: {
  "trace.01.safe": ["action.transfer.1"],
  "trace.01.mutant": ["action.transfer.1"],
  "trace.02.allowed": ["action.transfer.1"],
  "trace.02.bad": ["action.transfer.1"],
  "trace.03.edge": ["action.transfer.1", "action.transfer.2"],
  "trace.03.bad": ["action.transfer.1", "action.transfer.2", "action.buy.3"],
  "trace.04.edge": ["action.transfer.1"],
  "trace.04.bad": ["action.transfer.1"],
  "trace.05.resolved": ["action.withdraw.1"],
  "trace.05.bad": ["action.withdraw.1"],
  "trace.06.empty": [],
  "trace.06.bad": [],
  "trace.07.resolved": ["action.transfer.1"],
  "trace.07.bad": [],
  "trace.08.safe": ["action.transfer.1"],
  "trace.08.bad": ["action.transfer.1"],
  "trace.09.safe": ["action.transfer.1", "action.buy.2"],
  "trace.09.bad": ["action.buy.2"],
  "trace.10.revised": ["action.transfer.2", "action.buy.1"],
  "trace.10.bad": ["action.buy.1"],
  "trace.11.safe": ["action.choice.safe.transfer", "action.choice.safe.buy"],
  "trace.11.bad": ["action.choice.bad.buy"],
  "trace.12.sequence": ["action.transfer.1", "action.buy.2"],
  "trace.12.parallel": ["action.transfer.1", "action.buy.2"],
  "trace.13.no-fee": ["action.buy.no-fee"],
  "trace.13.fee": ["action.buy.with-fee"],
  "trace.14.revised": ["action.buy.1", "action.buy.2"],
  "trace.14.bad": ["action.buy.1", "action.buy.2"],
  "trace.15.budget700": ["action.transfer.1"],
  "trace.15.budget500": ["action.transfer.1"],
  "trace.16.resolved": [],
  "trace.16.bad": [],
  "trace.17.safe": ["action.submit-transfer", "action.settle-transfer", "action.buy"],
  "trace.17.bad": ["action.submit-transfer", "action.buy"],
  "trace.18.lucky": ["action.submit-transfer", "action.settle-transfer", "action.execute-buy"],
  "trace.18.bad": ["action.submit-transfer", "action.execute-buy"],
  "trace.19.settle": ["action.submit-transfer", "action.retry-settlement"],
  "trace.19.bound": ["action.submit-transfer", "action.retry-settlement", "action.retry-settlement", "action.stop-transfer"],
  "trace.20.once": ["action.submit-tx7", "action.submit-tx7"],
  "trace.20.bad": ["action.submit-tx7", "action.submit-tx7"],
  "trace.21.edge": ["action.execute-buy"],
  "trace.21.reject": ["action.execute-buy"],
  "trace.22.available": ["action.deposit"],
  "trace.22.unavailable": [],
  "trace.23.reverse": ["action.submit", "action.reverse", "action.reverse"],
  "trace.23.bad": ["action.submit", "action.reverse", "action.reverse"],
  "trace.24.one": ["action.budget.transfer"],
  "trace.24.bad": ["action.budget.transfer", "action.invest.transfer"],
  "trace.25.settle": ["action.settle"],
  "trace.25.unfair": [],
  "trace.26.possible": ["action.settle"],
  "trace.26.stutter": [],
  "trace.27.fair": ["action.attempt.tx1", "action.attempt.tx2"],
  "trace.27.starve": ["action.attempt.tx1", "action.attempt.tx1"],
  "trace.28.timeout": ["action.tick", "action.tick", "action.tick", "action.timeout-cancel"],
  "trace.28.bad": ["action.tick", "action.tick", "action.tick", "action.tick"],
  "trace.29.cancel": ["action.cancel-buy"],
  "trace.29.bad": ["action.cancel-buy", "action.execute-buy"],
  "trace.30.revised": ["action.submit-transfer", "action.settle-transfer", "action.execute-buy"],
  "trace.30.concurrent": ["action.submit-transfer", "action.execute-buy"]
};

def agent_phase:
  if .id == "core.26" then "verification_unavailable"
  elif .agent_next_step.kind == "stop" then "stopped"
  elif .evidence.verdict == "needs_clarification" then "clarification_required"
  elif .evidence.verdict == "inconclusive" then "verification_unavailable"
  elif .evidence.verdict == "fail" then "violation_found"
  elif (.tags | index("no-action")) != null then "checks_passed"
  else "bounded_approval_required"
  end;

def verification_status:
  if .id == "core.26" then "inconclusive"
  elif .evidence.verdict == "needs_clarification" then "blocked"
  elif .evidence.verdict == "fail" then "violation_found"
  else "complete"
  end;

def property_status($verdict):
  if $verdict == "pass" then "passed"
  elif $verdict == "fail" then "violated"
  elif $verdict == "inconclusive" then "inconclusive"
  else "blocked"
  end;

.cases |= map(
  (if (.expected_fsir.properties | length) == 0
   then
     (if .id == "core.06"
      then {
        id: "property.no_financial_action",
        kind: "trace",
        formula_label: "no financial action is emitted",
        finding_code: "unexpected_financial_action",
        source_span_ids: [.source_spans[0].id]
      }
      elif .id == "core.16"
      then {
        id: "property.known_action_kind",
        kind: "action_constraint",
        formula_label: "every action kind is recognized by the closed FSIR schema",
        finding_code: "unknown_action_kind",
        source_span_ids: [.source_spans[0].id]
      }
      else {
        id: "property.no_execution_before_resolution",
        kind: "trace",
        formula_label: "no financial action executes while a blocking meaning is unresolved",
        finding_code: "execution_before_resolution",
        source_span_ids: [.source_spans[0].id]
      } end
     ) as $fallback
     | .expected_fsir.properties = [$fallback]
     | .evidence.property_ids = [$fallback.id]
   else .
   end)
  | . as $case
  | .positive_traces |= map(
      . as $trace
      | . + {expected_event_ids: trace_event_map[$trace.id]}
    )
  | .negative_traces |= map(
      . as $trace
      | . + {expected_event_ids: trace_event_map[$trace.id]}
    )
  | .lowering_oracle = {
      source_map_format: "fsir-tla-source-map-0.1",
      manifest_format: "fsir-tla-manifest-0.1",
      fsir_document_id: ("fsir." + .id),
      module_name: ("Corpus_" + (.id | sub("^core\\."; "") | gsub("\\."; "_"))),
      mapped_state_ids: .expected_fsir.state_ids,
      mapped_operator_ids: [.expected_fsir.actions[].id],
      mapped_property_ids: [.expected_fsir.properties[].id],
      mapped_branch_ids:
        (if (.expected_fsir.control == "choice" or .expected_fsir.control == "parallel")
         then ["branch." + .id + ".1"] else [] end),
      required_sha256_fields: [
        "inputs.fsir_canonical_json", "inputs.source_document",
        "inputs.policy_snapshot", "outputs.model", "outputs.config",
        "outputs.source_map", "tools.lowerer.sha256",
        "tools.fsir_contract.sha256", "tools.tlc.sha256"
      ],
      normalized_counterexample_event_ids:
        (if .evidence.shortest_counterexample.exists
         then (.negative_traces[0].expected_event_ids // [])
         else [] end)
    }
  | .product_projection = {
      case_id: .id,
      title: .title,
      user_goal: .prose,
      agent_goal: .agent_next_step.text,
      agent_phase: agent_phase,
      source_text: .prose,
      questions: [
        .expected_fsir.unresolved[] |
        {
          id: .id,
          prompt: .question,
          required: .blocking,
          source_span: ($case.source_spans[0].id)
        }
      ],
      fsir_version: ("fsir." + .id + ".v0"),
      fsir_status:
        (if .id == "core.26" then "inconclusive"
         elif .evidence.verdict == "needs_clarification" then "clarification_required"
         elif .evidence.verdict == "inconclusive" then "inconclusive"
         elif .evidence.verdict == "fail" then "verified_violation"
         else "verified" end),
      assumptions: .expected_fsir.assumption_ids,
      bounds: {
        currency: "USD",
        amount_precision: 2,
        max_actions: .bounds.max_actions,
        accounts: [.expected_fsir.symbol_ids[] | select(startswith("account."))],
        choices:
          (if .expected_fsir.control == "choice" then ["branch.1", "branch.2"]
           elif .expected_fsir.control == "unresolved" then ["ordered", "concurrent"]
           else [] end)
      },
      nodes: [
        .expected_fsir.actions[] |
        {
          id: .id,
          type: .kind,
          label: (.kind + " by " + .actor),
          fields: {
            actor: .actor,
            amount: .amount,
            from: .from,
            to: .to,
            guard: .guard,
            effects: .effects
          },
          source_spans: .source_span_ids,
          review_status:
            (if $case.evidence.verdict == "needs_clarification" then "blocked"
             else "reviewed" end)
        }
      ],
      properties: [
        .expected_fsir.properties[] |
        {
          id: .id,
          label: .formula_label,
          backend: (if .kind == "liveness" then "tlc" else "python-policy+tlc" end),
          status:
            (if $case.id == "core.26" then "inconclusive"
             else property_status($case.evidence.verdict) end)
        }
      ],
      verification: {
        status: verification_status,
        backend: (if .id == "core.26" then "model-only" else "tlc" end),
        config_hash: ("oracle:config:" + .id),
        model_hash: ("oracle:model:" + .id)
      },
      findings:
        (if .evidence.verdict == "fail" then [{
          code:
            (([.expected_fsir.properties[].finding_code | select(. != null)][0])
             // "property_violation"),
          property_id: .evidence.property_ids[0],
          severity: "error",
          message: .evidence.explanation,
          node_id: (.expected_fsir.actions[0].id // null),
          state_id: (.expected_fsir.state_ids[0] // null),
          expected: ([.expected_fsir.properties[].formula_label][0] // "configured property holds"),
          actual: "shortest bounded trace violates the configured property"
        }] else [] end),
      counterexample: {
        summary:
          (if .evidence.shortest_counterexample.exists
           then .evidence.explanation else "No counterexample is asserted." end),
        first_violating_state:
          (if .evidence.shortest_counterexample.exists
           then ("state." + .id + ".violation") else null end),
        path: [
          .evidence.shortest_counterexample.steps[] as $step |
          {
            state_id: ("state." + $case.id + "." +
              ($step | ascii_downcase | gsub("[^a-z0-9]+"; ".") | sub("^\\."; "") | sub("\\.$"; ""))),
            action_node_id: ($case.expected_fsir.actions[0].id // null),
            label: $step,
            balances: {},
            violations: $case.evidence.property_ids
          }
        ]
      },
      revision: {
        from_version: ("fsir." + .id + ".v0"),
        to_version:
          (if (.agent_next_step.kind == "revise_plan" or .id == "core.30")
           then ("fsir." + .id + ".v1") else ("fsir." + .id + ".v0") end),
        rationale:
          (if (.agent_next_step.kind == "revise_plan" or .id == "core.30")
           then .agent_next_step.text else "No revision is proposed by this oracle." end),
        diff:
          (if (.agent_next_step.kind == "revise_plan" or .id == "core.30")
           then ["preserve properties, assumptions, and bounds; change only the unsafe plan semantics"]
           else [] end)
      },
      agent_next_step: {
        label: .agent_next_step.text,
        reason: .evidence.explanation,
        requires_approval: .agent_next_step.requires_human_approval
      },
      approval_scope: {
        actions: [.expected_fsir.actions[].id],
        limits: {
          max_actions: .bounds.max_actions,
          max_steps: .bounds.max_steps,
          retry_limit: .bounds.retry_limit,
          time_horizon: .bounds.time_horizon,
          amount_domain: .bounds.amount_domain
        },
        expires_at: "must-be-selected-before-execution"
      },
      activity: [{
        actor: "agent.research-scout",
        event: "corpus_oracle_authored",
        timestamp: "2026-07-29T00:00:00Z",
        artifact_hash: ("computed-at-replay:" + .id)
      }]
    }
)
| .cases |= map(
    if .id == "core.26"
    then .evidence.verdict = "inconclusive"
    else .
    end
  )
| .cases |= map(
    if .id == "core.30"
    then .hero_stages = [
      {
        stage: 1,
        state: "clarification_required",
        label: "Needs clarification",
        required_output: "I need 1 answer before I can verify this plan: may the buy execute before transfer settlement?"
      },
      {
        stage: 2,
        state: "ready_for_review",
        label: "Review interpretation",
        required_output: "Show the concurrent FSIR interpretation, source spans, unchanged properties, assumptions, and bounds for approval."
      },
      {
        stage: 3,
        state: "verification_running",
        label: "Verification in progress",
        required_output: "Show extraction complete, policy checks complete, and TLC running against the approved FSIR hash."
      },
      {
        stage: 4,
        state: "violation_found",
        label: "Plan blocked",
        required_output: "Name property.no_rejected_action and show the earliest buy-before-settlement state."
      },
      {
        stage: 5,
        state: "revision_proposed",
        label: "Safer revision proposed",
        required_output: "Show a v0→v1 FSIR diff adding settlement-before-buy and identify the counterexample it blocks."
      },
      {
        stage: 6,
        state: "reverification_required",
        label: "Changes need verification",
        required_output: "Invalidate the v0 evidence and require explicit approval before verifying v1."
      },
      {
        stage: 7,
        state: "checks_passed",
        label: "No configured guardrail was violated",
        required_output: "Report the named properties and exact max_steps=5 bound without calling the plan safe."
      },
      {
        stage: 8,
        state: "bounded_approval_required",
        label: "Ready for bounded approval",
        required_output: "Ask for approval of the exact actions, $300 limits, expiry, v1 model hash, assumptions, bounds, and verified properties."
      }
    ]
    else .
    end
  )
