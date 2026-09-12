# Feature matrix

Every capability this product claims, with the evidence level it has actually earned and
the citation that earns it. The third column is what makes a claim checkable; the fourth is
the point of the document, because a row whose strongest evidence is a unit test is not the
same product as a row somebody watched work.

## The vocabulary

These levels are this project's own, and each one means something specific. They are
ordered weakest to strongest, and a row claims the strongest level that something in the
repository actually backs.

| Level | What it means |
| --- | --- |
| UNVERIFIED | None of the below. |
| IMPLEMENTED | The code exists and is reviewed. Nothing executes it in a check. |
| UNIT TESTED | A test drives the unit in isolation, usually with the things around it faked. |
| INTEGRATION TESTED | A test drives it through the real store, the real source and the real engine together. `tests/codexsim.py` builds a real Codex-shaped SQLite home - the tables and columns Codex itself writes - and every history and queue read goes through the production query layer, so a query that is wrong against the real schema fails there too. It is not a mock of the query layer. |
| REAL WINDOWS TESTED | It was run on a real Windows machine outside the ordinary logic of the suite: a compiled executable, a real named mutex, a real registry parser, a real PowerShell process, a captured screenshot. |
| REAL CODEX PROTOCOL TESTED | It was exercised against the real Codex desktop app's own databases or CLI, and the result is recorded under `docs/evidence/`. |
| REAL CODEX VISUALLY TESTED | A person watched it happen in Codex. |
| PUBLISHED | It is in a published release. |

## What this document is, and is not

- **It is written from the repository.** Every citation is something in this tree: a test
  module and test name, an artifact under `assets/` or `docs/images/`, a recorded
  observation under `docs/evidence/`, or a build output. Nothing here was established by
  reading a commit message or by remembering a session.
- **Nothing in it was verified by running the product against a real Codex conversation
  unless the row says so.** Five rows carry REAL CODEX PROTOCOL TESTED, and all five rest on
  the same 2026-09-06 measurements under `docs/evidence/`, taken against a disposable test
  thread. Everything else about recovery - correlation, outcomes, chains, budgets, expiry -
  has been driven only against `tests/codexsim.py`.
- **No row claims REAL CODEX VISUALLY TESTED.** Nothing in this repository records a person
  watching a recovery happen in Codex. The 2026-09-06 delivery check was confirmed through
  the desktop app's own task read and the thread's local history and queue, with
  `visual_ui_scraping_used: false` recorded in
  [`docs/evidence/unloaded-thread-observation.json`](evidence/unloaded-thread-observation.json).
  That is a protocol observation, not somebody watching.
- **v0.6.0 is not released.** Everything the changelog's Unreleased section describes is on
  `main` and unreleased, so no row about it can claim PUBLISHED. Where PUBLISHED appears
  here it refers only to what shipped in the releases up to the last one.
- **A REAL WINDOWS TESTED row usually means a test in the suite that needs a real Windows
  facility**, and those tests skip themselves where the facility is absent. A skipped test
  proves nothing, so the fourth column says where a skip is likely.

  For the record: on 2026-09-12, on the Windows 11 machine this document was written on,
  `PYTHONPATH="src;tests" python -m unittest discover -s tests` ran **1140 tests in 310
  seconds, with two failures and six skipped**. The run was red. Both failures are
  bookkeeping about the Korean branch rather than anything this document describes:
  `tests/test_korean.py:MappingTests.test_every_korean_document_is_mapped` fails because this
  document and `docs/LIVE_ACCEPTANCE.md` have Korean siblings that `scripts/ko_branch.json`
  does not list yet, and `test_no_translation_is_stale` fails because `README.md`,
  `CONTRIBUTING.md` and `docs/DEVELOPMENT.md` each gained a link to those two documents after
  their Korean siblings were last recorded as reviewed. Adding the mapping and running
  `python scripts/ko_sync.py --reviewed <english path>` clears both; neither touches the
  product. All six skips were the opt-in live checks in `tests/test_integration_live.py`,
  every one of them declining to run without `CODEX_AR_LIVE=1`. So every REAL WINDOWS TESTED
  row below did run here, and none of the checks that would touch a real Codex installation
  did.

## How to read a citation

`tests/test_engine.py:GateTests.test_T47_a_subagent_or_non_desktop_thread_is_never_detected`
is module, then class, then test. Where several tests in one class back a row, the class is
named with a count rather than every method. Artifacts are given by path.

---

## 1. Detection and classification

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| A usage limit is read from Codex's own turn row (`status=failed`, `codexErrorInfo=usageLimitExceeded`) | REAL CODEX PROTOCOL TESTED | `docs/evidence/usage-limit-sample.json`, captured read-only from a real Codex database on 2026-09-06. `tests/test_source.py:DetectionTests.test_real_usage_sample` runs detection over `tests/fixtures/usage-limit.json` - a sanitized copy of that capture, carrying its own made-up ids and its own field names - and not over the capture itself | One capture, one account, one Codex build. Nothing re-checks the shape against a newer Codex, and **nothing in the suite reads `docs/evidence/usage-limit-sample.json` at all**, so the fixture can drift away from the capture it was made from without a test noticing. |
| The reset time comes from the rate-limit snapshot preceding the failure, not from the message text | REAL CODEX PROTOCOL TESTED | The same capture records `resets_at` beside the UI's own "try again at" phrase, and `contains_machine_readable_reset_in_error: false`. `tests/test_source.py:DetectionTests.test_real_reset_and_timezone` chooses the reset from the fixture's own rate-limit rows and requires the fixture's own expected value; `test_low_usage_hint_is_not_adopted_as_reset` works from values written in the test | Nothing checks the two still agree on a current Codex, and nothing re-checks the fixture against the published capture. |
| A failed turn's rollout event is named `task_complete` and still carries the error, so an event name is never read as success | REAL CODEX PROTOCOL TESTED | `docs/evidence/usage-limit-sample.json` (`rollout_failure.payload_type: task_complete`); `tests/test_source.py:LocalSourceTests.test_detect_actual_shape` detects that failure in a hand-built Codex home seeded from the fixture's copy of the rollout event, not from the capture | The same single capture, and nothing re-checks the fixture against it. |
| Transient failures are classified and recovered on their own policy | INTEGRATION TESTED | `tests/test_failures.py:TransientTests` (3 tests); `tests/test_recovery.py:PolicySeparationTests.test_a_transient_failure_waits_on_backoff_not_on_a_reset` | No recorded observation of a real transient Codex failure; the codes come from the schema, not from a capture. |
| Terminal failures are never retried | UNIT TESTED | `tests/test_failures.py:TerminalTests` (3 tests, incl. `test_authentication_is_terminal_not_a_retry_budget`); `tests/test_recovery.py:UnknownNeverRetriedTests.test_a_terminal_failure_is_never_registered` | No captured real instance of any terminal code. |
| An unclassified failure is never registered and never retried | INTEGRATION TESTED | `tests/test_failures.py:UnknownTests` (6 tests), `DetectionGateTests.test_only_recoverable_categories_are_ever_registered`; `tests/test_recovery.py:UnknownNeverRetriedTests.test_an_unclassified_failure_is_never_registered` | - |
| A rate limit Codex itself gave up on (`429`, too many attempts) waits at least a minute | INTEGRATION TESTED | `tests/test_outcomes.py:T27RateLimitTests` (3 tests); `tests/test_recovery.py:PolicySeparationTests.test_T27_a_rate_limit_codex_gave_up_on_waits_at_least_a_minute` | Not observed against a real 429. |
| Only the exact conversation UUID is ever acted on; `--last` is never used | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_18_one_thread_failure_never_resumes_another`; `tests/test_windows.py:BackendTests.test_queue_argv_exact_id_shell_disabled_and_no_telemetry`, `test_invalid_thread_id_never_launches` | - |
| Subagent, archived and non-desktop conversations are never detected | INTEGRATION TESTED | `tests/test_source.py:ChildThreadTests` (3 tests, incl. `test_T47_state_row_and_rollout_must_both_say_user`); `tests/test_engine.py:GateTests.test_T47_a_subagent_or_non_desktop_thread_is_never_detected` | The originator values come from the simulated home; no capture of a real subagent thread. |
| A failure older than the look-back is never detected later | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_12b_disabled_at_failure_time_is_not_detected_later_beyond_lookback`; `tests/test_source.py:LocalSourceTests.test_ignore_historic_failure` | - |
| Detection keeps no error text | UNIT TESTED | `tests/test_failures.py:DetectionGateTests.test_no_error_text_survives_detection` | - |

## 2. The gates

