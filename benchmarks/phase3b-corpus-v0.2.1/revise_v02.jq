def blocking_ids:
  ["core.05", "core.07", "core.12", "core.15", "core.16", "core.20", "core.26", "core.30"];

def controls($state):
  {
    approve: ($state == "bounded_approval_required"),
    edit: ($state == "clarification_required" or
           $state == "ready_for_review" or
           $state == "verification_unavailable" or
           $state == "revision_proposed" or
           $state == "reverification_required" or
           $state == "checks_passed" or
           $state == "bounded_approval_required"),
    reject: ($state == "ready_for_review" or
             $state == "revision_proposed" or
             $state == "reverification_required" or
             $state == "bounded_approval_required"),
    stop: ($state != "stopped"),
    revise: ($state == "violation_found"),
    rerun: ($state == "verification_unavailable"),
    clarify: ($state == "clarification_required"),
    inspect_evidence: ($state == "violation_found" or
                       $state == "checks_passed" or
                       $state == "bounded_approval_required"),
    resume: ($state == "stopped"),
    new_goal: ($state == "stopped"),
    verify: ($state == "ready_for_review" or $state == "reverification_required")
  };

def balances($id):
  if $id == "core.02" then [
    {"state.cash.checking":1000,"state.cash.brokerage":0,"state.cash.savings":300},
    {"state.cash.checking":900,"state.cash.brokerage":0,"state.cash.savings":300}
  ]
  elif $id == "core.03" then [
    {"state.cash.checking":1000,"state.cash.brokerage":0,"state.cash.savings":300},
    {"state.cash.checking":650,"state.cash.brokerage":350,"state.cash.savings":300},
    {"state.cash.checking":300,"state.cash.brokerage":350,"state.cash.savings":650},
    {"state.cash.checking":300,"state.cash.brokerage":300,"state.cash.savings":650}
  ]
  elif $id == "core.04" then [
    {"state.cash.checking":1000,"state.cash.brokerage":0,"state.cash.savings":300},
    {"state.cash.checking":599,"state.cash.brokerage":401,"state.cash.savings":300}
  ]
  elif $id == "core.08" then [
    {"state.cash.checking":1000,"state.cash.brokerage":0,"state.cash.savings":300},
    {"state.cash.checking":550,"state.cash.brokerage":0,"state.cash.savings":300}
  ]
  elif $id == "core.10" then [
    {"state.cash.checking":350,"state.cash.brokerage":100,"state.cash.savings":50},
    {"state.cash.checking":350,"state.cash.brokerage":-200,"state.cash.savings":50}
  ]
  elif $id == "core.11" then [
    {"state.cash.checking":1000,"state.cash.brokerage":0,"state.cash.savings":300},
    {"state.cash.checking":1000,"state.cash.brokerage":-300,"state.cash.savings":300}
  ]
  elif $id == "core.13" then [
    {"state.cash.checking":350,"state.cash.brokerage":100,"state.cash.savings":50},
    {"state.cash.checking":350,"state.cash.brokerage":-105,"state.cash.savings":50}
  ]
  elif $id == "core.14" then [
    {"state.cash.checking":350,"state.cash.brokerage":100,"state.cash.savings":50},
    {"state.cash.checking":350,"state.cash.brokerage":100,"state.cash.savings":-150},
    {"state.cash.checking":350,"state.cash.brokerage":100,"state.cash.savings":-350}
  ]
  elif $id == "core.18" then [
    {"state.cash.checking":1200,"state.cash.brokerage":0,"state.cash.savings":200},
    {"state.cash.checking":900,"state.cash.brokerage":0,"state.cash.savings":200},
    {"state.cash.checking":900,"state.cash.brokerage":-300,"state.cash.savings":200}
  ]
  elif $id == "core.27" then [
    {"state.cash.checking":1200,"state.cash.brokerage":0,"state.cash.savings":200},
    {"state.cash.checking":1200,"state.cash.brokerage":0,"state.cash.savings":200},
    {"state.cash.checking":1200,"state.cash.brokerage":0,"state.cash.savings":200}
  ]
  else [] end;

