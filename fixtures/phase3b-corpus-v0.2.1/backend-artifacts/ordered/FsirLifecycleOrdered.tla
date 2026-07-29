---- MODULE FsirLifecycleOrdered ----
EXTENDS Integers, FiniteSets, Sequences

\* Generated deterministically by fsir-tla-lowerer-0.1.
\* FSIR IDs are retained in source-map.json and lastEvent.

VARIABLES State_state_cash_brokerage_d2161d34, State_state_cash_checking_1c212abd, State_state_cash_savings_548e3bb7, State_state_position_brokerage_vti_f0670753, State_state_transfer_status_5ad17816, State_state_buy_status_a9cb3a91, done, selectedBranch, lastEvent
vars == <<State_state_cash_brokerage_d2161d34, State_state_cash_checking_1c212abd, State_state_cash_savings_548e3bb7, State_state_position_brokerage_vti_f0670753, State_state_transfer_status_5ad17816, State_state_buy_status_a9cb3a91, done, selectedBranch, lastEvent>>

Init ==
  /\ State_state_cash_brokerage_d2161d34 = 0
  /\ State_state_cash_checking_1c212abd = 600
  /\ State_state_cash_savings_548e3bb7 = 100
  /\ State_state_position_brokerage_vti_f0670753 = 0
  /\ State_state_transfer_status_5ad17816 = "not_submitted"
  /\ State_state_buy_status_a9cb3a91 = "not_submitted"
  /\ done = {}
  /\ selectedBranch = "fixed"
  /\ lastEvent = "init"

Act_event_transfer_submit_7cc1856e ==
  \* FSIR action event.transfer.submit
  /\ ~("event.transfer.submit" \in done)
  /\ TRUE
  /\ State_state_transfer_status_5ad17816' = "pending"
  /\ UNCHANGED <<State_state_buy_status_a9cb3a91, State_state_cash_brokerage_d2161d34, State_state_cash_checking_1c212abd, State_state_cash_savings_548e3bb7, State_state_position_brokerage_vti_f0670753>>
  /\ done' = done \cup {"event.transfer.submit"}
  /\ lastEvent' = "event.transfer.submit"
  /\ UNCHANGED selectedBranch

Act_event_transfer_settle_8282a791 ==
  \* FSIR action event.transfer.settle
  /\ ~("event.transfer.settle" \in done)
  /\ {"event.transfer.submit"} \subseteq done
  /\ TRUE
  /\ State_state_cash_brokerage_d2161d34' = State_state_cash_brokerage_d2161d34 + (300)
  /\ State_state_cash_checking_1c212abd' = State_state_cash_checking_1c212abd - (300)
  /\ UNCHANGED <<State_state_buy_status_a9cb3a91, State_state_cash_savings_548e3bb7, State_state_position_brokerage_vti_f0670753, State_state_transfer_status_5ad17816>>
  /\ done' = done \cup {"event.transfer.settle"}
  /\ lastEvent' = "event.transfer.settle"
  /\ UNCHANGED selectedBranch

Act_event_transfer_settled_cbeed67c ==
  \* FSIR action event.transfer.settled
  /\ ~("event.transfer.settled" \in done)
  /\ {"event.transfer.settle"} \subseteq done
  /\ TRUE
  /\ State_state_transfer_status_5ad17816' = "settled"
  /\ UNCHANGED <<State_state_buy_status_a9cb3a91, State_state_cash_brokerage_d2161d34, State_state_cash_checking_1c212abd, State_state_cash_savings_548e3bb7, State_state_position_brokerage_vti_f0670753>>
  /\ done' = done \cup {"event.transfer.settled"}
  /\ lastEvent' = "event.transfer.settled"
  /\ UNCHANGED selectedBranch

Act_event_buy_submit_762f7978 ==
  \* FSIR action event.buy.submit
  /\ ~("event.buy.submit" \in done)
  /\ {"event.transfer.settled"} \subseteq done
  /\ ((State_state_cash_brokerage_d2161d34 >= 0) /\ (State_state_position_brokerage_vti_f0670753 >= 0))
  /\ State_state_buy_status_a9cb3a91' = "submitted"
  /\ UNCHANGED <<State_state_cash_brokerage_d2161d34, State_state_cash_checking_1c212abd, State_state_cash_savings_548e3bb7, State_state_position_brokerage_vti_f0670753, State_state_transfer_status_5ad17816>>
  /\ done' = done \cup {"event.buy.submit"}
  /\ lastEvent' = "event.buy.submit"
  /\ UNCHANGED selectedBranch