Every send passes a fixed vector of gates. A gate that refuses is recorded beside the
record rather than folded into its state.

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| The gate vector is written on a granted claim, and a refusal makes no transition | INTEGRATION TESTED | `tests/test_outcomes.py:T31GateEvalTests.test_T31_the_gate_vector_is_written_on_a_granted_claim`, `test_T31_a_refused_claim_writes_consent_block_and_makes_no_transition` | - |
| Global pause is an immediate kill switch and preserves what is pending | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_12_global_disable_is_immediate_kill_switch`; `tests/test_control.py:StatusTests.test_pause_preserves_pending_records` | - |
| A conversation switched off never queues, and others are unaffected | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_13_thread_disabled_never_queues_but_other_thread_does`; `tests/test_outcomes.py:T31GateEvalTests.test_T31_a_due_record_on_a_disabled_thread_records_consent_block` | - |
| Nothing is sent before the real reset time | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_07_before_reset_never_queues`, `GateTests.test_T31_a_future_reset_is_a_wait_with_a_reason` | - |
| Nothing is sent while the desktop app is closed, the conversation is not loaded, or loaded state is unknown | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_09_after_reset_not_loaded_waits`, `test_11_app_closed_never_queues`, `test_unknown_loaded_state_never_queues` | The gate exists because of the finding below; the gate itself has never run against a real unloaded thread. |
| A message queued for an unloaded conversation is not delivered as a turn - the finding the gate is built on | REAL CODEX PROTOCOL TESTED | `docs/evidence/unloaded-thread-delivery.json` (verdict FAIL after a genuine app restart, 90-second window) and `docs/evidence/unloaded-thread-observation.json` | One 90-second window, one Codex build. Codex may deliver later; the evidence says so and the README repeats it. |
| A message queued for a loaded conversation is delivered into that exact conversation | REAL CODEX PROTOCOL TESTED | `docs/evidence/loaded-thread-delivery.json` (`same_thread_user_message_confirmed`, `same_thread_agent_message_confirmed`, `pending_test_items_after_delivery: 0`) | Confirmed through the app's task read and local history, not watched by a person. One thread, one run, 2026-09-06. |
| Loaded state is decided from the Restart Manager, and this tool never takes the app's writer lock | UNIT TESTED | `tests/test_windows.py:BackendTests`, eight loaded-state tests in that class (incl. `test_tool_never_acquires_the_apps_writer_lock`, `test_pid_reuse_fails_closed`, `test_ambiguous_resource_users_fail_closed`) | The classifier runs against faked Restart Manager output. `tests/test_integration_live.py:LiveReadOnlyTests.test_loaded_state_classification_of_existing_locks` would check it for real; it is one of the six tests skipped without `CODEX_AR_LIVE=1`, and nothing here records a run. |
| Live usage is re-checked immediately before a send, and an unavailable probe waits | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_15d_usage_still_unavailable_does_not_queue`; `tests/test_windows.py:UsageTests` (9 tests, incl. `test_missing_or_malformed_safe_unknown`, `test_private_response_fields_are_discarded`) | The real probe is exercised only by the opt-in live check, which nothing records running. |
| A history projection that has fallen behind its rollout blocks the send | INTEGRATION TESTED | `tests/test_outcomes.py:T32ProjectionTests` (5 tests); `tests/test_source.py:LocalSourceTests.test_projection_fresh_when_caught_up`, `test_projection_not_fresh_when_the_rollout_grew` | The staleness thresholds were chosen, not measured against a real Codex under load. |
| A missing projection table blocks as incompatible rather than passing | INTEGRATION TESTED | `tests/test_outcomes.py:T32ProjectionTests.test_T32_a_missing_projection_table_blocks_as_incompatible`; `tests/test_engine.py:GateTests.test_T32_a_missing_projection_table_blocks_compatibility` | - |
| One send in flight per conversation; a cooldown and a daily cap | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_thread_cooldown_and_daily_cap`, `test_15e_a_launch_retry_still_respects_the_thread_cooldown` | - |
| Two engines on one state send once | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_16_two_engines_on_same_state_send_once` | Two engines in one process against one file - not two real watcher processes racing. |
| The same interruption is never resumed twice, across a crash or a restart | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_crash_after_reserve_before_send_never_resends`, `test_15b_unknown_send_outcome_is_never_resent`, `test_14_watcher_restart_preserves_pending`; `tests/test_store.py:StoreTests.test_reserved_interruption_survives_crash_as_submitting`, `test_unknown_submission_can_resolve_but_never_retry` | - |
| A policy setting cannot reach a safety gate | UNIT TESTED | `tests/test_engine.py:PolicyTests.test_policy_cannot_reach_a_safety_gate`, `test_no_setting_names_an_engine_safety_option`; `tests/test_settings.py:DefaultsTests.test_no_setting_can_enable_recovery_of_an_unknown_failure` | - |

## 3. Exact turn correlation

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| The continuation carries a marker built from the interruption's own id, and the recovery turn is the marker row's turn - not the latest turn | INTEGRATION TESTED | `tests/test_correlation.py:CorrelationTest.test_T01_recovery_turn_is_the_marker_rows_turn_even_after_a_later_user_turn`; `tests/test_engine.py:CorrelationTests.test_T01_the_recovery_turn_survives_a_watcher_restart`; `tests/test_source.py:LocalSourceTests.test_marker_rows_report_their_own_turn_not_the_latest` | Never correlated against a marker a real Codex wrote. The marker rows in the simulation are written by the simulation. |
| The engine has no way to ask for "the latest turn" | UNIT TESTED | `tests/test_source.py:StaticQueryTests.test_T01_latest_turn_id_is_gone`; `tests/test_engine.py:CorrelationTests.test_T01_latest_turn_id_is_gone_from_the_source`. Both read the files under `src/` and require the identifier `latest_turn_id` to be absent; neither runs a query | What is checked is that one spelling is gone, not that the capability is. A renamed helper that still returned the latest turn would pass both. |
| Two marker rows are never correlated; the record stays ambiguous and our queued row is still taken back | INTEGRATION TESTED | `tests/test_correlation.py:CorrelationTest.test_T02a_two_marker_rows_are_never_correlated`, `test_T02a_two_marker_rows_still_withdraw_our_queued_row` | - |
| A marker with a different client id, or at or before the failed turn, is ambiguous | INTEGRATION TESTED | `tests/test_correlation.py:CorrelationTest.test_T02c_different_client_id_is_an_ambiguous_receipt`, `test_T02e_marker_at_or_below_the_failed_ordinal_is_ambiguous`, `test_T02d_null_client_ids_leave_the_marker_rules_alone` | The client id column's real values come from one Codex build. |
| A marker steered into somebody else's turn is handed over, not claimed | INTEGRATION TESTED | `tests/test_correlation.py:CorrelationTest.test_T02b_marker_steered_into_someone_elses_turn_is_handed_over` | - |
| One Codex turn can belong to at most one record | UNIT TESTED | `tests/test_store.py:TransitionTableTests.test_T12_a_recovery_turn_is_written_once` (the unique index) | - |
| An undetermined turn is never a reason to delete a queued row, and never holds back a cancel or a pause | INTEGRATION TESTED | `tests/test_correlation.py:WatchTest.test_T03_undetermined_turn_is_never_a_reason_to_delete`, `test_T03_an_undetermined_turn_never_holds_back_a_cancel_or_a_pause` | - |
| A change between the claim and the send releases the claim, and nothing is announced in between | INTEGRATION TESTED | `tests/test_correlation.py:WatchTest.test_T08_change_between_reserve_and_send_releases_the_claim`, `test_T08_no_notification_between_claim_and_send`; `tests/test_outcomes.py:T48NotificationTests.test_T48_nothing_is_announced_between_the_claim_and_the_send` | - |
| A foreign item queued before or behind ours makes us wait, or take ours back | INTEGRATION TESTED | `tests/test_correlation.py:WatchTest.test_T09_foreign_queued_input_makes_the_record_wait`, `test_T09_foreign_item_queued_while_ours_is_queued_withdraws_ours` | - |
| An edited queued item is handed over without a delete | INTEGRATION TESTED | `tests/test_correlation.py:WatchTest.test_T10_edited_queued_item_is_handed_over_without_a_delete` | Editing is simulated by rewriting the queue row; nobody has edited a queued item in Codex and watched the result. |
| A marker already in Codex releases the claim as a duplicate owner | INTEGRATION TESTED | `tests/test_engine.py:CorrelationTests.test_T45_a_marker_already_in_codex_releases_the_claim_as_a_duplicate_owner` | - |