def unsupported_reason($id; $control; $bounds):
  if $id == "core.27" then "unsupported_repeated_action_semantics"
  elif ($id == "core.24" or $id == "core.29") then "unsupported_parallel_control"
  elif ($id == "core.11" or $id == "core.13" or $id == "core.21")
    then "unsupported_choice_topology"
  elif ($bounds.retry_limit > 0 or $bounds.time_horizon > 0)
    then "unsupported_retry_or_time_semantics"
  else "requires_exact_fsir_materialization"
  end;

def reject_message($reason):
  if $reason == "blocking_unresolved" then "blocking unresolved"
  elif $reason == "unsupported_choice_topology" then "choice topology requires exact FSIR branches"
  elif $reason == "unsupported_retry_or_time_semantics" then "max_retries and time_horizon must be zero"
  elif $reason == "unsupported_repeated_action_semantics" then "actions execute at most once"
  elif $reason == "unsupported_parallel_control" then "parallel control is unsupported; use explicit partial_order"
  else "exact FSIR v0.1 materialization required"
  end;

def stage_snapshot($stage):
  if $stage == 1 then {
    fsir_version:"fsir.core.30.v0", fsir_status:"clarification_required",
    review_status:"blocked", verification_status:"blocked",
    config_hash:null, model_hash:null, evidence_status:"none",
    counterexample:null, revision:null,
    controls:controls("clarification_required"),
    activity_event:"clarification_requested", approval_scope:null
  }
  elif $stage == 2 then {
    fsir_version:"fsir.core.30.v0", fsir_status:"review_required",
    review_status:"pending", verification_status:"blocked",
    config_hash:null, model_hash:null, evidence_status:"none",
    counterexample:null, revision:null,
    controls:controls("ready_for_review"),
    activity_event:"interpretation_presented", approval_scope:null
  }
  elif $stage == 3 then {
    fsir_version:"fsir.core.30.v0", fsir_status:"approved_for_verification",
    review_status:"approved", verification_status:"running",
    config_hash:"15d2ca0918c40660889fc5eb047caa5a6ba74f13be7eb6be883e596dc03724ce",
    model_hash:"dbbc7f15b80b5cf974b2a25e1ced5de13d5fdd1718bcd131f22594df51bdb11d",
    evidence_status:"pending", counterexample:null, revision:null,
    controls:controls("verification_running"),
    activity_event:"verification_started", approval_scope:null
  }
  elif $stage == 4 then {
    fsir_version:"fsir.core.30.v0", fsir_status:"verified_violation",
    review_status:"approved", verification_status:"violation_found",
    config_hash:"15d2ca0918c40660889fc5eb047caa5a6ba74f13be7eb6be883e596dc03724ce",
    model_hash:"dbbc7f15b80b5cf974b2a25e1ced5de13d5fdd1718bcd131f22594df51bdb11d",
    evidence_status:"current",
    counterexample:{
      fixture_id:"fixture.phase3a.lifecycle.concurrent",
      event_ids:["event.buy.submit","event.buy.execute"],
      violated_property_id:"property.no_rejected_action"
    },
    revision:null, controls:controls("violation_found"),
    activity_event:"violation_found", approval_scope:null
  }
  elif $stage == 5 then {
    fsir_version:"fsir.core.30.v1", fsir_status:"revision_proposed",
    review_status:"pending", verification_status:"blocked",
    config_hash:null, model_hash:null, evidence_status:"none",
    counterexample:{fixture_id:"fixture.phase3a.lifecycle.concurrent"},
    revision:{
      from_version:"fsir.core.30.v0", to_version:"fsir.core.30.v1",
      diff:["add settlement-before-buy edge"],
      addresses_event_ids:["event.buy.submit","event.buy.execute"]
    },
    controls:controls("revision_proposed"),
    activity_event:"revision_proposed", approval_scope:null
  }
  elif $stage == 6 then {
    fsir_version:"fsir.core.30.v1", fsir_status:"reverification_required",
    review_status:"approved", verification_status:"blocked",
    config_hash:null, model_hash:null, evidence_status:"stale",
    stale_evidence:{version:"fsir.core.30.v0",model_hash:"dbbc7f15b80b5cf974b2a25e1ced5de13d5fdd1718bcd131f22594df51bdb11d"},
    counterexample:null,
    revision:{from_version:"fsir.core.30.v0",to_version:"fsir.core.30.v1"},
    controls:controls("reverification_required"),
    activity_event:"prior_evidence_invalidated", approval_scope:null
  }
  elif $stage == 7 then {
    fsir_version:"fsir.core.30.v1", fsir_status:"verified",
    review_status:"approved", verification_status:"complete",
    config_hash:"15d2ca0918c40660889fc5eb047caa5a6ba74f13be7eb6be883e596dc03724ce",
    model_hash:"50836489a453ea2520cf5207e6e6f24dead291f13e6cb2f6ad2651169e7cf70c",
    evidence_status:"fresh", counterexample:null,
    revision:{from_version:"fsir.core.30.v0",to_version:"fsir.core.30.v1"},
    controls:controls("checks_passed"),
    activity_event:"reverification_passed", approval_scope:null
  }
  else {
    fsir_version:"fsir.core.30.v1", fsir_status:"verified",
    review_status:"approved", verification_status:"complete",
    config_hash:"15d2ca0918c40660889fc5eb047caa5a6ba74f13be7eb6be883e596dc03724ce",
    model_hash:"50836489a453ea2520cf5207e6e6f24dead291f13e6cb2f6ad2651169e7cf70c",
    evidence_status:"fresh", counterexample:null,
    revision:{from_version:"fsir.core.30.v0",to_version:"fsir.core.30.v1"},
    controls:controls("bounded_approval_required"),
    activity_event:"bounded_approval_requested",
    approval_scope:{
      actions:["action.submit-transfer","action.settle-transfer","action.execute-buy"],
      max_amount_usd:300, expires_at:"must-be-selected-before-execution"
    }
  } end;