Act_event_buy_execute_4deb6ea8 ==
  \* FSIR action event.buy.execute
  /\ ~("event.buy.execute" \in done)
  /\ {"event.buy.submit"} \subseteq done
  /\ TRUE
  /\ State_state_cash_brokerage_d2161d34' = State_state_cash_brokerage_d2161d34 - (300)
  /\ State_state_position_brokerage_vti_f0670753' = State_state_position_brokerage_vti_f0670753 + (300)
  /\ UNCHANGED <<State_state_buy_status_a9cb3a91, State_state_cash_checking_1c212abd, State_state_cash_savings_548e3bb7, State_state_transfer_status_5ad17816>>
  /\ done' = done \cup {"event.buy.execute"}
  /\ lastEvent' = "event.buy.execute"
  /\ UNCHANGED selectedBranch

Act_event_buy_filled_c24a1d40 ==
  \* FSIR action event.buy.filled
  /\ ~("event.buy.filled" \in done)
  /\ {"event.buy.execute"} \subseteq done
  /\ TRUE
  /\ State_state_buy_status_a9cb3a91' = "filled"
  /\ UNCHANGED <<State_state_cash_brokerage_d2161d34, State_state_cash_checking_1c212abd, State_state_cash_savings_548e3bb7, State_state_position_brokerage_vti_f0670753, State_state_transfer_status_5ad17816>>
  /\ done' = done \cup {"event.buy.filled"}
  /\ lastEvent' = "event.buy.filled"
  /\ UNCHANGED selectedBranch

Assume_assumption_lifecycle_weak_fairness_373c9396 == WF_vars(Act_event_transfer_submit_7cc1856e) /\ WF_vars(Act_event_transfer_settle_8282a791) /\ WF_vars(Act_event_transfer_settled_cbeed67c) /\ WF_vars(Act_event_buy_submit_762f7978) /\ WF_vars(Act_event_buy_execute_4deb6ea8) /\ WF_vars(Act_event_buy_filled_c24a1d40)

Next ==
  \/ Act_event_transfer_submit_7cc1856e
  \/ Act_event_transfer_settle_8282a791
  \/ Act_event_transfer_settled_cbeed67c
  \/ Act_event_buy_submit_762f7978
  \/ Act_event_buy_execute_4deb6ea8
  \/ Act_event_buy_filled_c24a1d40

Spec == Init /\ [][Next]_vars /\ Assume_assumption_lifecycle_weak_fairness_373c9396

Prop_property_safe_transfer_then_buy_order_sensitive_type_ok_1639d2da == TRUE

Prop_property_safe_transfer_then_buy_order_sensitive_no_negative_cash_3fdd966b == ((State_state_cash_brokerage_d2161d34 >= 0) /\ (State_state_cash_checking_1c212abd >= 0) /\ (State_state_cash_savings_548e3bb7 >= 0))

Prop_property_safe_transfer_then_buy_order_sensitive_allowed_action_kinds_ca5553fb == (("transfer" \in {"buy", "deposit", "sell", "swap", "transfer", "withdraw"}) /\ ("buy" \in {"buy", "deposit", "sell", "swap", "transfer", "withdraw"}))

Prop_property_safe_transfer_then_buy_order_sensitive_positive_amounts_8ede5d9e == ((300 > 0) /\ (300 > 0))

Prop_property_safe_transfer_then_buy_order_sensitive_individual_action_limit_d382ca75 == ((300 <= 300) /\ (300 <= 300))

Prop_property_safe_transfer_then_buy_order_sensitive_allowed_destinations_44e3ccf3 == (("account.brokerage" \in {"account.brokerage", "account.savings"}) /\ ("account.brokerage" \in {"account.brokerage", "account.savings"}))

Prop_property_safe_transfer_then_buy_order_sensitive_known_sources_23c79bfa == (("account.checking" \in {"account.brokerage", "account.checking", "account.savings"}) /\ ("account.brokerage" \in {"account.brokerage", "account.checking", "account.savings"}))

Prop_property_safe_transfer_then_buy_order_sensitive_gross_debit_budget_fe1fe139 == ((300 + 300) <= 600)

Prop_property_lifecycle_transfer_settles_9e300e77 == <>((State_state_transfer_status_5ad17816 = "settled"))

Prop_property_lifecycle_buy_fills_0d66f07a == <>((State_state_buy_status_a9cb3a91 = "filled"))

====