## 4. Outcomes

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| The outcome is read from the correlated turn and no other | INTEGRATION TESTED | `tests/test_outcomes.py:T13OutcomeRulesTests` (6 tests); `tests/test_engine.py:OutcomeTests` (11 tests) | - |
| A turn that never finishes is unverified at the deadline - never a success | INTEGRATION TESTED | `tests/test_outcomes.py:T13OutcomeRulesTests.test_T13_a_row_that_stays_in_progress_becomes_unverified_at_the_deadline`, `test_T13_a_later_terminal_turn_proves_an_in_progress_row_stale` | - |
| An unreadable history is retried to the deadline and never becomes "no progress" | INTEGRATION TESTED | `tests/test_outcomes.py:T13OutcomeRulesTests.test_T13_unreadable_history_is_retried_then_hits_the_deadline_never_no_progress`, `test_T13_history_that_becomes_readable_again_is_evaluated_normally` | - |
| An interrupted recovery turn is "stopped by the user" | INTEGRATION TESTED | `tests/test_outcomes.py:T13OutcomeRulesTests.test_T13_an_interrupted_recovery_turn_is_stopped_by_the_user` | The status string comes from the schema; no capture of a real user interrupt. |
| A completed turn that produced nothing is "no progress", in a chain as well as alone | INTEGRATION TESTED | `tests/test_outcomes.py:T15NoProgressTests` (2 tests) | - |
| A person joining the turn hands it over at once, and its child is superseded rather than claimed | INTEGRATION TESTED | `tests/test_outcomes.py:T16UserJoinedTests` (3 tests) | - |
| Nothing is judged before the turn's own items are projected, and a terminal status first seen late still waits one more tick | INTEGRATION TESTED | `tests/test_outcomes.py:T14SettleTests` (2 tests); `tests/test_engine.py:OutcomeTests.test_T14_a_turn_first_seen_long_after_it_finished_still_waits_one_tick` | - |
| Progress is decided without reading any content | INTEGRATION TESTED | `tests/test_recovery.py:NoProgressTests.test_progress_is_decided_without_reading_any_content`; `tests/test_source.py:LocalSourceTests.test_turn_observation_progress_only_known_types_in_that_turn` | - |
| A stale observing record does not block a newer failure | INTEGRATION TESTED | `tests/test_outcomes.py:T17StuckObservingTests` (2 tests) | - |
| A late delivery after an unknown result is announced | INTEGRATION TESTED | `tests/test_outcomes.py:T48NotificationTests.test_T48_a_late_delivery_after_an_unknown_result_is_announced`; `tests/test_engine.py:OutcomeTests.test_T48_a_late_delivery_after_an_unknown_result_is_announced` | - |

## 5. Budgets, chains and usage expiry

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| A failure of our own recovery turn continues its parent's chain rather than starting a new one | INTEGRATION TESTED | `tests/test_outcomes.py:T18ChainTests` (5 tests); `tests/test_recovery.py:ChainTests` (6 tests) | - |
| The child inherits every counter in the one transaction that creates it | UNIT TESTED | `tests/test_store.py:CrashInjectionTests.test_T19_register_with_a_parent_is_all_or_nothing`; `tests/test_store.py:StoreTests.test_every_record_belongs_to_a_chain` | - |
| A cancelled, handed-over or exhausted parent makes its child arrive already stopped | INTEGRATION TESTED | `tests/test_outcomes.py:T20LineageTests` (2 tests); `tests/test_recovery.py:ChainTests.test_T20_a_cancelled_parent_stops_its_child_before_its_own_outcome`; `tests/test_store.py:CancelTests.test_T21_nothing_running_reports_no_change_but_blocks_a_future_child` | - |
| Six continuations per task by default; the setting takes 1 to 10 and nothing outside | UNIT TESTED | `tests/test_engine.py:PolicyTests.test_the_chain_cap_can_be_lowered_but_never_raised_past_ten`, `test_the_attempt_budget_comes_from_the_settings`; `tests/test_settings.py:DescribeTests.test_published_ranges_accept_their_own_bounds` | - |
| The attempt budget holds across records and across a restart | INTEGRATION TESTED | `tests/test_recovery.py:BudgetTests` (3 tests, incl. `test_attempts_persist_across_a_restart`) | - |
| A usage chain stops at the continuation cap whatever the attempt budget | INTEGRATION TESTED | `tests/test_outcomes.py:T18ChainTests.test_T18_a_usage_chain_stops_at_the_chain_cap_whatever_the_attempt_budget` | - |
| Time without usage accumulates across a chain and expires it at seven days | INTEGRATION TESTED | `tests/test_outcomes.py:T28UsageExpiryTests` (4 tests); `tests/test_engine.py:GateTests.test_T28_the_never_available_limit_is_seven_days`, `test_T28_only_unavailable_time_between_probes_accumulates` | Seven days of real wall-clock behaviour has never been observed; the clock is the test's. |
| A weekly limit never expires before its own reset plus a day | INTEGRATION TESTED | `tests/test_outcomes.py:T28UsageExpiryTests.test_T28_a_weekly_reset_never_expires_before_reset_plus_a_day`; `tests/test_engine.py:GateTests.test_T28_a_weekly_limit_never_expires_before_its_reset` | - |
| Giving attempts back is bounded to three per task, belongs to the chain, restores only the two exhausted states, and sends nothing | UNIT TESTED | `tests/test_store.py:RestoreBudgetTests` (13 tests, incl. `test_T26_the_fourth_reset_of_a_record_is_refused`, `test_T26_the_reset_count_belongs_to_the_chain`, `test_does_not_submit`, `test_never_reactivates_something_that_may_have_been_sent`) | - |
| It re-enters the wait its kind of failure needs, and leaves a switched-off conversation off | UNIT TESTED | `tests/test_store.py:RestoreBudgetTests.test_T26_usage_record_returns_to_its_reset_wait_and_transient_to_backoff`; `tests/test_control.py:BudgetTests.test_reset_returns_a_record_to_the_wait_its_kind_of_failure_needs`, `test_reset_leaves_a_switched_off_conversation_off` | - |
| Retry now moves only the schedule: it does not send, does not skip a gate, does not open a usage window | UNIT TESTED | `tests/test_store.py:RetryNowTests` (3 tests); `tests/test_control.py:RetryNowTests` (4 tests); `tests/test_control_v3.py:RetryNowTests` (2 tests); `tests/test_mcp.py:ToolBehaviourTests.test_retry_now_does_not_submit`, `test_retry_now_says_the_checks_still_apply` | - |
| Retry now wakes the watcher | IMPLEMENTED | `src/codex_auto_resume/windows.py:WakeEvent`; the control layer reports whether anything woke, and `tests/test_control_v3.py:RetryNowTests` covers the "no watcher to wake" answer | **No test signals a real wake event and observes a waiting watcher shorten its wait.** The only covered path is the one where the event is unavailable (`tests/test_cli.py:WatcherLoopTests`). |
| Cancel reaches every record of the task and no other, and is retried under a write lock rather than refused | UNIT TESTED | `tests/test_store.py:CancelTests` (3 tests); `tests/test_control_v3.py:ChainCancelTests` (2 tests); `tests/test_outcomes.py:T23CancelContentionTests` (2 tests, incl. `test_T23_cancel_succeeds_by_retrying_under_a_12_second_write_lock`) | - |
| Cancel racing the send marks the record and the watch withdraws it | INTEGRATION TESTED | `tests/test_outcomes.py:T22CancelRaceTests` (2 tests); `tests/test_engine.py:PauseAndCancelTests.test_T22_cancel_racing_the_send_marks_and_the_watch_withdraws` | That a turn already running in Codex is not stopped is documented, not observed against Codex. |
| Pause withdraws a queued continuation and returns the record to waiting; a withdrawal over a stale history is never released | INTEGRATION TESTED | `tests/test_outcomes.py:T24PauseTests` (5 tests), `T25PausedWatchTests` (4 tests); `tests/test_pause_unknown.py:PausedUnknownTests.test_a_pause_withdraws_it_and_it_ends_final` | The withdrawal is the simulated App Server delete; a real withdrawal has never been measured. |

## 6. The public vocabulary

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| 27 stored states map onto 22 public codes, exactly as the design table says | UNIT TESTED | `tests/test_outcomes.py:T29T30PublicCodeTests.test_T29_there_are_twenty_seven_stored_states`, `test_T29_T30_every_stored_record_maps_as_the_design_table_says`, `test_T29_every_stored_failed_is_failed_terminal`; `tests/test_labels_v3.py:LabelTests.test_every_stored_state_maps_to_a_public_code` | - |
| A public code never depends on a setting | UNIT TESTED | `tests/test_outcomes.py:T29T30PublicCodeTests.test_T29_the_code_does_not_change_with_the_attempt_budget`, `test_T29_the_mapping_module_imports_no_settings`; `tests/test_labels_v3.py:LabelTests.test_a_failed_record_is_never_described_as_retrying` | - |
| Overlays never apply to a record that may already have been sent | UNIT TESTED | `tests/test_outcomes.py:T29T30PublicCodeTests.test_T30_overlays_never_apply_to_a_record_that_may_have_been_sent`, `test_T30_a_claimed_record_with_a_receipt_or_queue_id_reads_as_submitted` | - |
| Every public code and overlay has a label in every language | UNIT TESTED | `tests/test_labels_v3.py:LabelTests.test_every_public_code_and_overlay_has_a_label_in_every_language`; `tests/test_locale.py:CatalogTests` (9 tests) | Nobody has read the Korean labels in the running window; they exist only in the Korean screenshots. |
| The window, the panel and the tools show the public code; the command line also prints the stored state | UNIT TESTED | `tests/test_control_v3.py:HistoryAndStatisticsTests.test_the_timeline_code_is_the_code_the_listing_shows`, `test_listing_carries_the_public_code_and_overlays` | - |
| Every refusal carries a code from a closed set, the same code every time, beside a sentence | UNIT TESTED | `tests/test_control.py:ErrorCodeTests` (11 tests); `tests/test_mcp.py:RefusalTests` (6 tests); `tests/test_control_v3.py:RefusalCodeTests` (5 tests); `tests/test_locale.py:CatalogTests.test_every_refusal_code_has_a_sentence_in_every_language` | - |