.corpus_version = "phase3b-0.2"
| .semantic_projection_version = "corpus-semantic-projection-0.2"
| .backend_fixtures = [
    {
      id:"fixture.phase3a.lifecycle.ordered",
      frozen_commit:"fce10ae8",
      source_constructor:"tests.test_fsir_lowering.lifecycle_document('sequence')",
      control_kind:"sequence",
      module_name:"FsirLifecycleOrdered",
      artifact_directory:"backend-artifacts/ordered",
      fsir_document:$ordered[0],
      expected_tlc_verdict:"passed",
      expected_property_ids:$report[0].cases.ordered.expected_property_ids,
      expected_manifest:$report[0].cases.ordered.manifest,
      execution_evidence_manifest:$report[0].cases.ordered.execution_evidence_manifest,
      expected_normalized_event_ids:$report[0].cases.ordered.normalized_event_ids,
      source_map_direction:{
        states:"fsir_state_id_to_generated_entry",
        operators:"generated_operator_to_fsir_action_and_optional_outcome",
        properties:"generated_property_to_fsir_property",
        branches:"generated_branch_to_fsir_branch"
      }
    },
    {
      id:"fixture.phase3a.lifecycle.concurrent",
      frozen_commit:"fce10ae8",
      source_constructor:"tests.test_fsir_lowering.lifecycle_document('partial_order')",
      control_kind:"partial_order",
      module_name:"FsirLifecycleConcurrent",
      artifact_directory:"backend-artifacts/concurrent",
      fsir_document:$concurrent[0],
      expected_tlc_verdict:"property_violation",
      expected_property_ids:$report[0].cases.concurrent.expected_property_ids,
      expected_manifest:$report[0].cases.concurrent.manifest,
      execution_evidence_manifest:$report[0].cases.concurrent.execution_evidence_manifest,
      expected_normalized_event_ids:$report[0].cases.concurrent.normalized_event_ids,
      source_map_direction:{
        states:"fsir_state_id_to_generated_entry",
        operators:"generated_operator_to_fsir_action_and_optional_outcome",
        properties:"generated_property_to_fsir_property",
        branches:"generated_branch_to_fsir_branch"
      }
    }
  ]