## 7. The Dashboard

The window is C#. Most of it is checked by asserting the shape of `gui/Dashboard.cs`, or by
testing the control layer it calls. Only a few rows run the compiled program.

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| Six pages - Overview, Pending, History, Statistics, Diagnostics, Settings | REAL WINDOWS TESTED, for three of the six | `gui/Dashboard.cs` builds all six; `docs/images/dashboard-overview.png`, `docs/images/dashboard-pending.png` and `docs/images/settings-window.png` are captures of the compiled window taken with `build/capture_window.ps1` at 144 DPI, pinned in `assets/screenshots.json` and checked by `tests/test_screenshots.py:ManifestTests` (5 tests) | **No artifact of any kind for History, Statistics or Diagnostics.** Nothing in the repository shows those three pages ever rendering. Three more captures the same way would fix it. |
| The screenshots are current: the suite fails when what they were rendered from changes | UNIT TESTED | `tests/test_screenshots.py:ManifestTests.test_every_render_input_is_unchanged_since_the_images_were_made`, `test_the_committed_images_are_the_ones_the_manifest_describes`, `test_the_window_inputs_include_what_the_dashboard_is_computed_by` | The manifest records the last release's version, so a screenshot's footer is a release behind until a release is made. |
| The sample data in the screenshots carries no real identifier | UNIT TESTED | `tests/test_screenshots.py:ContentTests.test_the_window_sample_carries_no_real_identifier`, `test_the_sample_data_carries_no_real_identifier` | - |
| The window talks to one long-lived bridge process, one JSON line per request | UNIT TESTED | `tests/test_gui_layout.py:PersistentBridgeTests.test_the_serve_command_line_answers_a_request` runs the exact command line the window builds and requires a real reply; `tests/test_control.py:BridgeTests.test_serve_answers_every_line_with_exactly_one_line`, `test_serve_framing_edge_cases_each_get_the_answer_they_should`, `test_serve_cannot_reach_anything_the_one_shot_form_cannot` | The compiled window's own client of that bridge is never driven. |
| The whole Overview arrives in one round trip, each part failing on its own | UNIT TESTED | `tests/test_control.py:BridgeTests.test_a_dashboard_part_that_fails_costs_only_that_part` | Tested at the bridge. Whether the window renders a failed part correctly is not checked. |
| A part that cannot be read is shown as unreadable, not as an empty list | IMPLEMENTED | `gui/Dashboard.cs` (`ShowUnreadable`, `MarkUnavailable`, `ClearRecent`) | **Unverified in the window.** Nothing asserts the C# takes that branch, and no screenshot shows it. A capture with the bridge made to fail would settle it. |
| Nothing that talks to the bridge runs on the UI thread | UNIT TESTED | `tests/test_gui_layout.py:WatcherStartReportingTests.test_the_wait_does_not_happen_on_the_ui_thread`, `test_it_does_not_wait_a_fixed_time_and_hope`, `test_it_reads_the_state_the_engine_reported` | These are source-shape assertions: they pin the reasoning, and pass on code that is wrong in a new way. |
| Each action addresses a recovery by its exact interruption id, and each confirmation names the conversation | UNIT TESTED, at the control layer | `tests/test_control.py:IdentifierTests` (3 tests); `tests/test_control_v3.py:ThreadSwitchTests.test_the_switch_needs_an_exact_id` | The C# half - that the id sent is the selected row's, and that the confirmation really carries the name - is unverified. |
| Retry now is offered only where it can do something; giving attempts back is offered where it cannot send | IMPLEMENTED | `gui/Dashboard.cs` (`UpdatePendingButtons`, `UpdateHistoryButtons`); every refusal those conditions avoid is tested at the control layer: `tests/test_control_v3.py:RefusalCodeTests.test_each_retry_now_refusal_arrives_as_its_own_code`, `test_each_restore_budget_refusal_arrives_as_its_own_code` | **The enabling logic itself is unverified.** A wrong condition offers a button that then refuses - safe, but the window has promised something it cannot do. |
| The timeline shows one chain in the public words and is content-free | UNIT TESTED | `tests/test_control_v3.py:HistoryAndStatisticsTests.test_the_timeline_is_content_free`, `test_the_timeline_code_is_the_code_the_listing_shows` | No artifact shows the timeline dialog. |
| Clear history hides and never deletes; hidden rows still count for every cap and duplicate check | UNIT TESTED | `tests/test_store.py:HideHistoryTests` (2 tests, incl. `test_T41_hidden_rows_still_count_for_every_safety_decision`); `tests/test_control_v3.py:HistoryAndStatisticsTests.test_clear_history_hides_finished_records_and_keeps_them_counting` | - |
| Statistics over 7 days, 30 days or all of it; one final outcome per record; a success rate only above five | UNIT TESTED | `tests/test_store.py:StatisticsTests` (4 tests, incl. `test_T44_a_late_receipt_counts_once`, `test_statistics_include_hidden_rows`) | The Statistics page itself has no artifact. |
| Export diagnostics writes a redacted file and never overwrites | UNIT TESTED | `tests/test_diagnostics.py:DiagnosticsTests` (4 tests) | Only `diagnostics.write` is tested. The button, the file picker and the read-before-you-send flow are unverified. |
| Repair installation reports which of five things happened, under the installer's own lock, with `--keep-state` | IMPLEMENTED | `gui/Dashboard.cs` (`Repair`, `RunRepair`, `ReportRepair`); the lock it contends for is tested in `tests/test_convergence.py:InstallerLockTests` (3 tests) and `--keep-state` in `tests/test_plugin.py:BridgeTests.test_keep_state_repairs_an_autostart_that_is_already_ours` | **None of the five outcomes is exercised.** "Busy", "still running", "incomplete" and the trimmed failure tail are unverified. Driving `RunRepair` against a fake setup process returning each condition would cover them. |
| Stop watcher asks through the stop event, never kills, and reports stopped / still finishing / not running / unknown | UNIT TESTED | `tests/test_control.py:StopWatcherTests` (9 tests, incl. `test_the_stop_is_asked_once_and_nothing_is_ever_killed`, `test_a_probe_that_cannot_tell_is_unknown_and_never_stopped`, `test_the_layer_holds_no_way_to_end_a_process`) | The window's button is not driven, and the four wordings appear in no artifact. |
| Start watcher confirms through the mutex probe and never overclaims | UNIT TESTED | `tests/test_control.py:StartWatcherTests` (6 tests), `WatcherConfirmationTests` (8 tests), `StartWatcherReportingTests` (6 tests, incl. `test_every_outcome_has_wording_that_does_not_overclaim`) | - |
| The wire between window and bridge is UTF-8 whatever the machine's code page | REAL WINDOWS TESTED | `tests/test_bridge_encoding.py:WireEncodingTests` (5 tests) run the real bridge in a subprocess with `PYTHONIOENCODING=cp949` and UTF-8 mode off | The decoding half is asserted against the C# source, not against the running window. |
| A malformed or deeply nested reply is an ordinary format error, not a process death | REAL WINDOWS TESTED | `tests/test_gui_json.py:ParserRobustnessTests` (5 tests) compile the real window with the in-box C# compiler and run a probe process: `test_the_probe_process_survived`, `test_the_limit_is_where_it_says` | Skipped where the in-box compiler or PowerShell is absent. |
| Layout: the editor row, the footer, the numeric inset, buffered painting | UNIT TESTED, with a real capture behind it | `tests/test_gui_layout.py:RowLayoutTests` (3), `FooterTests` (3), `NumericInsetTests` (5), `BufferedPaintTests` (2). The module records that the rendering was measured at six display scalings and against the real window at 144 DPI | Those measurements are described in a docstring, not stored as artifacts. Only the 144 DPI case has a committed capture. |
| Nothing is written in raw pixels; the column holding the state dot scales too | UNIT TESTED | `tests/test_brand.py:WindowScalingTests` (3 tests); `tests/test_screenshots.py:PixelTests.test_every_window_screenshot_shows_the_state_dot`, `test_every_window_screenshot_has_both_hairlines` | Only one scaling has a committed screenshot. |
| The window writes no colour of its own; every colour comes from the palette | UNIT TESTED | `tests/test_brand.py:SurfaceTests.test_settings_window_writes_no_colour_of_its_own`, `GeneratedFileTests.test_gui_brand_cs_is_current`; `tests/test_brand.py:RetiredColourTests.test_no_tracked_file_still_carries_a_retired_colour` | - |
| No local web server, and nothing opens in a browser | IMPLEMENTED | `tests/test_privacy_claims.py:CodePropertyTests.test_the_recovery_runtime_imports_no_networking_module` covers `src/` and `scripts/*.py`, where nothing listens or dials | **`gui/*.cs` is not covered by that check.** Nothing asserts the window opens no socket and launches no browser. Extending the same grep to the C# sources would close it. |
| The lists refresh every five seconds | IMPLEMENTED | `gui/Dashboard.cs` (`StartClock`, `RefreshNow`, `UpdateCountdowns`) | Unverified. Nothing measures the interval, or that a refresh cannot land between a confirmation and the action it confirms. |

## 8. The notification-area icon

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| The icon belongs to the watcher process: it appears when one starts and goes when it stops | REAL WINDOWS TESTED | `tests/test_tray.py:LiveIconTests.test_the_icon_starts_updates_and_goes_away_cleanly` creates a real notification-area icon on Windows, updates its tooltip and requires its thread to end | Skipped off Windows. No screenshot of the icon or its menu exists anywhere in the repository. |
| The tooltip says paused / waiting / running / next check, in every language, within the tooltip limit | UNIT TESTED | `tests/test_tray.py:WordingTests` (4 tests, incl. `test_every_language_fits_the_tooltip_limit`, `test_the_countdown_is_short_and_never_negative`) | Nobody has read the tooltip in Korean on a real machine. |
| What it shows comes from this product's own store and nothing else | UNIT TESTED | `tests/test_tray.py:SnapshotTests.test_the_snapshot_comes_from_our_own_store_only` | - |
| Its menu opens the window, pauses or resumes recovery and stops the watcher, all through the same control layer | IMPLEMENTED | `src/codex_auto_resume/tray.py` | **Unverified.** No test dispatches a menu command or asserts the handlers reach the control layer. A test over the menu's command ids would be the smallest fix. |
| It is on by default and can be switched off in the settings | UNIT TESTED, for the setting | `tests/test_settings.py:DefaultsTests.test_every_field_has_a_default`, `DescribeTests.test_describes_every_field_exactly_once` | Nothing checks that switching it off actually removes the icon. |

## 9. The Codex panel and the MCP tools

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| The panel is the exact resource the plugin serves, carries everything it renders, fetches nothing, and holds no settings of its own | UNIT TESTED | `tests/test_mcp.py:WidgetTests` (11 tests, incl. `test_the_panel_fetches_nothing`, `test_the_panel_carries_no_settings_of_its_own`, `test_a_preview_seed_is_escaped`) | Never loaded by the real Codex client. |
| The published panel screenshot is the rendered markup, not a photograph of Codex | REAL WINDOWS TESTED | `assets/screenshot-panel.png` and its Korean sibling, rendered from the served markup (`<panel render:en>` and `<panel render:ko>` in `assets/screenshots.json`), checked by `tests/test_screenshots.py:ManifestTests.test_the_panel_input_is_the_rendered_markup_not_a_file_list` | **Nobody has seen the panel inside Codex.** This is the likeliest place a REAL CODEX VISUALLY TESTED row could exist, and it does not. |
| The panel speaks a sentence for every refusal it can be handed, in the language it speaks | UNIT TESTED | `tests/test_mcp.py:WidgetTests.test_the_panel_is_served_a_sentence_for_every_refusal_it_may_be_handed`, `test_only_the_refusal_helper_reads_the_english_sentence`; `PanelWordingTests` (6 tests) | - |
| Sixteen tools, each with a schema and an implementation, and the skill lists exactly those | UNIT TESTED | `tests/test_mcp.py:ToolSurfaceTests.test_every_tool_has_a_schema_and_an_implementation`, `test_the_skill_lists_every_tool_and_no_others` | - |
| No tool can send a continuation, and none accepts a conversation by anything but an exact id | UNIT TESTED | `tests/test_mcp.py:ToolSurfaceTests.test_no_tool_can_send_a_continuation`, `test_no_tool_accepts_a_thread_by_anything_but_an_exact_id`; `tests/test_control.py:NotARecoveryEngineTests` (2 tests), `BridgeTests.test_bridge_exposes_no_command_that_sends` | - |
| Pausing runs without a prompt; resuming, budget reset, start watcher and settings changes are marked destructive | UNIT TESTED | `tests/test_mcp_v3.py:ApprovalHintTests` (3 tests); `tests/test_mcp.py:ToolSurfaceTests.test_automation_can_be_reduced_freely_but_only_increased_with_approval`, `test_read_only_tools_are_marked_read_only` | **Whether Codex actually shows the prompt is checked nowhere, and cannot be from here.** The mark is a request, not a lock; nobody has recorded seeing Codex honour it. |
| `update_settings` refuses the advanced settings even from a client that ignores the schema | UNIT TESTED | `tests/test_mcp.py:ToolBehaviourTests.test_an_advanced_setting_is_refused_even_if_the_schema_is_ignored`; `ToolSurfaceTests.test_advanced_settings_are_not_offered_to_a_model`, `test_the_settings_schema_offers_no_unknown_failure_switch` | - |
| `get_status` does not carry the install path | UNIT TESTED | `tests/test_mcp.py:ToolBehaviourTests.test_status_does_not_carry_the_install_path` | - |
| The transport answers one JSON object per line, survives a malformed line, never answers a notification, and leaks no detail on an internal failure | UNIT TESTED | `tests/test_mcp.py:TransportTests` (9 tests) | Never driven by the real Codex MCP client; negotiation is tested against the test's own requests. |
| The plugin manifest declares no hooks, no environment and no network, and names only this product's own stdio server | UNIT TESTED | `tests/test_plugin.py:ManifestTests` (13 tests) | - |

## 10. The command line

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| The fourteen commands, end to end: install, enable, status, disable, pending, cancel, logs, run, stop, uninstall, doctor, activate, diagnostics, downgrade-state | UNIT TESTED | `tests/test_cli.py:CliTests` (9 tests, incl. `test_install_enable_status_disable_cycle`, `test_run_once_without_engine_fails_closed`, `test_uninstall_removes_only_owned_files`, `test_stop_without_watcher`) | - |
| `downgrade-state --to 2` produces a file the tagged v0.5.7 code opens, with every row kept | UNIT TESTED | `tests/test_downgrade.py:DowngradeTests.test_the_tagged_v0_5_7_store_opens_the_result_with_every_row` loads the store module from that git tag and opens the result with it; `test_upgrading_again_restores_a_working_v3_state` | Skipped where the tag is not in the checkout - a failure on CI, a silent skip locally. It tests the old *store module*, not the old release running. |
| `downgrade-state` refuses while the watcher runs | UNIT TESTED | `tests/test_downgrade.py:DowngradeCommandTests.test_it_refuses_while_the_watcher_runs` | - |
| `doctor` reports the protocol registration and the engine it found | UNIT TESTED | `tests/test_cli.py:DoctorProtocolCheckTests` (3 tests), `DiscoveryTests.test_discovery_requires_single_compatible_binary` | Against a fake registry. |
| The watcher loop survives a transient adapter failure and a store read failure | UNIT TESTED | `tests/test_cli.py:WatcherLoopTests` (2 tests) | - |
| Log rendering is from a fixed message table and prints Windows local time | UNIT TESTED | `tests/test_cli.py:LogbookTests` (2 tests) | - |
| The entry point runs with no `PYTHONPATH` from an unrelated directory and puts its own package first | UNIT TESTED | `tests/test_cli.py:EntryPointTests` (2 tests) | - |