| .cases |= map(
    .id as $case_id
    | .expected_semantics = .expected_fsir
    | del(.expected_fsir)
    | .positive_traces |= map(.semantic_event_ids = .expected_event_ids | del(.expected_event_ids))
    | .negative_traces |= map(.semantic_event_ids = .expected_event_ids | del(.expected_event_ids))
    | .lowering_oracle =
      (if .id == "core.17" then {
         frozen_commit:"fce10ae8", expectation:"lower",
         reason_code:"frozen_lifecycle_fixture", emits_artifacts:true,
         fixture_id:"fixture.phase3a.lifecycle.ordered", expected_rejection:null,
         semantic_action_map:{
           "action.submit-transfer":["event.transfer.submit"],
           "action.settle-transfer":["event.transfer.settle","event.transfer.settled"],
           "action.buy":["event.buy.submit","event.buy.execute","event.buy.filled"]
         },
         semantic_property_map:{
           "property.no_negative_cash":
             "property.safe_transfer_then_buy_order_sensitive.no_negative_cash"
         }
       }
       elif .id == "core.18" then {
         frozen_commit:"fce10ae8", expectation:"lower",
         reason_code:"frozen_lifecycle_fixture", emits_artifacts:true,
         fixture_id:"fixture.phase3a.lifecycle.concurrent", expected_rejection:null,
         semantic_action_map:{
           "action.submit-transfer":["event.transfer.submit"],
           "action.settle-transfer":["event.transfer.settle","event.transfer.settled"],
           "action.execute-buy":["event.buy.submit","event.buy.execute","event.buy.filled"]
         },
         semantic_property_map:{
           "property.no_negative_cash":
             "property.safe_transfer_then_buy_order_sensitive.no_negative_cash"
         }
       }
       elif (blocking_ids | index($case_id)) != null then {
         frozen_commit:"fce10ae8", expectation:"reject_blocking",
         reason_code:"blocking_unresolved", emits_artifacts:false,
         fixture_id:null,
         semantic_action_map:null, semantic_property_map:null,
         expected_rejection:{class:"ValueError",message_contains:"blocking unresolved"}
       }
       else
         (unsupported_reason($case_id; .expected_semantics.control; .bounds)) as $reason
         | {
           frozen_commit:"fce10ae8", expectation:"unsupported",
           reason_code:$reason, emits_artifacts:false, fixture_id:null,
           semantic_action_map:null, semantic_property_map:null,
           expected_rejection:{
             class:"UnsupportedFsirError",
             message_contains:reject_message($reason)
           }
         }
       end)
    | .product_projection.controls = controls(.product_projection.agent_phase)
    | .product_projection.verification.reason_code =
      (if .id == "core.26" then "missing_assumption" else null end)
    | .product_projection.verification.message =
      (if .id == "core.26"
       then "Eventual settlement is inconclusive because no fairness assumption is approved."
       else null end)
    | .product_projection.approval_scope.actions =
      (if .product_projection.agent_phase == "bounded_approval_required"
       then [.expected_semantics.actions[].id] else [] end)
    | (if .evidence.verdict == "fail" then
         .negative_traces[0].semantic_event_ids as $events
         | (balances($case_id)) as $balances
         | .product_projection.counterexample.path = [
             range(0; ($events|length)+1) as $index
             | {
                 state_id:("trace-state." + .id + "." + ($index|tostring)),
                 action_node_id:(if $index == 0 then null else $events[$index-1] end),
                 label:(if $index == 0 then "Init" else $events[$index-1] end),
                 balances:$balances[$index],
                 violations:
                   (if $index == ($events|length)
                    then .evidence.property_ids else [] end)
               }
           ]
         | .product_projection.counterexample.first_violating_state =
             ("trace-state." + .id + "." + (($events|length)|tostring))
         | .product_projection.findings |= map(
             .node_id = $events[-1]
           )
       else
         .product_projection.counterexample = {
           summary:"No counterexample is asserted.",
           first_violating_state:null,
           path:[]
         }
       end)
    | (if .id == "core.30"
       then .hero_stages |= map(
         .projection_snapshot = stage_snapshot(.stage)
         | .projection_snapshot.contract_hash =
           "c7548819d9217e0350fff4f186a9e76240f19a65d99593db26798644c1395d82"
       )
       else . end)
  )