## 11. Windows notifications

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| A toast is raised under this product's own identity rather than PowerShell's | UNIT TESTED, with a real capture beside it | `tests/test_notify.py:NotificationIdentityTests` (4 tests); `docs/images/notification.png` is a capture of a real Windows notification raised by this product | That image is **not** pinned by `assets/screenshots.json`, so nothing fails when it goes stale. Adding it to the manifest would fix that. |
| The toast is drawn only because a Start Menu shortcut carries the same AppUserModelID | UNVERIFIED | `src/codex_auto_resume/shortcut.py` writes that shortcut through the shell's own COM interfaces, driven from PowerShell because `System.AppUserModel.ID` needs `IPropertyStore`; its module docstring records the measurement on Windows 11 - without the shortcut the platform still accepts the toast and logs it delivered, and simply never draws it | **Nothing in the suite writes a real `.lnk`**, and every test that walks an install or uninstall patches `shortcut.install` and `shortcut.uninstall` out (`tests/test_cli.py`, `tests/test_plugin.py`, `tests/test_installer.py`). The measurement is in a docstring, not in an artifact, so a reader has this sentence and nothing else. Writing one shortcut into a temporary folder on Windows and reading the id back off it would be the smallest fix. |
| The shortcut's own values travel beside its script, never inside it | UNIT TESTED | `tests/test_pwsh.py:NoValueInScriptTests.test_the_shortcut_values_travel_out_of_band` drives `shortcut.install` with `subprocess.run` patched, decodes the `-EncodedCommand` that was handed to PowerShell and requires it to be `shortcut._MAKER` unchanged, with an install path carrying an apostrophe arriving in the environment; `test_every_pwsh_run_call_passes_a_module_constant` names `shortcut.py` as one of the two callers | No PowerShell runs and no file is written in that test. **`shortcut.uninstall` is exercised nowhere**: that it removes only our own name in our own folder, and refuses a symlink, is reviewed rather than tested. |
| A missing identity registration never stops a notification | UNIT TESTED | `tests/test_notify.py:NotificationIdentityTests.test_an_unregistered_identity_still_sends`; the class docstring records that delivery was measured working unregistered on Windows 11 | That measurement is described, not stored as an artifact. |
| No conversation content reaches a toast; at most three lines; the text is XML-escaped | UNIT TESTED | `tests/test_notify.py:ToastPayloadTests` (12 tests, incl. `test_no_conversation_content_is_disclosed`, `test_never_more_than_three_lines`, `test_the_embedded_document_is_still_valid_xml`, `test_a_quote_in_the_text_cannot_break_out_of_the_script`) | - |
| No value ever reaches PowerShell as script text | REAL WINDOWS TESTED | `tests/test_pwsh.py:RealInterpreterTests` (2 tests) run the real Windows PowerShell with hostile values; `NoValueInScriptTests` (5 tests) and `EnvironmentTests` (4 tests) pin the shape | Skipped where PowerShell is absent. |
| A failing or missing PowerShell is not an error | UNIT TESTED | `tests/test_notify.py:ToastPayloadTests.test_a_failing_or_missing_powershell_is_not_an_error` | - |
| The button only ever cancels, and a hostile or malformed URI never reaches the store | UNIT TESTED | `tests/test_notify.py:CancelUriTests` (4 tests), `ActivationTests` (3 tests) | The path from a real toast click through the real protocol handler has never been exercised. |
| Every lifecycle event has its own switch, and a master switch silences all of them | UNIT TESTED | `tests/test_notify.py:EngineNotificationTests.test_every_lifecycle_event_maps_to_a_notification_setting`, `NotificationSettingTests.test_messages_exist_in_every_language`; `tests/test_settings.py:PolicyTests.test_master_notification_switch_silences_every_event`, `test_individual_notification_events_are_independent` | - |
| An interruption is announced once however often it is seen, and a failing notification never blocks a recovery | INTEGRATION TESTED | `tests/test_notify.py:EngineNotificationTests.test_an_interruption_is_announced_once_however_often_it_is_seen`, `test_a_failing_notification_never_blocks_a_resume` | - |
| A child registered already stopped is announced as stopped only | INTEGRATION TESTED | `tests/test_outcomes.py:T48NotificationTests.test_T48_a_child_registered_exhausted_is_announced_as_stopped_only`, `test_T48_children_registered_cancelled_or_superseded_are_announced_as_stopped_only` | - |

## 12. Platform pieces

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| A single-instance mutex refuses a second watcher | REAL WINDOWS TESTED | `tests/test_engine.py:SingleInstanceTests.test_16_duplicate_watcher_process_is_refused` holds a real named mutex in a real second process and requires the App to exit busy | Skipped off Windows. The live variant, `tests/test_integration_live.py:LiveReadOnlyTests.test_single_instance_mutex_and_stop_event_roundtrip`, needs `CODEX_AR_LIVE=1` and nothing records a run. |
| The stop event wakes a waiter, and stopping is always an ask | REAL WINDOWS TESTED | `tests/test_engine.py:SingleInstanceTests.test_stop_event_wakes_waiter` uses real named events; `tests/test_control.py:StopWatcherTests.test_the_stop_is_asked_once_and_nothing_is_ever_killed` | - |
| A mutex or stop event planted by a lower-integrity process is refused, and the status reads unknown rather than running | REAL WINDOWS TESTED | `tests/test_named_objects.py:SquattedObjectTests` (5 tests) create real named objects carrying a Low integrity label and require the watcher to refuse them | Skipped off Windows. It does **not** cover a lower-integrity process opening the running watcher's own Medium-labelled mutex - SECURITY.md says so, and nothing tests it because nothing defends it. |
| The wake event lets Retry now shorten a wait | IMPLEMENTED | `src/codex_auto_resume/windows.py:WakeEvent`; the fallback where it is unavailable is covered by `tests/test_cli.py:WatcherLoopTests` | **Unverified.** No test signals a real wake event and observes a waiting watcher react. |
| The home lock keeps two processes out of one state directory | IMPLEMENTED | `src/codex_auto_resume/windows.py:HomeLock`, and `home_lock_unavailable` is a first-class refusal reason in `src/codex_auto_resume/machine.py` | **Unverified.** No test in the suite names `HomeLock` at all. |
| Sign-in start writes one value under the current user's `Run` key, is idempotent, pins the effective home, and is removable | UNIT TESTED | `tests/test_cli.py:StartupTests` (4 tests); `tests/test_plugin.py:AutostartOwnershipTests` (5 tests), `BridgeTests.test_setup_refuses_when_another_installation_owns_autostart`, `test_no_startup_never_writes_the_registry` | Against `FakeWinreg`. **No test writes a real `Run` value**, and nothing in the repository records the watcher actually starting at a Windows sign-in. A captured `logs/launcher.log` from a real sign-in would be that artifact. |
| The registered command survives a path with a space, a trailing backslash, an embedded quote, and a Unicode path | REAL WINDOWS TESTED | `tests/test_cli.py:CommandQuotingTests` (6 tests) compare against `CommandLineToArgvW` itself on Windows; `tests/test_installer_ownership.py:ArgumentQuotingTests` (6 tests) | Skipped off Windows. |
| Short-path and case spellings of the home resolve to the same installation | UNIT TESTED | `tests/test_plugin.py:ShortPathOwnershipTests` (7 tests) | - |
| The `codex-auto-resume:` protocol handler is registered per user, carries only the activate verb, and is removed only if it is ours | UNIT TESTED | `tests/test_notify.py:ProtocolRegistrationTests` (4 tests); `tests/test_cli.py:DoctorProtocolCheckTests` | Against a fake registry. **No real protocol registration, and no recorded activation from a real toast button.** |
| The watcher launcher calls system binaries by absolute path and resolves nothing through the current directory | UNIT TESTED | `tests/test_upgrade_handover.py:LauncherPathTests` (3 tests) | - |

## 13. Install, upgrade, repair, uninstall

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| The installer parses as PowerShell | REAL WINDOWS TESTED | `tests/test_installer.py:ParseTests.test_the_installer_parses_as_powershell` runs the real PowerShell parser over `install/install.ps1` | Parsing is not running. Nothing in the suite executes the installer end to end. |
| It needs no administrator rights, creates no service or scheduled task, writes no machine-wide registry, downloads nothing at install time, and uses the bundled runtime | UNIT TESTED | `tests/test_installer.py:SafetyTests` (12 tests) | Source assertions over `install/install.ps1`. A real install is never performed. |
| Program directories are moved aside rather than deleted, and a failure at either step puts the installation back | UNIT TESTED | `tests/test_installer.py:InPlaceUpgradeTests` (7 tests) | - |
| The move-aside journal is written whole before the first move, read before anything is swept, and deleted only when both trees are in place | UNIT TESTED | `tests/test_installer.py:CrashDuringTheCopyTests` (10 tests), `JournalRecoveryTests` (9 tests, incl. `test_a_tree_left_aside_by_an_interrupted_run_is_put_back`, `test_a_path_outside_the_installation_is_never_moved`, `test_a_journal_that_cannot_be_read_destroys_nothing`) | No power cut has been simulated on a real installation; the crash points are chosen by the test. |
| Only the settings window and its icon are copied to the payload root, by name, and an archive carrying anything else is refused | UNIT TESTED | `tests/test_installer.py:PayloadRootTests` (6 tests), `ArchiveContentsTests` (5 tests) | - |
| A directory is treated as an installation only on proof of ownership, and nothing outside the verified root is ever removed | UNIT TESTED | `tests/test_installer_ownership.py:InstallHomeProvenanceTests` (9), `PathConfinementTests` (7), `RemoveOwnedItemTests` (3), `InstallHomeClaimTests` (8), `InstallerDeletionRoutingTests` (4), `ProcessOwnershipTests` (2) | - |
| An upgrade runs setup with `--keep-state`, so it never re-enables recovery and never re-adds a removed sign-in start | UNIT TESTED | `tests/test_installer.py:UpgradeKeepsTheOwnersChoiceTests` (6 tests); `tests/test_plugin.py:BridgeTests.test_keep_state_neither_resumes_nor_adds_an_autostart`, `test_keep_state_repairs_an_autostart_that_is_already_ours`, `test_without_keep_state_setup_still_enables_and_registers` | Never observed across a real version-to-version upgrade. |
| The watcher is handed over before the files are replaced, through the stop event, with a bounded wait, and one left running is reported | UNIT TESTED | `tests/test_upgrade_handover.py:UpgradeHandoverTests` (6 tests) | - |
| The sign-in launcher accepts only this product's own marketplace, and otherwise starts nothing | UNIT TESTED | `tests/test_plugin.py:LauncherResolutionTests` (8 tests, incl. `test_a_same_named_plugin_from_another_marketplace_is_never_run`, `test_only_another_marketplace_means_nothing_starts`); `tests/test_convergence.py:EngineResolutionTests` (4 tests) | - |
| The bootstrap verifies before it executes, accepts only GitHub hosts, cannot be told which version to fetch, and leaves nothing behind on failure | UNIT TESTED | `tests/test_convergence.py:BootstrapTests` (7 tests), `ReleaseManifestTests` (6 tests), `HostPortabilityTests` (3 tests) | Source assertions over `scripts/bootstrap.ps1`. No download is performed in the suite. |
| The installer takes a lock before it touches anything, and an abandoned lock is taken rather than treated as contention | UNIT TESTED | `tests/test_convergence.py:InstallerLockTests` (3 tests) | - |
| Uninstall removes only what it created, aborts when the watcher state is unknown, and keeps state unless purging is asked for | UNIT TESTED | `tests/test_cli.py:UninstallSafetyTests` (6 tests); `tests/test_installer.py:UninstallKeepsStateTests` (5), `UninstallStatePreservationTests` (3) | Never run against a real installation. |
| Repair from the window | IMPLEMENTED | See §7 | Its five outcomes are unverified. |

## 14. The state store

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| Schema 3 is created and validated; a corrupt file, a newer schema or an unknown record state fails closed and is never silently reset | UNIT TESTED | `tests/test_store.py:StoreTests.test_corrupt_database_fails_without_reset`, `test_newer_schema_and_unknown_record_state_fail_closed`, `test_existing_empty_state_is_never_silently_reset`, `test_invalid_settings_fail_closed` | - |
| Migration 1 to 2 to 3 happens in one transaction, only under the watcher's mutex, with a forensic copy of the old file taken first | UNIT TESTED | `tests/test_store.py:MigrationTests` (5 tests, incl. `test_T37_open_without_migrate_is_refused_and_touches_nothing`, `test_T37_migration_preserves_every_row_and_backfills_the_chain`, `test_T19_T37_a_crash_during_migration_leaves_the_old_schema_or_the_new`) | The migration also ran once on the machine this document was written on, whose working tree holds a schema-2 forensic copy, `config/state.v2-backup-20260911T190545Z.sqlite`, beside a live schema-3 `config/state.sqlite` carrying the `events` and `watcher_status` tables. **No reader can confirm that.** `config/` is deliberately untracked (`tests/test_repo_hygiene.py:RepositoryHygieneTests.test_no_copied_runtime_state_is_tracked`), so a clone of this repository holds no trace of the run, and this sentence is the whole of the record. |
| Until the state is migrated, only the actions that reduce automation work | UNIT TESTED | `tests/test_control_v3.py:UpgradeWindowTests.test_only_what_reduces_automation_works_until_the_old_watcher_stops`, `test_a_newer_state_is_never_called_damage` | Skipped off Windows, and skipped where the v0.5.7 tag is absent from the checkout. |
| The transition table allows exactly the plain moves; the moves reserved for dedicated operations are refused to `update` | UNIT TESTED | `tests/test_store.py:TransitionTableTests` (8 tests, incl. `test_T12_nothing_possibly_sent_returns_to_waiting_by_update`, `test_T12_validator_rejects_observing_without_its_proof`) | - |
| A crash mid-write leaves the record whole or absent | UNIT TESTED | `tests/test_store.py:CrashInjectionTests` (2 tests) | The crash is injected at chosen points, not by killing a process. |
| The journal stores codes, ids, counters and times and nothing else; it is bounded at 5,000 entries and 90 days; it never drops an entry of a running recovery; event ids are never reused | UNIT TESTED | `tests/test_store.py:JournalTests` (8 tests, incl. `test_T44_pruning_keeps_the_story_of_every_record_still_running`, `test_T44_event_ids_are_never_reused`, `test_T39_a_foreign_journal_row_never_fails_an_open_or_a_read`) | - |
| Re-entering the same wait journals once; two writers of one transition journal once; a refused change journals nothing | UNIT TESTED | `tests/test_store.py:JournalTests.test_T44_re_entering_the_same_wait_journals_once`, `test_T44_two_writers_of_the_same_transition_journal_once`, `test_T44_a_refused_change_journals_nothing` | - |
| Nothing reads the journal back to decide anything | IMPLEMENTED | Decisions are made from the records; `events()` in `src/codex_auto_resume/store.py` is reached only from the control layer | **Unverified as a property.** A source-shape test, like the ones in `tests/test_control.py:NotARecoveryEngineTests`, asserting the engine never calls `events()`, would close it. |
| Statistics: buckets, medians, a rate only above five, one final outcome per record, hidden rows included | UNIT TESTED | `tests/test_store.py:StatisticsTests` (4 tests) | - |
| Settings round-trip through one validator; a corrupt or oversized file reads as defaults; no temporary file is left behind | UNIT TESTED | `tests/test_settings.py:PersistenceTests` (10 tests), `CoerceTests` (6), `ValidateUpdateTests` (5), `DescribeTests` (6) | - |
| Three interfaces write the same file through the same validator | UNIT TESTED | `tests/test_control.py:SettingsSurfaceTests` (8 tests), `BridgeTests.test_a_value_written_by_the_bridge_is_what_the_control_layer_reads`; `tests/test_mcp.py:ToolSurfaceTests.test_the_settings_schema_is_generated_from_the_shared_fields`, `test_published_bounds_match_the_validator` | - |

## 15. Privacy and safety properties

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| The recovery runtime imports no networking module; exactly one shipped file reaches the network | UNIT TESTED | `tests/test_privacy_claims.py:CodePropertyTests.test_the_recovery_runtime_imports_no_networking_module`, `test_exactly_one_shipped_file_reaches_the_network` | Covers `src/*.py` and `scripts/*.py`. **`gui/*.cs` is not covered.** |
| There is no analytics or telemetry endpoint, and the runtime disables Codex's own telemetry when it drives it | UNIT TESTED | `tests/test_privacy_claims.py:CodePropertyTests.test_there_is_no_analytics_or_telemetry_endpoint`, `test_the_runtime_disables_codex_own_telemetry_when_it_drives_it`; `tests/test_windows.py:BackendTests.test_queue_argv_exact_id_shell_disabled_and_no_telemetry` | That Codex honours the flag is not checked here, and cannot be. |
| Every history query is bounded by the marker; foreign rows are counted, never read | UNIT TESTED | `tests/test_source.py:StaticQueryTests.test_T11_content_is_marker_bounded_and_foreign_rows_are_counts` parses `src/codex_auto_resume/source.py`, takes every SQL string literal out of it and matches the marker bound with a regular expression; `test_T11_checker_catches_an_unbounded_query` proves the checker itself catches a bound that sits only in a sub-query | **The check reads the source. It opens no database and runs no query**, so a query that is wrong in a new way can pass it: a bound the regular expression happens to match, content reached through a join or a table the checker does not model, or SQL assembled from pieces rather than written as one literal. Only `source.py` is parsed, and nothing observes what a query actually returns. |
| No prompt, reply or error text reaches the log, the journal or a reply | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_log_entries_never_contain_prompt_text`; `tests/test_failures.py:DetectionGateTests.test_no_error_text_survives_detection`; `tests/test_control_v3.py:HistoryAndStatisticsTests.test_the_timeline_is_content_free`; `tests/test_control.py:StopWatcherTests.test_every_reply_is_content_free` | `errors.log` deliberately carries exception messages this product did not write. That is documented in PRIVACY.md, and redacted rather than filtered in a diagnostics bundle. |
| A label shown to a person is bounded and never multiline, and prompt-bearing columns are never read to build one | UNIT TESTED | `tests/test_failures.py:DisplayLabelTests` (2 tests), `IdentitySourceTests` (8 tests, incl. `test_prompt_bearing_columns_are_never_read`, `test_extended_length_paths_do_not_leak_the_prefix`) | - |
| Diagnostics: nothing identifying survives, aliases hold inside one file and differ between files, and it never overwrites | UNIT TESTED | `tests/test_diagnostics.py:DiagnosticsTests` (4 tests) | Run against a constructed log, not against a bundle from a real incident. |
| No shell anywhere, and no value ever reaches a script as text | REAL WINDOWS TESTED | `tests/test_pwsh.py:RealInterpreterTests` (2 tests, real PowerShell), `NoValueInScriptTests` (5 tests), `EnvironmentTests` (4 tests) | - |
| Owned paths are confined; a junction that escapes the home is refused | UNIT TESTED | `tests/test_cli.py:ConfinementTests` (3 tests); `tests/test_installer_ownership.py:PathConfinementTests` (7 tests) | - |
| No GUI automation, no mouse or keyboard simulation, no OCR, no screen scraping, no accessibility-API driving | IMPLEMENTED | Claimed in README.md; on inspection the only `user32` call in the product is `SetForegroundWindow` in `src/codex_auto_resume/tray.py`, used to bring this product's own window forward | **Unverified as a checked property.** Nothing fails if a future edit adds `SendInput`, `keybd_event` or a UI Automation import. A deny-list test alongside the networking one would make the README's claim enforced rather than reviewed. |
| The Korean documents are current, and make no claim the English ones do not | UNIT TESTED | `tests/test_korean.py:MappingTests` (6 tests, incl. `test_no_translation_is_stale`), `ClaimTests` (6 tests), `GeneratorTests` (6 tests) | - |
| Nothing in the repository names a real home directory or carries a non-synthetic UUID | UNIT TESTED | `tests/test_repo_hygiene.py:RepositoryHygieneTests` (5 tests) | - |

## 16. The build and the release

| Capability | Evidence | What backs it | What is still missing |
| --- | --- | --- | --- |
| Two builds of one source differ in exactly two PE fields, and normalising makes the executables byte-identical | REAL WINDOWS TESTED | `tests/test_reproducible.py:RealCompilerTests` (7 tests) build real executables with the in-box C# compiler and compare real PE bytes | Skipped where the compiler is absent. **One machine only** - whether GitHub's runner and another machine produce the same bytes is unverified, as `docs/VERIFY.md` states plainly. |
| The normalised program still runs, and the replacement MVID depends on the module's content | REAL WINDOWS TESTED | `tests/test_reproducible.py:RealCompilerTests.test_the_normalised_program_still_runs`, `test_the_mvid_depends_on_the_content`, `test_the_timestamp_is_the_fixed_value` | - |
| The release build normalises every executable and proves reproducibility by building twice | UNIT TESTED | `tests/test_reproducible.py:BuildScriptTests` (3 tests) | Source assertions over `build/make_gui.ps1` and the workflow; no release run is replayed. |
| Both executables carry a version resource generated from the plugin manifest | UNIT TESTED, with build outputs present | `tests/test_reproducible.py:BuildScriptTests.test_the_executables_carry_a_version_resource_from_the_manifest`; `build/CodexAutoResumeSettings.exe.VersionInfo.cs` and `build/codex-auto-resume-mcp.exe.VersionInfo.cs` are generated outputs in this tree | Nobody has recorded opening Properties, Details on a built executable and reading the values back. |
| No release published so far is reproducible | PUBLISHED, as a stated limitation | `docs/VERIFY.md`, "What a rebuild can and cannot show today": no tag up to the last release contains `build/normalize_pe.py` | The first reproducible archive will exist only once v0.6.0 is published. |
| Every external action is pinned to a full commit, named with its release, and pinned to one commit everywhere; Dependabot proposes updates | UNIT TESTED | `tests/test_workflow_pins.py:ActionPinTests` (6 tests), `ParserTests` (3 tests) | - |
| No job is granted write at the top level; the build job cannot write; the publish job runs no repository code; only a tag push publishes | UNIT TESTED | `tests/test_workflow_privilege.py:WorkflowPrivilegeTests` (8 tests), `KoSyncPrivilegeTests` (2), `YamlShapeTests` (1) | Workflow-file assertions; no run is replayed. |
| A published version's assets cannot be overwritten, and a dispatch cannot publish | UNIT TESTED | `tests/test_convergence.py:ReleaseImmutabilityTests` (5 tests) | The releases are not GitHub immutable releases; the rule binds the workflow, not everyone with write access. `docs/VERIFY.md` says so. |
| The release workflow runs the tests before publishing, refuses a tag that disagrees with the manifest, and verifies the published checksum | UNIT TESTED | `tests/test_plugin.py:ReleaseWorkflowTests` (6 tests) | - |
| The current version lives in one place, and the changelog leads with it | UNIT TESTED | `tests/test_plugin.py:VersionConsistencyTests` (4 tests), `ReleaseNotesTests` (6 tests); `tests/test_privacy_claims.py:WordingTests.test_no_released_version_has_lost_its_changelog_section` | - |
| Released archives verify by digest, by the release page, by the digest pinned on `main` and, from v0.5.4, by build attestation | PUBLISHED | `docs/VERIFY.md`; `scripts/release.json`; `tests/test_convergence.py:ReleaseManifestTests.test_every_released_version_is_pinned`, `test_digests_are_absent_or_real` | v0.6.0 has no published archive, no digest pin and no attestation, because it is not released. |
| The brand assets and the icon are generated from their sources and stay current | UNIT TESTED | `tests/test_brand.py:GeneratedFileTests` (4 tests), `PaletteTests` (4), `SurfaceTests` (6) | - |
| A live-acceptance record is refused unless it is one: a missing field, a pass that observed nothing, a raw conversation id, a path, an e-mail address, a step the validator does not know, a version that is not the manifest's, or two files disagreeing about one step | UNIT TESTED | `scripts/live_evidence.py`, driven by `tests/test_live_evidence.py:WellFormedTests` (4 tests), `RefusalTests` (19), `DirectoryTests` (10) and `DocumentTests` (7, which hold `docs/LIVE_ACCEPTANCE.md` and the validator to the same steps and the same recorded values) | The validator checks the shape of what a person wrote and the vocabulary they wrote it in. It cannot check that any of it happened, and says so itself. |
| The live acceptance itself - install, watcher, Dashboard, a real interruption, cancel, retry now, giving attempts back, pause, upgrade, repair, uninstall, each on a real machine against a real Codex | UNVERIFIED | `docs/LIVE_ACCEPTANCE.md` says for each step what it proves, what to do, what a pass looks like and what to record; `docs/evidence/live/` is where the records go | **Nobody has run it.** `docs/evidence/live/` holds a `README.md` and an `example.json` that records nothing and counts towards no step, so `python scripts/live_evidence.py` on this tree prints that nothing has been accepted yet and exits 2. Every row in this document that says a thing has never been watched in Codex is waiting on this procedure being run. |

---

## Where the evidence is thinnest

These are the capabilities this product claims that nothing in this repository exercises,
gathered so they are not lost among the rows that are well covered.

| Capability | Level | The smallest thing that would raise it |
| --- | --- | --- |
| The home lock | IMPLEMENTED | A test that opens two `HomeLock`s on one directory and requires the second to be refused. |
| The wake event | IMPLEMENTED | A test that signals a real wake event and observes a waiting watcher shorten its wait. |
| The notification-area menu's items | IMPLEMENTED | A test that dispatches each menu command id and asserts it reaches the control layer. |
| Repair in the window, all five outcomes | IMPLEMENTED | Drive `RunRepair` against a fake setup process returning each of the five conditions. |
| "Unreadable, not empty" in the window | IMPLEMENTED | A capture of the Pending page taken with the bridge made to fail. |
| Which buttons the window offers | IMPLEMENTED | A test of `UpdatePendingButtons` and `UpdateHistoryButtons` against records in each state. |
| The five-second refresh | IMPLEMENTED | Anything at all that measures it. |
| No web server, no browser, from the C# | IMPLEMENTED | Extend the `tests/test_privacy_claims.py` code-property check to `gui/*.cs`. |
| No GUI automation, ever | IMPLEMENTED | A deny-list test for `SendInput`, `keybd_event`, UI Automation and OCR. |
| Nothing reads the journal back to decide | IMPLEMENTED | A source-shape test that the engine never calls `events()`. |
| A real `Run` key at a real sign-in | UNIT TESTED, against a fake registry | A `logs/launcher.log` captured after a Windows sign-in. |
| A real protocol registration and a real toast click | UNIT TESTED, against a fake registry | The same, plus a recorded activation. |
| History, Statistics and Diagnostics pages | IMPLEMENTED | Three more captures through `build/capture_window.ps1`, added to `assets/screenshots.json`. |
| The Start Menu shortcut, and the toast identity that depends on it | UNVERIFIED | Write one `.lnk` into a temporary folder on Windows and read the AppUserModelID back off it. |
| The live acceptance procedure | UNVERIFIED | Somebody runs `docs/LIVE_ACCEPTANCE.md` on a real machine and commits the files it produces under `docs/evidence/live/`. |
| Anything at all seen inside Codex | - | Nobody has watched this product work in Codex. Until somebody does and the repository records it, no row here can say REAL CODEX VISUALLY TESTED. |

## What a reader should take from this

The recovery engine is the best-evidenced part. Its detection, its gates, its correlation,
its outcomes and its budgets are driven end to end against a real Codex-shaped database
through the production query layer, and the three facts the whole design rests on - the
usage-limit shape, delivery to a loaded conversation, non-delivery to an unloaded one -
were measured against real Codex on 2026-09-06 and are published under `docs/evidence/`.

The surfaces are the weakest. The window's six pages are real code with three captures
between them; the notification-area icon is created and destroyed for real exactly once, in
one test, with no picture of it anywhere; the Codex panel has never been loaded by Codex.
Where a surface talks to the control layer, the control layer is well tested and the
surface's own half usually is not.

And nothing here has been watched. That is the honest summary: a carefully tested program
that, as far as this repository records, nobody has yet sat and watched recover a
conversation.
