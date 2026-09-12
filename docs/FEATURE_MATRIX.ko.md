# 기능과 근거 대조표

> 🌐 한국어 문서입니다. English version: [`main` 브랜치의 docs/FEATURE_MATRIX.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/FEATURE_MATRIX.md)

이 제품이 한다고 말하는 모든 것을, 실제로 확보한 근거 등급과 그 등급을 뒷받침하는 인용과 함께
적어 둡니다. 세 번째 칸은 주장이 확인 가능하도록 만드는 것이고, 네 번째 칸이 이 문서의 목적입니다.
가장 강한 근거가 단위 테스트뿐인 항목과, 사람이 직접 동작하는 것을 본 항목은 같은 제품이 아니기
때문입니다.

## 근거 어휘

아래 등급은 이 프로젝트가 쓰는 어휘이고, 하나하나가 정해진 뜻을 가집니다. 약한 것부터 강한 순서로
적었으며, 각 항목은 저장소 안에 실제로 뒷받침하는 것이 있는 가장 강한 등급만 주장합니다.

| 등급 | 뜻 |
| --- | --- |
| UNVERIFIED | 아래 어느 것도 아님. |
| IMPLEMENTED | 코드가 있고 검토를 거쳤음. 그 코드를 실행해 확인하는 것은 없음. |
| UNIT TESTED | 테스트가 그 단위를 홀로 구동함. 주변은 대개 가짜로 대체됨. |
| INTEGRATION TESTED | 테스트가 진짜 상태 저장소, 진짜 소스, 진짜 엔진을 함께 구동함. `tests/codexsim.py`는 Codex가 직접 쓰는 표와 열을 그대로 가진 진짜 Codex 모양의 SQLite 홈을 만들고, 기록과 대기열 읽기는 모두 제품이 쓰는 질의 계층을 지나갑니다. 그래서 실제 스키마에 대해 틀린 질의는 여기서도 실패합니다. 질의 계층을 흉내 낸 것이 아닙니다. |
| REAL WINDOWS TESTED | 테스트 스위트의 평범한 논리 바깥에서, 진짜 Windows 기능을 써서 실행했음. 컴파일된 실행 파일, 진짜 이름 있는 뮤텍스, 진짜 레지스트리 파서, 진짜 PowerShell 프로세스, 캡처된 스크린샷. |
| REAL CODEX PROTOCOL TESTED | 실제 Codex 데스크톱 앱의 데이터베이스나 CLI를 상대로 시험했고, 그 결과가 `docs/evidence/` 아래에 기록되어 있음. |
| REAL CODEX VISUALLY TESTED | 사람이 Codex 안에서 그 일이 일어나는 것을 지켜봤음. |
| PUBLISHED | 공개된 릴리스에 들어 있음. |

## 이 문서가 무엇이고, 무엇이 아닌지

- **이 문서는 저장소를 읽고 씁니다.** 모든 인용은 이 나무 안에 실제로 있는 것입니다. 테스트 모듈과
  테스트 이름, `assets/`나 `docs/images/` 아래의 산출물, `docs/evidence/` 아래에 기록된 관측,
  또는 빌드 산출물입니다. 커밋 메시지를 읽거나 지난 작업을 기억해서 적은 것은 하나도 없습니다.
- **항목이 그렇다고 말하지 않는 한, 실제 Codex 대화를 상대로 제품을 돌려서 확인한 것은 없습니다.**
  REAL CODEX PROTOCOL TESTED를 다는 항목은 다섯 개이고, 다섯 모두 `docs/evidence/` 아래에 있는
  2026-09-06 측정, 그것도 버려도 되는 시험용 대화를 상대로 한 측정에 기대고 있습니다. 복구에 관한
  나머지 전부 - 정확한 턴 대응, 결과 판정, 연쇄, 예산, 사용량 만료 - 는 `tests/codexsim.py`를 상대로만
  구동되었습니다.
- **REAL CODEX VISUALLY TESTED를 다는 항목은 하나도 없습니다.** 사람이 Codex 안에서 복구가 일어나는
  것을 지켜봤다는 기록이 이 저장소에는 없습니다. 2026-09-06 전달 확인은 데스크톱 앱 자신의 작업 조회와
  그 대화의 로컬 기록·대기열로 확인한 것이고,
  [`docs/evidence/unloaded-thread-observation.json`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/evidence/unloaded-thread-observation.json)에
  `visual_ui_scraping_used: false`로 적혀 있습니다. 프로토콜 관측이지, 누가 지켜본 것이 아닙니다.
- **이번 릴리스는 공개되었습니다.** 압축 파일이 발행되었고, 그 해시가 `main`에 고정되었으며,
  아래에서 PUBLISHED라고 적힌 항목들은 그것을 뜻합니다. 이 문서 어디에서도 PUBLISHED가 뜻하지
  *않는* 것은, 누군가 그것을 설치해서 써 보았다는 것입니다. 발행된 바이트는 그 확인만을 위해 만든
  상태 폴더와 Codex 홈을 상대로 구동했고, 설치 프로그램의 등록은 하나도 돌리지 않았으며, 실제
  Codex 상태를 상대로 워처를 띄우지도 않았습니다. 누군가 쓰는 기계에서 설치하고 올리고 지우는
  일은 [LIVE_ACCEPTANCE.ko.md](LIVE_ACCEPTANCE.ko.md)가 맡고 있고, 아무도 돌려 보지
  않았습니다.
- **REAL WINDOWS TESTED 항목은 대개 진짜 Windows 기능이 필요한 스위트 안의 테스트를 뜻하고**,
  그런 테스트는 기능이 없으면 스스로 건너뜁니다. 건너뛴 테스트는 아무것도 증명하지 않으므로,
  건너뛸 가능성이 있는 곳은 네 번째 칸에 적었습니다.

  기록해 둔다. 2026-09-13, 릴리스가 공개된 뒤 이 문서를 쓴 Windows 11 기계에서
  `PYTHONPATH="src;tests" python -m unittest discover -s tests`가 **1230개를 300초에 돌렸고,
  실패는 없고 일곱 개를 건너뛰었다**. 일곱 중 여섯은 `tests/test_integration_live.py`의 선택 참여
  라이브 검사이며, `CODEX_AR_LIVE=1` 없이는 돌지 않겠다고 스스로 물러난 것이다. 나머지 하나는
  `tests/test_workflow_privilege.py:YamlShapeTests.test_every_workflow_parses`로, PyYAML이
  필요한데 여기에는 깔려 있지 않다. 그 파일들은 푸시할 때마다 GitHub이 어차피 파싱한다. 아래
  REAL WINDOWS TESTED 줄은 모두 여기서 실제로 돌았고, 실제 Codex 설치에 닿을 검사는 하나도 돌지
  않았다.

  이 문서의 앞선 초고는 1140개짜리 빨간 실행을 적어 두었다. 그 두 실패는 한국어 가지 관리였고,
  짝이 매핑되지 않은 것과 번역 지문 셋이 낡은 것이었으며 둘 다 제품에 닿지 않았다. 둘 다 고쳤다.
  그 초고가 잡지 못한 것 하나는 남겨 둘 만하다. 그 실행은 쓴 기계에서는 초록이고 CI에서는
  빨갰는데, 두 줄이 생성되고 git이 무시하는 빌드 산출물을 인용했기 때문이다. 실행 파일을 빌드해
  본 사람에게는 있고 새로 받은 사본에는 없는 파일이다. 이제 `tests/test_feature_matrix.py`는
  인용된 경로를 기계가 가지고 있는지가 아니라 저장소가 싣고 있는지를 묻는다.

## 인용 읽는 법

`tests/test_engine.py:GateTests.test_T47_a_subagent_or_non_desktop_thread_is_never_detected`는
모듈, 클래스, 테스트 순서입니다. 한 클래스의 여러 테스트가 한 항목을 뒷받침할 때는 모든 이름을
적는 대신 클래스 이름과 개수를 적었습니다. 산출물은 경로로 적습니다.

---

## 1. 감지와 분류

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 사용량 한도를 Codex 자신의 턴 행(`status=failed`, `codexErrorInfo=usageLimitExceeded`)에서 읽는다 | REAL CODEX PROTOCOL TESTED | 2026-09-06에 실제 Codex 데이터베이스에서 읽기 전용으로 담은 `docs/evidence/usage-limit-sample.json`. `tests/test_source.py:DetectionTests.test_real_usage_sample`이 감지를 돌리는 대상은 그 캡처가 아니라 `tests/fixtures/usage-limit.json`이다. 캡처를 정제해 만든 사본이고, id도 필드 이름도 캡처와 다르다 | 한 번의 캡처, 한 계정, 한 Codex 빌드. 더 새로운 Codex에 대해 모양을 다시 확인하는 것은 없고, **스위트 안의 어떤 테스트도 `docs/evidence/usage-limit-sample.json`을 읽지 않으므로**, 픽스처가 그 캡처에서 멀어져도 아무것도 알려 주지 않는다. |
| 재개 시각은 메시지 문구가 아니라 실패 직전의 사용량 스냅숏에서 가져온다 | REAL CODEX PROTOCOL TESTED | 같은 캡처가 UI가 보여 준 "try again at" 문구 옆에 `resets_at`를 기록하고 있고, `contains_machine_readable_reset_in_error: false`도 함께 있음. `tests/test_source.py:DetectionTests.test_real_reset_and_timezone`은 픽스처 자신의 사용량 행에서 재개 시각을 고르고 픽스처 자신이 적어 둔 기댓값과 맞춰 보며, `test_low_usage_hint_is_not_adopted_as_reset`은 테스트 안에 적은 값으로만 돈다 | 지금 Codex에서도 둘이 일치하는지 확인하는 것은 없고, 픽스처를 공개된 캡처와 다시 맞춰 보는 것도 없다. |
| 실패한 턴의 롤아웃 사건 이름은 `task_complete`인데도 오류를 그대로 싣고 있으므로, 사건 이름을 성공으로 읽는 일은 없다 | REAL CODEX PROTOCOL TESTED | `docs/evidence/usage-limit-sample.json`(`rollout_failure.payload_type: task_complete`); `tests/test_source.py:LocalSourceTests.test_detect_actual_shape`는 캡처가 아니라 픽스처가 들고 있는 롤아웃 사건으로 손수 만든 Codex 홈에서 그 실패를 감지한다 | 같은 캡처 하나뿐이고, 픽스처를 그 캡처와 다시 맞춰 보는 것도 없다. |
| 일시적 실패를 분류하고 별도 정책으로 복구한다 | INTEGRATION TESTED | `tests/test_failures.py:TransientTests`(3개); `tests/test_recovery.py:PolicySeparationTests.test_a_transient_failure_waits_on_backoff_not_on_a_reset` | 실제 Codex의 일시적 실패를 관측한 기록이 없다. 코드는 스키마에서 온 것이지 캡처에서 온 것이 아니다. |
| 영구적 실패는 절대 재시도하지 않는다 | UNIT TESTED | `tests/test_failures.py:TerminalTests`(3개, `test_authentication_is_terminal_not_a_retry_budget` 포함); `tests/test_recovery.py:UnknownNeverRetriedTests.test_a_terminal_failure_is_never_registered` | 어느 영구 실패 코드도 실제 사례를 담아 둔 것이 없다. |
| 분류하지 못한 실패는 기록조차 하지 않고 재시도도 하지 않는다 | INTEGRATION TESTED | `tests/test_failures.py:UnknownTests`(6개), `DetectionGateTests.test_only_recoverable_categories_are_ever_registered`; `tests/test_recovery.py:UnknownNeverRetriedTests.test_an_unclassified_failure_is_never_registered` | - |
| Codex 자신이 포기한 요청 제한(`429`, 시도 과다)은 최소 1분을 기다린다 | INTEGRATION TESTED | `tests/test_outcomes.py:T27RateLimitTests`(3개); `tests/test_recovery.py:PolicySeparationTests.test_T27_a_rate_limit_codex_gave_up_on_waits_at_least_a_minute` | 실제 429에 대해 관측한 적이 없다. |
| 정확한 대화 UUID만 다루며 `--last`는 쓰지 않는다 | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_18_one_thread_failure_never_resumes_another`; `tests/test_windows.py:BackendTests.test_queue_argv_exact_id_shell_disabled_and_no_telemetry`, `test_invalid_thread_id_never_launches` | - |
| 하위 에이전트·보관된 대화·데스크톱이 아닌 대화는 감지하지 않는다 | INTEGRATION TESTED | `tests/test_source.py:ChildThreadTests`(3개, `test_T47_state_row_and_rollout_must_both_say_user` 포함); `tests/test_engine.py:GateTests.test_T47_a_subagent_or_non_desktop_thread_is_never_detected` | 출처 값이 모의 홈에서 온 것이다. 실제 하위 에이전트 대화를 담은 캡처는 없다. |
| 조회 기간보다 오래된 실패는 나중에 감지되지 않는다 | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_12b_disabled_at_failure_time_is_not_detected_later_beyond_lookback`; `tests/test_source.py:LocalSourceTests.test_ignore_historic_failure` | - |
| 감지 단계에서 오류 문구를 남기지 않는다 | UNIT TESTED | `tests/test_failures.py:DetectionGateTests.test_no_error_text_survives_detection` | - |

## 2. 관문

모든 전송은 정해진 관문 묶음을 통과합니다. 거절한 관문은 기록으로 남고, 레코드의 상태 안에
섞여 들어가지 않습니다.

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 승인된 예약에는 관문 벡터가 함께 기록되고, 거절은 아무 전이도 만들지 않는다 | INTEGRATION TESTED | `tests/test_outcomes.py:T31GateEvalTests.test_T31_the_gate_vector_is_written_on_a_granted_claim`, `test_T31_a_refused_claim_writes_consent_block_and_makes_no_transition` | - |
| 자동 복구 일시 정지는 즉시 듣는 차단 스위치이며 대기 중인 것을 보존한다 | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_12_global_disable_is_immediate_kill_switch`; `tests/test_control.py:StatusTests.test_pause_preserves_pending_records` | - |
| 꺼 둔 대화는 절대 대기열에 넣지 않고, 다른 대화는 영향을 받지 않는다 | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_13_thread_disabled_never_queues_but_other_thread_does`; `tests/test_outcomes.py:T31GateEvalTests.test_T31_a_due_record_on_a_disabled_thread_records_consent_block` | - |
| 실제 재개 시각 전에는 아무것도 보내지 않는다 | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_07_before_reset_never_queues`, `GateTests.test_T31_a_future_reset_is_a_wait_with_a_reason` | - |
| 데스크톱 앱이 닫혀 있거나, 대화가 열려 있지 않거나, 열림 여부를 알 수 없으면 보내지 않는다 | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_09_after_reset_not_loaded_waits`, `test_11_app_closed_never_queues`, `test_unknown_loaded_state_never_queues` | 이 관문은 아래의 관측 때문에 존재하지만, 관문 자체가 실제로 닫혀 있는 대화를 상대로 돈 적은 없다. |
| 열려 있지 않은 대화에 넣은 메시지는 턴으로 전달되지 않는다 - 이 관문의 근거가 된 관측 | REAL CODEX PROTOCOL TESTED | `docs/evidence/unloaded-thread-delivery.json`(실제 앱 재시작 후 90초 관측, 판정 FAIL)와 `docs/evidence/unloaded-thread-observation.json` | 90초 한 번, Codex 빌드 하나. Codex가 나중에 전달할 수는 있고, 증거 파일과 README가 그렇게 적고 있다. |
| 열려 있는 대화에 넣은 메시지는 바로 그 대화로 전달된다 | REAL CODEX PROTOCOL TESTED | `docs/evidence/loaded-thread-delivery.json`(`same_thread_user_message_confirmed`, `same_thread_agent_message_confirmed`, `pending_test_items_after_delivery: 0`) | 앱의 작업 조회와 로컬 기록으로 확인한 것이지 사람이 본 것이 아니다. 대화 하나, 실행 한 번, 2026-09-06. |
| 열림 여부는 다시 시작 관리자로 판정하며, 앱의 쓰기 잠금은 절대 잡지 않는다 | UNIT TESTED | `tests/test_windows.py:BackendTests`, 그 클래스의 열림 판정 테스트 여덟 개(`test_tool_never_acquires_the_apps_writer_lock`, `test_pid_reuse_fails_closed`, `test_ambiguous_resource_users_fail_closed` 포함) | 판정기가 가짜 다시 시작 관리자 출력을 상대로 돈다. 실제로 확인하는 `tests/test_integration_live.py:LiveReadOnlyTests.test_loaded_state_classification_of_existing_locks`는 `CODEX_AR_LIVE=1` 없이 건너뛰는 여섯 중 하나이고, 실행 기록이 없다. |
| 보내기 직전에 사용량을 다시 확인하고, 확인할 수 없으면 기다린다 | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_15d_usage_still_unavailable_does_not_queue`; `tests/test_windows.py:UsageTests`(9개, `test_missing_or_malformed_safe_unknown`, `test_private_response_fields_are_discarded` 포함) | 실제 조회는 선택형 라이브 점검에서만 돌고, 그 실행 기록이 없다. |
| 롤아웃보다 뒤처진 기록 투영은 전송을 막는다 | INTEGRATION TESTED | `tests/test_outcomes.py:T32ProjectionTests`(5개); `tests/test_source.py:LocalSourceTests.test_projection_fresh_when_caught_up`, `test_projection_not_fresh_when_the_rollout_grew` | 지연 기준값은 정한 것이지, 부하가 걸린 실제 Codex에서 재 본 것이 아니다. |
| 투영 표가 아예 없으면 통과 대신 비호환으로 막는다 | INTEGRATION TESTED | `tests/test_outcomes.py:T32ProjectionTests.test_T32_a_missing_projection_table_blocks_as_incompatible`; `tests/test_engine.py:GateTests.test_T32_a_missing_projection_table_blocks_compatibility` | - |
| 대화 하나당 전송은 한 번에 하나, 그리고 재전송 간격과 하루 상한 | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_thread_cooldown_and_daily_cap`, `test_15e_a_launch_retry_still_respects_the_thread_cooldown` | - |
| 한 상태 파일 위의 엔진 둘이 한 번만 보낸다 | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_16_two_engines_on_same_state_send_once` | 한 프로세스 안의 엔진 둘이 한 파일을 상대로 경쟁하는 것이지, 진짜 워처 프로세스 둘이 경쟁하는 것은 아니다. |
| 같은 중단을 두 번 이어가는 일은, 크래시나 워처 재시작을 건너서도 없다 | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_crash_after_reserve_before_send_never_resends`, `test_15b_unknown_send_outcome_is_never_resent`, `test_14_watcher_restart_preserves_pending`; `tests/test_store.py:StoreTests.test_reserved_interruption_survives_crash_as_submitting`, `test_unknown_submission_can_resolve_but_never_retry` | - |
| 정책 설정은 안전 관문에 손댈 수 없다 | UNIT TESTED | `tests/test_engine.py:PolicyTests.test_policy_cannot_reach_a_safety_gate`, `test_no_setting_names_an_engine_safety_option`; `tests/test_settings.py:DefaultsTests.test_no_setting_can_enable_recovery_of_an_unknown_failure` | - |

## 3. 정확한 턴 대응

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 이어가는 메시지는 그 중단의 id로 만든 표지를 싣고, 복구 턴은 그 표지가 있는 행의 턴이다 - 가장 최근 턴이 아니다 | INTEGRATION TESTED | `tests/test_correlation.py:CorrelationTest.test_T01_recovery_turn_is_the_marker_rows_turn_even_after_a_later_user_turn`; `tests/test_engine.py:CorrelationTests.test_T01_the_recovery_turn_survives_a_watcher_restart`; `tests/test_source.py:LocalSourceTests.test_marker_rows_report_their_own_turn_not_the_latest` | 실제 Codex가 쓴 표지를 상대로 대응시켜 본 적이 없다. 모의 환경의 표지 행은 모의 환경이 쓴 것이다. |
| 엔진에는 "가장 최근 턴"을 물을 방법 자체가 없다 | UNIT TESTED | `tests/test_source.py:StaticQueryTests.test_T01_latest_turn_id_is_gone`; `tests/test_engine.py:CorrelationTests.test_T01_latest_turn_id_is_gone_from_the_source`. 둘 다 `src/` 아래 파일을 읽어 `latest_turn_id`라는 이름이 없다는 것만 요구하고, 질의를 돌리지는 않는다 | 확인되는 것은 그 철자 하나가 사라졌다는 것이지 기능이 사라졌다는 것이 아니다. 이름만 바꾼 채 여전히 가장 최근 턴을 돌려주는 함수는 둘 다 통과한다. |
| 표지 행이 둘이면 대응시키지 않고 모호한 채로 두며, 우리가 넣은 행은 그래도 되찾는다 | INTEGRATION TESTED | `tests/test_correlation.py:CorrelationTest.test_T02a_two_marker_rows_are_never_correlated`, `test_T02a_two_marker_rows_still_withdraw_our_queued_row` | - |
| 클라이언트 id가 다르거나, 실패한 턴과 같거나 그보다 앞선 표지는 모호로 본다 | INTEGRATION TESTED | `tests/test_correlation.py:CorrelationTest.test_T02c_different_client_id_is_an_ambiguous_receipt`, `test_T02e_marker_at_or_below_the_failed_ordinal_is_ambiguous`, `test_T02d_null_client_ids_leave_the_marker_rules_alone` | 클라이언트 id 열의 실제 값은 Codex 빌드 하나에서 온 것이다. |
| 다른 사람의 턴으로 들어간 표지는 넘겨준 것으로 처리하고 우리 것이라 주장하지 않는다 | INTEGRATION TESTED | `tests/test_correlation.py:CorrelationTest.test_T02b_marker_steered_into_someone_elses_turn_is_handed_over` | - |
| 하나의 Codex 턴은 많아야 하나의 레코드에만 속한다 | UNIT TESTED | `tests/test_store.py:TransitionTableTests.test_T12_a_recovery_turn_is_written_once`(고유 색인) | - |
| 판정되지 않은 턴은 대기열 행을 지울 이유가 되지 않고, 취소나 일시 정지를 붙잡지도 않는다 | INTEGRATION TESTED | `tests/test_correlation.py:WatchTest.test_T03_undetermined_turn_is_never_a_reason_to_delete`, `test_T03_an_undetermined_turn_never_holds_back_a_cancel_or_a_pause` | - |
| 예약과 전송 사이에 상황이 바뀌면 예약을 놓아 주고, 그 사이에는 아무것도 알리지 않는다 | INTEGRATION TESTED | `tests/test_correlation.py:WatchTest.test_T08_change_between_reserve_and_send_releases_the_claim`, `test_T08_no_notification_between_claim_and_send`; `tests/test_outcomes.py:T48NotificationTests.test_T48_nothing_is_announced_between_the_claim_and_the_send` | - |
| 우리 것 앞이나 뒤에 남의 항목이 들어오면 기다리거나 우리 것을 되찾는다 | INTEGRATION TESTED | `tests/test_correlation.py:WatchTest.test_T09_foreign_queued_input_makes_the_record_wait`, `test_T09_foreign_item_queued_while_ours_is_queued_withdraws_ours` | - |
| 대기열에서 편집된 항목은 삭제 없이 넘겨준 것으로 처리한다 | INTEGRATION TESTED | `tests/test_correlation.py:WatchTest.test_T10_edited_queued_item_is_handed_over_without_a_delete` | 편집은 대기열 행을 고쳐 쓰는 것으로 흉내 낸다. Codex에서 실제로 편집해 보고 결과를 지켜본 사람은 없다. |
| 이미 Codex 안에 있는 표지를 만나면 예약을 중복 소유로 놓아 준다 | INTEGRATION TESTED | `tests/test_engine.py:CorrelationTests.test_T45_a_marker_already_in_codex_releases_the_claim_as_a_duplicate_owner` | - |

## 4. 결과 판정

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 결과는 대응시킨 그 턴에서만 읽는다 | INTEGRATION TESTED | `tests/test_outcomes.py:T13OutcomeRulesTests`(6개); `tests/test_engine.py:OutcomeTests`(11개) | - |
| 끝나지 않는 턴은 마감 시각에 확인 불가가 된다 - 성공이 되는 일은 없다 | INTEGRATION TESTED | `tests/test_outcomes.py:T13OutcomeRulesTests.test_T13_a_row_that_stays_in_progress_becomes_unverified_at_the_deadline`, `test_T13_a_later_terminal_turn_proves_an_in_progress_row_stale` | - |
| 읽을 수 없는 기록은 마감까지 다시 시도하며, "진전 없음"이 되지 않는다 | INTEGRATION TESTED | `tests/test_outcomes.py:T13OutcomeRulesTests.test_T13_unreadable_history_is_retried_then_hits_the_deadline_never_no_progress`, `test_T13_history_that_becomes_readable_again_is_evaluated_normally` | - |
| 중간에 끊긴 복구 턴은 "사용자가 중단함"이다 | INTEGRATION TESTED | `tests/test_outcomes.py:T13OutcomeRulesTests.test_T13_an_interrupted_recovery_turn_is_stopped_by_the_user` | 상태 문자열은 스키마에서 온 것이고, 실제 사용자 중단을 담은 캡처는 없다. |
| 아무것도 내놓지 않고 끝난 턴은 "진전 없음"이며, 연쇄 안에서도 그렇다 | INTEGRATION TESTED | `tests/test_outcomes.py:T15NoProgressTests`(2개) | - |
| 사람이 그 턴에 끼어들면 즉시 넘겨준 것이 되고, 그 자식은 예약되지 않고 밀려난 것이 된다 | INTEGRATION TESTED | `tests/test_outcomes.py:T16UserJoinedTests`(3개) | - |
| 그 턴의 항목이 투영되기 전에는 판정하지 않고, 늦게 처음 본 종료 상태도 한 번 더 기다린다 | INTEGRATION TESTED | `tests/test_outcomes.py:T14SettleTests`(2개); `tests/test_engine.py:OutcomeTests.test_T14_a_turn_first_seen_long_after_it_finished_still_waits_one_tick` | - |
| 진전 여부는 내용을 전혀 읽지 않고 판정한다 | INTEGRATION TESTED | `tests/test_recovery.py:NoProgressTests.test_progress_is_decided_without_reading_any_content`; `tests/test_source.py:LocalSourceTests.test_turn_observation_progress_only_known_types_in_that_turn` | - |
| 관찰 중에 멈춰 버린 레코드가 더 새로운 실패를 막지 않는다 | INTEGRATION TESTED | `tests/test_outcomes.py:T17StuckObservingTests`(2개) | - |
| 결과를 알 수 없다고 한 뒤에 뒤늦게 전달된 것도 알린다 | INTEGRATION TESTED | `tests/test_outcomes.py:T48NotificationTests.test_T48_a_late_delivery_after_an_unknown_result_is_announced`; `tests/test_engine.py:OutcomeTests.test_T48_a_late_delivery_after_an_unknown_result_is_announced` | - |

## 5. 예산, 연쇄, 사용량 만료

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 우리 복구 턴이 실패하면 새 연쇄를 시작하지 않고 부모의 연쇄를 잇는다 | INTEGRATION TESTED | `tests/test_outcomes.py:T18ChainTests`(5개); `tests/test_recovery.py:ChainTests`(6개) | - |
| 자식은 자신을 만드는 하나의 트랜잭션 안에서 모든 계수기를 물려받는다 | UNIT TESTED | `tests/test_store.py:CrashInjectionTests.test_T19_register_with_a_parent_is_all_or_nothing`; `tests/test_store.py:StoreTests.test_every_record_belongs_to_a_chain` | - |
| 취소되었거나, 사람에게 넘어갔거나, 예산을 다 쓴 부모의 자식은 이미 멈춘 채로 태어난다 | INTEGRATION TESTED | `tests/test_outcomes.py:T20LineageTests`(2개); `tests/test_recovery.py:ChainTests.test_T20_a_cancelled_parent_stops_its_child_before_its_own_outcome`; `tests/test_store.py:CancelTests.test_T21_nothing_running_reports_no_change_but_blocks_a_future_child` | - |
| 한 작업에 기본 여섯 번까지 이어가며, 설정은 1에서 10까지만 받는다 | UNIT TESTED | `tests/test_engine.py:PolicyTests.test_the_chain_cap_can_be_lowered_but_never_raised_past_ten`, `test_the_attempt_budget_comes_from_the_settings`; `tests/test_settings.py:DescribeTests.test_published_ranges_accept_their_own_bounds` | - |
| 시도 예산은 레코드를 건너서도, 재시작을 건너서도 유지된다 | INTEGRATION TESTED | `tests/test_recovery.py:BudgetTests`(3개, `test_attempts_persist_across_a_restart` 포함) | - |
| 사용량 연쇄는 시도 예산과 무관하게 이어가기 상한에서 멈춘다 | INTEGRATION TESTED | `tests/test_outcomes.py:T18ChainTests.test_T18_a_usage_chain_stops_at_the_chain_cap_whatever_the_attempt_budget` | - |
| 사용량이 없던 시간은 연쇄를 따라 누적되어 7일에서 만료된다 | INTEGRATION TESTED | `tests/test_outcomes.py:T28UsageExpiryTests`(4개); `tests/test_engine.py:GateTests.test_T28_the_never_available_limit_is_seven_days`, `test_T28_only_unavailable_time_between_probes_accumulates` | 실제 시계로 7일이 흐르는 동안의 동작은 관측된 적이 없다. 시계는 테스트의 것이다. |
| 주간 한도는 자기 재개 시각에 하루를 더하기 전에는 만료되지 않는다 | INTEGRATION TESTED | `tests/test_outcomes.py:T28UsageExpiryTests.test_T28_a_weekly_reset_never_expires_before_reset_plus_a_day`; `tests/test_engine.py:GateTests.test_T28_a_weekly_limit_never_expires_before_its_reset` | - |
| 시도를 되돌려 주는 것은 한 작업에 세 번까지이고, 연쇄에 속하며, 소진된 두 상태만 되살리고, 아무것도 보내지 않는다 | UNIT TESTED | `tests/test_store.py:RestoreBudgetTests`(13개, `test_T26_the_fourth_reset_of_a_record_is_refused`, `test_T26_the_reset_count_belongs_to_the_chain`, `test_does_not_submit`, `test_never_reactivates_something_that_may_have_been_sent` 포함) | - |
| 되돌려 준 레코드는 자기 실패 종류에 맞는 기다림으로 돌아가고, 꺼 둔 대화는 꺼 둔 채로 남는다 | UNIT TESTED | `tests/test_store.py:RestoreBudgetTests.test_T26_usage_record_returns_to_its_reset_wait_and_transient_to_backoff`; `tests/test_control.py:BudgetTests.test_reset_returns_a_record_to_the_wait_its_kind_of_failure_needs`, `test_reset_leaves_a_switched_off_conversation_off` | - |
| 지금 다시 확인은 일정만 앞당긴다. 보내지 않고, 관문을 건너뛰지 않고, 사용량 창을 열지 않는다 | UNIT TESTED | `tests/test_store.py:RetryNowTests`(3개); `tests/test_control.py:RetryNowTests`(4개); `tests/test_control_v3.py:RetryNowTests`(2개); `tests/test_mcp.py:ToolBehaviourTests.test_retry_now_does_not_submit`, `test_retry_now_says_the_checks_still_apply` | - |
| 지금 다시 확인이 워처를 깨운다 | REAL WINDOWS TESTED | `tests/test_surface_properties.py:WakeEventTests`(4개)가 두 번째 프로세스에서 진짜 이름 있는 이벤트를 쥐고 2분을 기다리게 한 뒤 이쪽에서 신호를 보내, 기다림이 30초에 한참 못 미쳐 그 이벤트로 끝나기를 요구한다. 기다리는 쪽이 없으면 거짓을 답하는 것, 한 상태 디렉터리의 이벤트가 다른 쪽에 닿지 않는 것, 이벤트가 없는 대체 경로도 헛돌지 않고 자는 것도 함께 요구한다. 제어 계층은 깨울 것이 있었는지 답하고, `tests/test_control_v3.py:RetryNowTests`가 "깨울 워처가 없음" 답을 덮는다 | 기다리는 쪽이 진짜 워처가 아니라 시험용 프로세스라, 보인 것은 기다림이 끝난다는 것이다. 그 뒤에 도는 점검이 모든 것을 다시 따진다는 것은 `tests/test_engine.py`의 몫이다. |
| 취소는 그 작업의 모든 레코드에 닿고 다른 것에는 닿지 않으며, 쓰기 잠금 아래에서는 거절 대신 다시 시도한다 | UNIT TESTED | `tests/test_store.py:CancelTests`(3개); `tests/test_control_v3.py:ChainCancelTests`(2개); `tests/test_outcomes.py:T23CancelContentionTests`(2개, `test_T23_cancel_succeeds_by_retrying_under_a_12_second_write_lock` 포함) | - |
| 전송과 경쟁한 취소는 레코드에 표시를 남기고, 감시가 그것을 되찾는다 | INTEGRATION TESTED | `tests/test_outcomes.py:T22CancelRaceTests`(2개); `tests/test_engine.py:PauseAndCancelTests.test_T22_cancel_racing_the_send_marks_and_the_watch_withdraws` | 이미 Codex에서 돌고 있는 턴은 멈추지 않는다는 것은 문서에 적힌 사실이고, Codex를 상대로 관측된 것은 아니다. |
| 일시 정지는 대기열의 이어가기를 되찾아 레코드를 기다림으로 돌려놓고, 기록이 뒤처진 상태에서 되찾은 것은 절대 풀어 주지 않는다 | INTEGRATION TESTED | `tests/test_outcomes.py:T24PauseTests`(5개), `T25PausedWatchTests`(4개); `tests/test_pause_unknown.py:PausedUnknownTests.test_a_pause_withdraws_it_and_it_ends_final` | 되찾기는 모의된 App Server 삭제이고, 실제 되찾기를 재 본 적은 없다. |

## 6. 공개 어휘

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 저장 상태 27개가 공개 코드 22개로, 설계 표 그대로 대응된다 | UNIT TESTED | `tests/test_outcomes.py:T29T30PublicCodeTests.test_T29_there_are_twenty_seven_stored_states`, `test_T29_T30_every_stored_record_maps_as_the_design_table_says`, `test_T29_every_stored_failed_is_failed_terminal`; `tests/test_labels_v3.py:LabelTests.test_every_stored_state_maps_to_a_public_code` | - |
| 공개 코드는 설정에 따라 달라지지 않는다 | UNIT TESTED | `tests/test_outcomes.py:T29T30PublicCodeTests.test_T29_the_code_does_not_change_with_the_attempt_budget`, `test_T29_the_mapping_module_imports_no_settings`; `tests/test_labels_v3.py:LabelTests.test_a_failed_record_is_never_described_as_retrying` | - |
| 덧보기는 이미 보냈을 수 있는 레코드에는 절대 붙지 않는다 | UNIT TESTED | `tests/test_outcomes.py:T29T30PublicCodeTests.test_T30_overlays_never_apply_to_a_record_that_may_have_been_sent`, `test_T30_a_claimed_record_with_a_receipt_or_queue_id_reads_as_submitted` | - |
| 모든 공개 코드와 덧보기에 모든 언어의 표시 문구가 있다 | UNIT TESTED | `tests/test_labels_v3.py:LabelTests.test_every_public_code_and_overlay_has_a_label_in_every_language`; `tests/test_locale.py:CatalogTests`(9개) | 돌아가는 창에서 한국어 문구를 읽어 본 사람은 없다. 한국어 스크린샷 안에만 있다. |
| 창과 패널과 도구는 공개 코드를 보여 주고, 명령줄은 저장 상태도 함께 찍는다 | UNIT TESTED | `tests/test_control_v3.py:HistoryAndStatisticsTests.test_the_timeline_code_is_the_code_the_listing_shows`, `test_listing_carries_the_public_code_and_overlays` | - |
| 모든 거절은 닫힌 집합의 코드를 문장과 함께 싣고, 같은 거절은 늘 같은 코드를 싣는다 | UNIT TESTED | `tests/test_control.py:ErrorCodeTests`(11개); `tests/test_mcp.py:RefusalTests`(6개); `tests/test_control_v3.py:RefusalCodeTests`(5개); `tests/test_locale.py:CatalogTests.test_every_refusal_code_has_a_sentence_in_every_language` | - |

## 7. 대시보드 창

창은 C#입니다. 대부분은 `gui/Dashboard.cs`의 모양을 확인하거나, 창이 부르는 제어 계층을 시험해서
덮습니다. 컴파일된 프로그램을 실제로 돌리는 항목은 몇 개뿐입니다.

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 여섯 쪽 - 개요, 대기 중, 기록, 통계, 진단, 설정 | REAL WINDOWS TESTED | `gui/Dashboard.cs`가 여섯 쪽을 모두 만들고, 여섯 쪽 모두 `build/capture_window.ps1`로 144 DPI에서 두 언어로 찍혀 있다. `docs/images/dashboard-overview.png`, `dashboard-pending.png`, `dashboard-history.png`, `dashboard-statistics.png`, `dashboard-diagnostics.png`, `settings-window.png`이며 `assets/screenshots.json`에 고정되고 `tests/test_screenshots.py:ManifestTests`(5개)가 확인한다 | 한 쪽을 한 크기에서 한 벌의 합성 레코드로 찍은 것이다. 그림은 쪽이 그려진다는 것을 보일 뿐, 사람이 그것을 쓰는 모습을 보이지는 않는다. |
| 스크린샷은 최신이다. 그것을 만든 입력이 바뀌면 스위트가 실패한다 | UNIT TESTED | `tests/test_screenshots.py:ManifestTests.test_every_render_input_is_unchanged_since_the_images_were_made`, `test_the_committed_images_are_the_ones_the_manifest_describes`, `test_the_window_inputs_include_what_the_dashboard_is_computed_by` | 매니페스트는 마지막 릴리스의 번호를 적으므로, 다음 릴리스가 나오기 전까지 스크린샷 바닥글의 번호는 한 릴리스 뒤처진다. |
| 스크린샷의 예시 자료에는 실제 식별자가 없다 | UNIT TESTED | `tests/test_screenshots.py:ContentTests.test_the_window_sample_carries_no_real_identifier`, `test_the_sample_data_carries_no_real_identifier` | - |
| 창은 오래 사는 브리지 프로세스 하나와, 요청 하나에 JSON 한 줄로 이야기한다 | UNIT TESTED | `tests/test_gui_layout.py:PersistentBridgeTests.test_the_serve_command_line_answers_a_request`가 창이 만드는 바로 그 명령줄을 돌려 실제 응답을 요구한다. `tests/test_control.py:BridgeTests.test_serve_answers_every_line_with_exactly_one_line`, `test_serve_framing_edge_cases_each_get_the_answer_they_should`, `test_serve_cannot_reach_anything_the_one_shot_form_cannot` | 컴파일된 창 쪽 클라이언트는 한 번도 구동되지 않는다. |
| 개요 전체가 한 번의 왕복으로 오고, 각 조각은 따로 실패한다 | UNIT TESTED | `tests/test_control.py:BridgeTests.test_a_dashboard_part_that_fails_costs_only_that_part` | 브리지에서 확인한 것이다. 실패한 조각을 창이 제대로 그리는지는 확인하지 않는다. |
| 읽을 수 없는 조각은 빈 목록이 아니라 읽을 수 없음으로 보인다 | REAL WINDOWS TESTED | `tests/test_gui_decisions.py:DecisionTests`(10개 중 3개)가 컴파일된 창 자신의 `Unreadable`을 한쪽만 오류로 돌아온 스냅숏, 다른 쪽만, 둘 다, 둘 다 아닌 경우로 부르고, 창 자신의 `ShowUnreadable`을 이미 한 줄이 들어 있는 진짜 `ListView`와 이미 "Nothing is waiting"이라고 적힌 진짜 `Label`에 대고 부른다. 그 결과는 비워지고, 보이고, 읽을 수 없다고 말해야 한다. 브리지 쪽은 `tests/test_control.py:BridgeTests.test_a_dashboard_part_that_fails_costs_only_that_part`다 | **그림이 없다.** 판단과 글자는 구동되지만 그 상태의 창을 찍은 적은 없고, 그것이 [LIVE_ACCEPTANCE.ko.md](LIVE_ACCEPTANCE.ko.md)의 12단계가 있는 이유다. |
| 브리지와 이야기하는 일은 UI 스레드에서 돌지 않는다 | UNIT TESTED | `tests/test_gui_layout.py:WatcherStartReportingTests.test_the_wait_does_not_happen_on_the_ui_thread`, `test_it_does_not_wait_a_fixed_time_and_hope`, `test_it_reads_the_state_the_engine_reported` | 소스 모양 확인이다. 이유를 못 박을 뿐, 새로운 방식으로 잘못된 코드는 통과한다. |
| 모든 동작은 정확한 중단 id로 대상을 가리키고, 확인 문구는 대화 이름을 말한다 | UNIT TESTED, 제어 계층에서 | `tests/test_control.py:IdentifierTests`(3개); `tests/test_control_v3.py:ThreadSwitchTests.test_the_switch_needs_an_exact_id` | 보내는 id가 선택된 행의 것인지, 확인 문구가 실제로 이름을 싣는지 - C# 쪽 절반은 확인되지 않았다. |
| 지금 다시 확인은 할 일이 있는 곳에만, 시도 되돌리기는 보낼 수 없는 곳에 제공된다 | REAL WINDOWS TESTED | `tests/test_gui_decisions.py:DecisionTests`(7개 중 4개)가 컴파일된 창을 불러와 창 자신의 `CanRetryNow`와 `CanGiveAttemptsBack`을 레코드 열여덟 가지로 부른다. 지난 초기화와 아직 남은 초기화, 일시 정지, 대화별 끔, 취소, 시도를 다 쓴 경우와 되돌릴 횟수가 남은 경우와 남지 않은 경우, 아무도 모르는 코드, 고른 레코드가 없는 경우, 그리고 창이 바쁜 경우다. 그 조건이 피하려는 거절은 모두 제어 계층에서 시험된다: `tests/test_control_v3.py:RefusalCodeTests.test_each_retry_now_refusal_arrives_as_its_own_code`, `test_each_restore_budget_refusal_arrives_as_its_own_code` | 판단은 시험되지만, 창이 그 판단을 맞는 버튼에 잇는지는 아직 읽어서 확인할 뿐이다. |
| 타임라인은 한 연쇄를 공개 어휘로 보여 주고 내용을 싣지 않는다 | UNIT TESTED | `tests/test_control_v3.py:HistoryAndStatisticsTests.test_the_timeline_is_content_free`, `test_the_timeline_code_is_the_code_the_listing_shows` | 타임라인 대화 상자를 보여 주는 산출물이 없다. |
| 기록 지우기는 숨길 뿐 지우지 않으며, 숨긴 행도 모든 상한과 중복 확인에 계속 센다 | UNIT TESTED | `tests/test_store.py:HideHistoryTests`(2개, `test_T41_hidden_rows_still_count_for_every_safety_decision` 포함); `tests/test_control_v3.py:HistoryAndStatisticsTests.test_clear_history_hides_finished_records_and_keeps_them_counting` | - |
| 통계는 7일·30일·전체 기준이고, 레코드마다 최종 결과 하나만 세며, 성공률은 다섯 건 이상일 때만 보인다 | UNIT TESTED | `tests/test_store.py:StatisticsTests`(4개, `test_T44_a_late_receipt_counts_once`, `test_statistics_include_hidden_rows` 포함) | 통계 쪽 자체의 산출물이 없다. |
| 진단 내보내기는 가려 쓴 파일을 쓰고 기존 파일을 덮지 않는다 | UNIT TESTED | `tests/test_diagnostics.py:DiagnosticsTests`(4개) | 시험되는 것은 `diagnostics.write`뿐이다. 버튼, 파일 선택, 보내기 전에 읽어 보는 흐름은 확인되지 않았다. |
| 설치 복구는 다섯 가지 중 무엇이 일어났는지 말하고, 설치 관리자의 잠금을 잡으며 `--keep-state`로 돈다 | REAL WINDOWS TESTED | `tests/test_gui_decisions.py:DecisionTests`(7개 중 3개)가 컴파일된 창의 `RunRepair`를 setup 대신 서는 진짜 자식 프로세스에 대고 부른다. 종료 코드와 줄의 조합마다, setup이 없는 경우, 잠금을 다른 프로세스가 쥔 경우까지 돌리며, setup이 `--keep-state`를 거부해 2로 끝난 경우가 성공으로 읽히지 않아야 한다는 것도 포함한다. 잠금은 `tests/test_convergence.py:InstallerLockTests`(3개)가, `--keep-state`는 `tests/test_plugin.py:BridgeTests.test_keep_state_repairs_an_autostart_that_is_already_ours`가 시험한다 | "아직 작업 중"은 진짜 느린 setup이 아니라 시험의 제한 시간으로 만든 것이고, 잘라 낸 실패 꼬리는 견주지 않는다. |
| 워처 중지는 중지 이벤트로 부탁하고 절대 죽이지 않으며, 중지됨 / 아직 마무리 중 / 실행 중 아님 / 알 수 없음을 답한다 | UNIT TESTED | `tests/test_control.py:StopWatcherTests`(9개, `test_the_stop_is_asked_once_and_nothing_is_ever_killed`, `test_a_probe_that_cannot_tell_is_unknown_and_never_stopped`, `test_the_layer_holds_no_way_to_end_a_process` 포함) | 창의 버튼은 구동되지 않고, 네 가지 문구는 어떤 산출물에도 나오지 않는다. |
| 워처 시작은 뮤텍스 확인으로 검증하고 과장해서 말하지 않는다 | UNIT TESTED | `tests/test_control.py:StartWatcherTests`(6개), `WatcherConfirmationTests`(8개), `StartWatcherReportingTests`(6개, `test_every_outcome_has_wording_that_does_not_overclaim` 포함) | - |
| 창과 브리지 사이의 선은 기계의 코드 페이지와 무관하게 UTF-8이다 | REAL WINDOWS TESTED | `tests/test_bridge_encoding.py:WireEncodingTests`(5개)가 `PYTHONIOENCODING=cp949`와 UTF-8 모드 해제 상태에서 진짜 브리지를 하위 프로세스로 돌린다 | 디코딩 쪽 절반은 C# 소스를 상대로 확인할 뿐, 돌아가는 창을 상대로 하지 않는다. |
| 잘못된 응답이나 깊게 중첩된 응답은 프로세스의 죽음이 아니라 평범한 형식 오류다 | REAL WINDOWS TESTED | `tests/test_gui_json.py:ParserRobustnessTests`(5개)가 내장 C# 컴파일러로 진짜 창을 컴파일하고 탐침 프로세스를 돌린다: `test_the_probe_process_survived`, `test_the_limit_is_where_it_says` | 내장 컴파일러나 PowerShell이 없으면 건너뛴다. |
| 배치: 편집 줄, 바닥 띠, 숫자 입력 여백, 이중 버퍼 그리기 | UNIT TESTED, 뒤에 실제 캡처가 있음 | `tests/test_gui_layout.py:RowLayoutTests`(3개), `FooterTests`(3개), `NumericInsetTests`(5개), `BufferedPaintTests`(2개). 그 모듈은 여섯 가지 배율과 144 DPI의 실제 창을 상대로 렌더링을 직접 재 봤다고 적고 있다 | 그 측정은 docstring에 적혀 있을 뿐 산출물로 남아 있지 않다. 커밋된 캡처는 144 DPI 한 경우뿐이다. |
| 원시 픽셀로 쓰인 값이 없고, 상태 점이 있는 열도 배율을 따른다 | UNIT TESTED | `tests/test_brand.py:WindowScalingTests`(3개); `tests/test_screenshots.py:PixelTests.test_every_window_screenshot_shows_the_state_dot`, `test_every_window_screenshot_has_both_hairlines` | 커밋된 스크린샷이 있는 배율은 하나뿐이다. |
| 창은 자기 색을 쓰지 않고 모든 색이 팔레트에서 온다 | UNIT TESTED | `tests/test_brand.py:SurfaceTests.test_settings_window_writes_no_colour_of_its_own`, `GeneratedFileTests.test_gui_brand_cs_is_current`, `RetiredColourTests.test_no_tracked_file_still_carries_a_retired_colour` | - |
| 로컬 웹 서버가 없고, 브라우저로 열리는 것도 없다 | UNIT TESTED | `tests/test_surface_properties.py:NoBrowserTests`(3개)가 `gui/`, `src/`, `scripts/`, `install/` 아래 추적되는 모든 파일에서 브라우저 컨트롤, 내장 렌더러, 듣는 소켓, 두 번째 런타임을 거부하고, 창이 System·System.Drawing·System.Windows.Forms 셋에만 기대어 컴파일되는지와 릴리스에 두 번째 런타임이 없는지를 요구한다. Python 쪽은 `tests/test_privacy_claims.py:CodePropertyTests`가 덮는다 | 금지 목록이라 알려진 경로만 막는다. 새로운 경로는 목록에 더해야 한다. |
| 목록은 5초마다 새로 읽는다 | IMPLEMENTED | `gui/Dashboard.cs`(`StartClock`, `RefreshNow`, `UpdateCountdowns`) | 확인되지 않았다. 간격을 재는 것도, 확인 문구와 그 동작 사이에 갱신이 끼어들 수 없다는 것을 확인하는 것도 없다. |

## 8. 알림 영역 아이콘

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 아이콘은 워처 프로세스의 것이다. 워처가 시작하면 나타나고 멈추면 사라진다 | REAL WINDOWS TESTED | `tests/test_tray.py:LiveIconTests.test_the_icon_starts_updates_and_goes_away_cleanly`가 Windows에서 진짜 알림 영역 아이콘을 만들고 도구 설명을 바꾸고 그 스레드가 끝나기를 요구한다 | Windows가 아니면 건너뛴다. 아이콘이나 그 메뉴의 스크린샷은 저장소 어디에도 없다. |
| 도구 설명은 일시 정지 / 대기 / 진행 / 다음 확인까지를, 모든 언어에서 길이 제한 안에 말한다 | UNIT TESTED | `tests/test_tray.py:WordingTests`(4개, `test_every_language_fits_the_tooltip_limit`, `test_the_countdown_is_short_and_never_negative` 포함) | 실제 기계에서 한국어 도구 설명을 읽어 본 사람은 없다. |
| 보여 주는 값은 이 제품 자신의 상태 저장소에서만 온다 | UNIT TESTED | `tests/test_tray.py:SnapshotTests.test_the_snapshot_comes_from_our_own_store_only` | - |
| 메뉴는 창을 열고, 자동 복구를 일시 정지하거나 다시 켜고, 워처를 멈춘다. 모두 같은 제어 계층을 지난다 | UNIT TESTED | `tests/test_surface_properties.py:TrayMenuTests`(7개)가 아이콘 자신의 `_act`로 모든 메뉴 id를 보낸다. 열기, 멈추기, 그려질 때의 상태에 따라 일시 정지도 되고 다시 켜기도 되는 그 한 항목, 고르지 않고 메뉴를 닫은 경우, 항목이 아닌 id, 예외를 던지는 동작(워처를 함께 쓰러뜨리지 않고 기록되어야 한다), 그리고 아무것도 잇지 않은 아이콘까지 있다 | id를 보내는 것이지 누르는 것은 아니다. `TrackPopupMenu` 자체는 구동하지 않아서, 사람의 클릭이 어떤 id를 만드는지는 아직 확인되지 않았다. |
| 메뉴는 정확히 그 대기 중인 일로 가는 길을 내주고, 그 일에 대한 동작은 내놓지 않는다 | UNIT TESTED | `src/codex_auto_resume/tray.py`의 `MENU_PENDING`과 `open_dashboard`가, 기다리는 것이 있을 때만, 창을 대기 중 쪽으로 여는 항목을 더한다. `tests/test_surface_properties.py:TrayMenuTests.test_pending_opens_the_page_where_those_actions_live`, `test_the_window_is_only_ever_opened_on_a_page_it_has` | **지금 다시 확인과 취소는 일부러 메뉴에 두지 않았다.** 워처가 계속 바꾸고 있는 목록으로 만든 문맥 메뉴는 그 id가 메뉴를 그릴 때 가리키던 레코드에 대고 동작한다. 그리고 메뉴 항목 옆에는 그 동작이 어떤 대화에 관한 것인지 적을 자리가 없는데, 창의 확인 문구가 쓰는 것이 바로 그것이다. 길을 내주는 쪽이 같은 필요의 더 안전한 절반이다. |
| 기본으로 켜져 있고 설정에서 끌 수 있다 | UNIT TESTED, 설정에 대해서만 | `tests/test_settings.py:DefaultsTests.test_every_field_has_a_default`, `DescribeTests.test_describes_every_field_exactly_once` | 껐을 때 아이콘이 실제로 사라지는지 확인하는 것은 없다. |

## 9. Codex 패널과 MCP 도구

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 패널은 플러그인이 내주는 바로 그 자원이고, 그리는 데 필요한 것을 모두 싣고, 아무것도 가져오지 않으며, 자기 설정을 갖지 않는다 | UNIT TESTED | `tests/test_mcp.py:WidgetTests`(11개, `test_the_panel_fetches_nothing`, `test_the_panel_carries_no_settings_of_its_own`, `test_a_preview_seed_is_escaped` 포함) | 실제 Codex 클라이언트가 불러온 적이 없다. |
| 패널은 기다리는 것을 공개 어휘로, 지금 어떤 상태인지와 다음에 언제 확인하는지까지 보여 준다 | UNIT TESTED | `src/codex_auto_resume/mcpui.py`가 각 줄의 공개 코드와 덧붙는 사실, 시도 횟수, 다음 확인 시각을 그리고, 그중 가장 이른 것을 개수 옆에 둔다. `tests/test_mcp.py:WidgetTests`(11개)가 패널에 무엇이 주어지는지를, `PanelWordingTests`(6개)가 무엇을 말하는지를 덮는다 | 재깍이는 카운트다운이 아니라 시각이다. 이 쪽은 도구 결과 하나로 한 번 그려지고 다시 그려지지 않으므로, 거기서 줄어드는 숫자는 곧 틀리면서도 그럴듯해 보이게 된다. 실시간 카운트다운은 창과 알림 영역 아이콘의 몫이다. |
| 공개된 패널 스크린샷은 Codex를 찍은 사진이 아니라 그 마크업을 그린 것이다 | REAL WINDOWS TESTED | `assets/screenshot-panel.png`과 그 한국어 짝. `assets/screenshots.json`의 `<panel render:en>`, `<panel render:ko>`가 입력을 고정하고 `tests/test_screenshots.py:ManifestTests.test_the_panel_input_is_the_rendered_markup_not_a_file_list`가 확인한다 | **Codex 안에서 패널을 본 사람이 없다.** REAL CODEX VISUALLY TESTED 항목이 생길 가능성이 가장 큰 자리인데, 아직 없다. |
| 패널이 받을 수 있는 모든 거절에 대해, 자기가 말하는 언어로 문장을 갖는다 | UNIT TESTED | `tests/test_mcp.py:WidgetTests.test_the_panel_is_served_a_sentence_for_every_refusal_it_may_be_handed`, `test_only_the_refusal_helper_reads_the_english_sentence`; `PanelWordingTests`(6개) | - |
| 도구 열여섯 개가 각각 스키마와 구현을 갖고, 스킬 문서가 정확히 그 목록을 적는다 | UNIT TESTED | `tests/test_mcp.py:ToolSurfaceTests.test_every_tool_has_a_schema_and_an_implementation`, `test_the_skill_lists_every_tool_and_no_others` | - |
| 어떤 도구도 이어가기를 보낼 수 없고, 정확한 id가 아닌 방식으로 대화를 받지 않는다 | UNIT TESTED | `tests/test_mcp.py:ToolSurfaceTests.test_no_tool_can_send_a_continuation`, `test_no_tool_accepts_a_thread_by_anything_but_an_exact_id`; `tests/test_control.py:NotARecoveryEngineTests`(2개), `BridgeTests.test_bridge_exposes_no_command_that_sends` | - |
| 일시 정지는 묻지 않고 돌고, 다시 켜기·예산 되돌리기·워처 시작·설정 변경은 파괴적으로 표시된다 | UNIT TESTED | `tests/test_mcp_v3.py:ApprovalHintTests`(3개); `tests/test_mcp.py:ToolSurfaceTests.test_automation_can_be_reduced_freely_but_only_increased_with_approval`, `test_read_only_tools_are_marked_read_only` | **Codex가 실제로 물어보는지는 어디서도 확인하지 않고, 여기서는 확인할 수도 없다.** 표시는 요청이지 잠금이 아니며, Codex가 그것을 지키는 것을 본 기록이 없다. |
| `update_settings`는 스키마를 무시하는 클라이언트에게도 고급 설정을 거절한다 | UNIT TESTED | `tests/test_mcp.py:ToolBehaviourTests.test_an_advanced_setting_is_refused_even_if_the_schema_is_ignored`; `ToolSurfaceTests.test_advanced_settings_are_not_offered_to_a_model`, `test_the_settings_schema_offers_no_unknown_failure_switch` | - |
| `get_status`는 설치 경로를 싣지 않는다 | UNIT TESTED | `tests/test_mcp.py:ToolBehaviourTests.test_status_does_not_carry_the_install_path` | - |
| 전송 계층은 한 줄에 JSON 하나로 답하고, 깨진 줄에도 끊기지 않고, 알림에는 답하지 않고, 내부 실패에서 아무것도 흘리지 않는다 | UNIT TESTED | `tests/test_mcp.py:TransportTests`(9개) | 실제 Codex MCP 클라이언트가 구동한 적이 없다. 협상도 테스트 자신의 요청을 상대로만 확인된다. |
| 플러그인 매니페스트는 훅도, 환경 변수도, 네트워크도 선언하지 않고, 이 제품 자신의 stdio 서버만 이름 짓는다 | UNIT TESTED | `tests/test_plugin.py:ManifestTests`(13개) | - |

## 10. 명령줄

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 열네 개 명령이 처음부터 끝까지: install, enable, status, disable, pending, cancel, logs, run, stop, uninstall, doctor, activate, diagnostics, downgrade-state | UNIT TESTED | `tests/test_cli.py:CliTests`(9개, `test_install_enable_status_disable_cycle`, `test_run_once_without_engine_fails_closed`, `test_uninstall_removes_only_owned_files`, `test_stop_without_watcher` 포함) | - |
| `downgrade-state --to 2`가 만든 파일을 마지막 릴리스 태그의 코드가 모든 행을 그대로 두고 연다 | UNIT TESTED | `tests/test_downgrade.py:DowngradeTests.test_the_tagged_v0_5_7_store_opens_the_result_with_every_row`가 그 git 태그에서 저장소 모듈을 불러와 결과를 연다. `test_upgrading_again_restores_a_working_v3_state`도 있다 | 태그가 체크아웃에 없으면 건너뛴다 - CI에서는 실패, 로컬에서는 조용한 건너뜀. 옛 릴리스가 돌아가는 것이 아니라 옛 *저장소 모듈*을 시험한다. |
| `downgrade-state`는 워처가 돌고 있으면 거절한다 | UNIT TESTED | `tests/test_downgrade.py:DowngradeCommandTests.test_it_refuses_while_the_watcher_runs` | - |
| `doctor`가 프로토콜 등록과 찾아낸 엔진을 보고한다 | UNIT TESTED | `tests/test_cli.py:DoctorProtocolCheckTests`(3개), `DiscoveryTests.test_discovery_requires_single_compatible_binary` | 가짜 레지스트리를 상대로 한다. |
| 워처 루프가 일시적 어댑터 실패와 상태 읽기 실패를 견딘다 | UNIT TESTED | `tests/test_cli.py:WatcherLoopTests`(2개) | - |
| 로그는 고정된 문구 표에서 그려지고 Windows 현지 시각을 찍는다 | UNIT TESTED | `tests/test_cli.py:LogbookTests`(2개) | - |
| 진입점은 `PYTHONPATH` 없이 무관한 디렉터리에서도 돌고, 자기 패키지를 맨 앞에 둔다 | UNIT TESTED | `tests/test_cli.py:EntryPointTests`(2개) | - |

## 11. Windows 알림

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 알림은 PowerShell이 아니라 이 제품 자신의 이름으로 올라온다 | UNIT TESTED, 옆에 실제 캡처가 있음 | `tests/test_notify.py:NotificationIdentityTests`(4개). `docs/images/notification.png`은 이 제품이 올린 실제 Windows 알림을 찍은 것이다 | 그 그림은 `assets/screenshots.json`에 **고정되어 있지 않아서**, 낡아도 아무것도 실패하지 않는다. 매니페스트에 넣으면 해결된다. |
| 알림이 실제로 그려지는 것은 시작 메뉴 바로 가기가 같은 AppUserModelID를 싣고 있기 때문이다 | REAL WINDOWS TESTED | `tests/test_surface_properties.py:ShortcutTests`(5개)가 `APPDATA`를 임시 폴더로 돌린 뒤 진짜 `shortcut.install`을 돌리고, 셸 자신의 바로 가기 객체로 대상과 설명을 다시 읽고, 파일의 바이트에서 AppUserModelID를 찾아내며, 알림을 보내는 쪽이 같은 id를 쓰는지 확인한다. `src/codex_auto_resume/shortcut.py`가 Windows 11에서 잰 것을 적고 있다. 바로 가기가 없으면 플랫폼은 알림을 받아들이고 전달했다고 기록까지 하면서 그리지만 않는다 | id를 `IPropertyStore`가 아니라 파일에서 읽고, 실제 알림을 띄워 본 적은 없다. |
| 바로 가기의 값들은 스크립트 안이 아니라 스크립트 옆으로 간다 | UNIT TESTED | `tests/test_pwsh.py:NoValueInScriptTests.test_the_shortcut_values_travel_out_of_band`가 `subprocess.run`을 가짜로 바꿔 `shortcut.install`을 구동하고, PowerShell에 넘어간 `-EncodedCommand`를 디코딩해 그것이 손대지 않은 `shortcut._MAKER`이기를 요구한다. 어포스트로피가 들어간 설치 경로는 환경 변수 쪽에서 나온다. `test_every_pwsh_run_call_passes_a_module_constant`가 `shortcut.py`를 두 호출자 중 하나로 이름 짓는다 | 그 테스트에서 PowerShell은 돌지 않고 파일도 쓰이지 않는다. **`shortcut.uninstall`은 어디에서도 구동되지 않는다.** 우리 폴더의 우리 이름만 지우고 심볼릭 링크는 거절한다는 것은 검토했을 뿐 시험하지 않았다. |
| 이름 등록이 없어도 알림은 막히지 않는다 | UNIT TESTED | `tests/test_notify.py:NotificationIdentityTests.test_an_unregistered_identity_still_sends`. 그 클래스의 docstring이 Windows 11에서 미등록 상태로도 전달되는 것을 재 봤다고 적고 있다 | 그 측정은 적혀 있을 뿐 산출물로 남아 있지 않다. |
| 알림에 대화 내용이 들어가지 않고, 최대 세 줄이며, 문구는 XML 이스케이프된다 | UNIT TESTED | `tests/test_notify.py:ToastPayloadTests`(12개, `test_no_conversation_content_is_disclosed`, `test_never_more_than_three_lines`, `test_the_embedded_document_is_still_valid_xml`, `test_a_quote_in_the_text_cannot_break_out_of_the_script` 포함) | - |
| 어떤 값도 PowerShell에 스크립트 문자열로 넘어가지 않는다 | REAL WINDOWS TESTED | `tests/test_pwsh.py:RealInterpreterTests`(2개)가 적대적인 값으로 진짜 Windows PowerShell을 돌린다. `NoValueInScriptTests`(5개), `EnvironmentTests`(4개)가 모양을 못 박는다 | PowerShell이 없으면 건너뛴다. |
| PowerShell이 없거나 실패해도 오류가 아니다 | UNIT TESTED | `tests/test_notify.py:ToastPayloadTests.test_a_failing_or_missing_powershell_is_not_an_error` | - |
| 버튼은 취소만 하며, 적대적이거나 깨진 URI는 저장소에 닿지 않는다 | UNIT TESTED | `tests/test_notify.py:CancelUriTests`(4개), `ActivationTests`(3개) | 실제 알림 클릭에서 실제 프로토콜 처리기를 지나는 경로는 한 번도 시험되지 않았다. |
| 생애 주기 사건마다 스위치가 있고, 총괄 스위치가 전부를 끈다 | UNIT TESTED | `tests/test_notify.py:EngineNotificationTests.test_every_lifecycle_event_maps_to_a_notification_setting`, `NotificationSettingTests.test_messages_exist_in_every_language`; `tests/test_settings.py:PolicyTests.test_master_notification_switch_silences_every_event`, `test_individual_notification_events_are_independent` | - |
| 한 중단은 몇 번을 보든 한 번만 알리고, 알림 실패가 복구를 막지 않는다 | INTEGRATION TESTED | `tests/test_notify.py:EngineNotificationTests.test_an_interruption_is_announced_once_however_often_it_is_seen`, `test_a_failing_notification_never_blocks_a_resume` | - |
| 이미 멈춘 채로 태어난 자식은 멈췄다고만 알린다 | INTEGRATION TESTED | `tests/test_outcomes.py:T48NotificationTests.test_T48_a_child_registered_exhausted_is_announced_as_stopped_only`, `test_T48_children_registered_cancelled_or_superseded_are_announced_as_stopped_only` | - |

## 12. 플랫폼 조각

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 단일 인스턴스 뮤텍스가 두 번째 워처를 거절한다 | REAL WINDOWS TESTED | `tests/test_engine.py:SingleInstanceTests.test_16_duplicate_watcher_process_is_refused`가 진짜 프로세스 하나에 진짜 이름 있는 뮤텍스를 쥐게 하고, App이 busy로 끝나기를 요구한다 | Windows가 아니면 건너뛴다. 라이브 판인 `tests/test_integration_live.py:LiveReadOnlyTests.test_single_instance_mutex_and_stop_event_roundtrip`는 `CODEX_AR_LIVE=1`이 필요하고 실행 기록이 없다. |
| 중지 이벤트가 기다리는 쪽을 깨우고, 멈추는 것은 언제나 부탁이다 | REAL WINDOWS TESTED | `tests/test_engine.py:SingleInstanceTests.test_stop_event_wakes_waiter`가 진짜 이름 있는 이벤트를 쓴다. `tests/test_control.py:StopWatcherTests.test_the_stop_is_asked_once_and_nothing_is_ever_killed` | - |
| 더 낮은 무결성 수준의 프로세스가 먼저 만든 뮤텍스나 중지 이벤트는 거절하고, 상태는 실행 중이 아니라 알 수 없음으로 읽힌다 | REAL WINDOWS TESTED | `tests/test_named_objects.py:SquattedObjectTests`(5개)가 Low 무결성 표를 단 진짜 이름 있는 객체를 만들고 워처가 그것을 거절하기를 요구한다 | Windows가 아니면 건너뛴다. 돌고 있는 워처 자신의 Medium 뮤텍스를 낮은 무결성 프로세스가 여는 경우는 **덮지 않는다** - SECURITY 문서가 그렇게 적고 있고, 막을 방법이 없어서 시험하지도 않는다. |
| 깨우기 이벤트 덕분에 지금 다시 확인이 기다림을 줄인다 | REAL WINDOWS TESTED | `tests/test_surface_properties.py:WakeEventTests`(4개)가 두 번째 프로세스에서 진짜 이름 있는 이벤트를 쥐고 2분을 기다리게 한 뒤 이쪽에서 신호를 보내, 기다림이 30초에 한참 못 미쳐 그 이벤트로 끝나기를 요구한다. 기다리는 쪽이 없으면 거짓을 답하는 것, 한 상태 디렉터리의 이벤트가 다른 쪽에 닿지 않는 것, 이벤트가 없는 대체 경로도 헛돌지 않고 자는 것도 함께 요구한다. 이벤트를 쓸 수 없는 경우의 대체 경로는 `tests/test_cli.py:WatcherLoopTests`도 덮는다 | 두 프로세스가 같은 로그온 세션 안에 있다. |
| 홈 잠금이 한 상태 디렉터리에 프로세스 둘이 들어가는 것을 막는다 | REAL WINDOWS TESTED | `tests/test_surface_properties.py:HomeLockTests`(5개)가 진짜 잠금을 잡고 두 번째가 `home_lock_busy`로 거절되기를 요구한다. 같은 프로세스에서도, 두 번째 프로세스에서도 그렇다. 쥐고 있던 쪽이 사라지면 다시 풀리는 것, 서로 무관한 홈은 서로의 일이 아니라는 것, 한 홈을 두 가지로 적어도 한 잠금이라는 것도 함께 요구한다. `home_lock_unavailable`은 `src/codex_auto_resume/machine.py`의 정식 거절 사유다 | 두 프로세스가 같은 로그온 세션 안에 있다. 잠금이 함께 막으려는 세션 사이의 경우는 돌려 본 적이 없다. |
| 로그인 시작은 현재 사용자의 `Run` 키에 값 하나를 쓰고, 여러 번 해도 같으며, 실제 홈을 못 박고, 지울 수 있다 | UNIT TESTED | `tests/test_cli.py:StartupTests`(4개); `tests/test_plugin.py:AutostartOwnershipTests`(5개), `BridgeTests.test_setup_refuses_when_another_installation_owns_autostart`, `test_no_startup_never_writes_the_registry` | `FakeWinreg`를 상대로 한다. **진짜 `Run` 값을 쓰는 테스트가 없고**, 워처가 실제 Windows 로그인에서 시작했다는 기록도 저장소에 없다. 실제 로그인 뒤의 `logs/launcher.log`를 담아 두는 것이 그 산출물이 된다. |
| 등록되는 명령은 공백, 끝의 역슬래시, 따옴표, 유니코드가 든 경로를 견딘다 | REAL WINDOWS TESTED | `tests/test_cli.py:CommandQuotingTests`(6개)가 Windows에서 `CommandLineToArgvW` 자체와 비교한다. `tests/test_installer_ownership.py:ArgumentQuotingTests`(6개) | Windows가 아니면 건너뛴다. |
| 홈의 짧은 경로 표기와 대소문자 표기가 같은 설치로 풀린다 | UNIT TESTED | `tests/test_plugin.py:ShortPathOwnershipTests`(7개) | - |
| `codex-auto-resume:` 프로토콜 처리기는 사용자별로 등록되고, activate 동사만 싣고, 우리 것일 때만 지워진다 | UNIT TESTED | `tests/test_notify.py:ProtocolRegistrationTests`(4개); `tests/test_cli.py:DoctorProtocolCheckTests` | 가짜 레지스트리를 상대로 한다. **실제 프로토콜 등록도, 실제 알림 버튼에서 온 활성화 기록도 없다.** |
| 워처 실행기는 시스템 실행 파일을 절대 경로로 부르고, 현재 디렉터리로는 아무것도 찾지 않는다 | UNIT TESTED | `tests/test_upgrade_handover.py:LauncherPathTests`(3개) | - |

## 13. 설치, 업그레이드, 복구, 제거

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 설치 관리자가 PowerShell로 파싱된다 | REAL WINDOWS TESTED | `tests/test_installer.py:ParseTests.test_the_installer_parses_as_powershell`가 진짜 PowerShell 파서로 `install/install.ps1`을 읽는다 | 파싱은 실행이 아니다. 스위트에서 설치 관리자를 끝까지 돌리는 것은 없다. |
| 관리자 권한이 필요 없고, 서비스나 예약 작업을 만들지 않고, 기계 전역 레지스트리를 쓰지 않고, 설치 때 아무것도 내려받지 않고, 번들 런타임을 쓴다 | UNIT TESTED | `tests/test_installer.py:SafetyTests`(12개) | `install/install.ps1`에 대한 소스 확인이다. 실제 설치는 수행되지 않는다. |
| 프로그램 디렉터리는 지우지 않고 옆으로 옮기며, 어느 단계에서 실패해도 설치가 되돌려진다 | UNIT TESTED | `tests/test_installer.py:InPlaceUpgradeTests`(7개) | - |
| 옆으로 옮긴 기록은 첫 이동 전에 통째로 쓰이고, 무엇을 쓸어내기 전에 읽히며, 두 나무가 제자리에 있을 때만 지워진다 | UNIT TESTED | `tests/test_installer.py:CrashDuringTheCopyTests`(10개), `JournalRecoveryTests`(9개, `test_a_tree_left_aside_by_an_interrupted_run_is_put_back`, `test_a_path_outside_the_installation_is_never_moved`, `test_a_journal_that_cannot_be_read_destroys_nothing` 포함) | 실제 설치에서 정전을 흉내 내 본 적은 없다. 크래시 지점은 테스트가 고른 것이다. |
| 페이로드 뿌리에는 설정 창과 그 아이콘만 이름으로 복사되고, 다른 것이 든 압축 파일은 거절된다 | UNIT TESTED | `tests/test_installer.py:PayloadRootTests`(6개), `ArchiveContentsTests`(5개) | - |
| 소유권이 증명된 디렉터리만 설치로 취급하고, 검증된 뿌리 밖은 절대 지우지 않는다 | UNIT TESTED | `tests/test_installer_ownership.py:InstallHomeProvenanceTests`(9개), `PathConfinementTests`(7개), `RemoveOwnedItemTests`(3개), `InstallHomeClaimTests`(8개), `InstallerDeletionRoutingTests`(4개), `ProcessOwnershipTests`(2개) | - |
| 업그레이드는 setup을 `--keep-state`로 돌려서, 복구를 다시 켜지도 않고 지워진 로그인 시작을 되살리지도 않는다 | UNIT TESTED | `tests/test_installer.py:UpgradeKeepsTheOwnersChoiceTests`(6개); `tests/test_plugin.py:BridgeTests.test_keep_state_neither_resumes_nor_adds_an_autostart`, `test_keep_state_repairs_an_autostart_that_is_already_ours`, `test_without_keep_state_setup_still_enables_and_registers` | 실제 버전 간 업그레이드에서 관측된 적이 없다. |
| 파일을 바꾸기 전에 워처를 넘겨받고, 중지 이벤트로 부탁하고, 기다림에 한계를 두고, 남아 있는 워처는 숨기지 않고 보고한다 | UNIT TESTED | `tests/test_upgrade_handover.py:UpgradeHandoverTests`(6개) | - |
| 로그인 실행기는 이 제품 자신의 마켓플레이스만 받아들이고, 아니면 아무것도 시작하지 않는다 | UNIT TESTED | `tests/test_plugin.py:LauncherResolutionTests`(8개, `test_a_same_named_plugin_from_another_marketplace_is_never_run`, `test_only_another_marketplace_means_nothing_starts` 포함); `tests/test_convergence.py:EngineResolutionTests`(4개) | - |
| 부트스트랩은 실행 전에 검증하고, GitHub 호스트만 받아들이며, 실패하면 아무것도 남기지 않는다 | UNIT TESTED | `tests/test_convergence.py:BootstrapTests`(12개), `ReleaseManifestTests`(6개), `HostPortabilityTests`(3개) | `scripts/bootstrap.ps1`에 대한 소스 검사다. 스위트가 실제로 내려받지는 않는다. |
| 보통의 실행이 가져올 버전은 건네줄 수 없다. `-Update`만 그것을 옮기고, 그것도 이 저장소 아래에서 풀어낸 버전으로만 옮긴다 | REAL WINDOWS TESTED | `tests/test_update_check.py:ResolverTests`(9개)가 PowerShell 파서로 `scripts/bootstrap.ps1`에서 실제 해석기를 들어내어, 네트워크를 대신한 최종 URL 열아홉 가지에 대고 돌린다. 포크, 같은 소유자의 다른 저장소, 이름이 이것으로 시작할 뿐인 소유자, 내려받기에는 허용되지만 릴리스를 답하지는 않는 호스트, 평문 HTTP, 버전이 아닌 태그, 경로 거슬러 오르기, 어디서 왔는지 말하지 않는 응답이 들어 있다. 열아홉 중 넷만 받아들이고 나머지는 거부한다. 모양은 `tests/test_convergence.py:BootstrapTests`(12개 중 5개)가 못 박는다 | 모든 경우가 대역이다. 이것이 실제로 보내는 요청 하나인 github.com에 대한 `-CheckOnly`는 스위트에 없고 손으로 돌려야 한다. 이번 릴리스가 공개된 날 실제로 돌렸고, 넘겨받은 주소에서 가장 새 릴리스를 풀어내어 그 기계에 깔린 버전과 견주어 알려 주었으며, 내려받은 것은 없었다. |
| 업데이트가 있는지 묻는 일은 페이지를 옮기지 않고, 사용자에 관한 것을 보내지 않으며, 스스로 일어나지 않는다 | UNIT TESTED | `tests/test_update_check.py:ResolverTests.test_it_asks_for_no_body_and_asks_only_the_constant`이 상수 URL로 가는 `HEAD` 한 번을 요구한다. `tests/test_convergence.py:BootstrapTests.test_the_update_check_never_parses_what_the_server_sends`, `test_nothing_checks_for_an_update_unless_asked`. `tests/test_gui_update.py:ButtonTests.test_nothing_asks_without_being_asked`가 창에서 그것을 부르는 곳이 단추뿐이기를 요구한다 | 익명 요청에 대해 GitHub가 남기는 것(주소, 시각, 사용자 에이전트)은 GitHub의 것이며, 여기서 검사하지 않고 `PRIVACY.md`가 밝힌다. |
| 네 가지 답과 네 가지 종료 코드, 그리고 "물어보지 못함"은 결코 "최신"이 되지 않는다 | REAL WINDOWS TESTED | `tests/test_gui_update.py:BootstrapReadingTests`(4개)가 컴파일된 창의 `RunBootstrap`을 진짜 자식 프로세스 열세 가지에 대고 부른다. 종료 코드와 출력된 줄이 어긋나는 조합이 모두 들어 있고, 그 경우는 둘 다 믿지 않아야 한다. `tests/test_update_check.py:EndToEndTests`(5개)는 아무도 듣지 않는 포트를 향해 스크립트 전체를 돌려 종료 코드 12와 `update: unavailable`, 그리고 아무것도 설치되지 않음을 요구한다 | "이 빌드가 더 앞섬" 답은 대역과 창을 통해서만 시험되고 github.com을 상대로는 해 보지 않았다. |
| 업데이트는 같은 설치기를 지나가고, 워처가 다시 시작했는지는 버전이 아니라 시작 시각으로 확인한다 | REAL WINDOWS TESTED | `scripts/bootstrap.ps1`이 대상 버전을 정한 뒤 여느 때의 내려받기와 체크섬·내용물·버전 검사를 거쳐 `install/install.ps1`로 간다. 그 `--keep-state`는 `tests/test_installer.py:UpgradeKeepsTheOwnersChoiceTests`(6개)가 시험한다. `gui/Dashboard.cs`의 `OfferUpdate`, `AfterUpdate`, `WatcherIdentity`는 `tests/test_gui_update.py:ButtonTests.test_the_watcher_identity_is_the_start_time_not_the_version`이 못 박는다 | 업그레이드를 이제 한 번 수행했다. 실제 Codex가 깔린 기계의 실제 v0.5.6 설치를 보통의 설치 실행으로 이번 버전까지 올렸고, 사이드카가 아니라 고정된 다이제스트로 맞춰 보았으며, 주인의 설정과 대기 중인 일을 그대로 두었고, 끝난 뒤 설치본은 `current`라고 답한다. [`docs/evidence/real-upgrade-2026-09-13.json`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/evidence/real-upgrade-2026-09-13.json)이 그것을 기록하고 있다. **넘겨받기 확인은 아직도 실제 재시작을 본 적이 없다.** 그 전에 워처가 돌고 있지 않았으므로 설치기가 갈아 끼운 것이 아니라 새로 띄웠다. 그리고 중단은 일어나지 않았으므로 여기 있는 무엇도 복구에 대한 근거가 아니다. 나머지가 있을 곳은 여전히 [LIVE_ACCEPTANCE.ko.md](LIVE_ACCEPTANCE.ko.md)다. |
| `-Force`로 청하지 않는 한 설치된 것이 더 오래된 것으로 바뀌는 일은 없다 | REAL WINDOWS TESTED | `tests/test_update_check.py:NeverGoesBackwardsTests`(5개)가 더 새로운 버전, 같은 버전, 더 오래된 버전, 버전을 읽을 수 없는 설치를 디스크에 늘어놓고 닿을 수 있는 호스트 없이 스크립트 전체를 돌려, 앞의 두 경우에만 내려받지 않고 맞추기만 하기를, 그리고 `-Force`가 청하면 내려받기를 요구한다 | 설치라고 해도 `Get-InstalledVersion`이 읽는 모양으로 만든 디렉터리이지 진짜 설치는 아니다. |
| 설치 관리자는 무엇을 건드리기 전에 잠금을 잡고, 버려진 잠금은 경합이 아니라 가져갈 것으로 본다 | UNIT TESTED | `tests/test_convergence.py:InstallerLockTests`(3개) | - |
| 제거는 자기가 만든 것만 지우고, 워처 상태를 알 수 없으면 중단하며, 따로 요청하지 않는 한 상태를 남긴다 | UNIT TESTED | `tests/test_cli.py:UninstallSafetyTests`(6개); `tests/test_installer.py:UninstallKeepsStateTests`(5개), `UninstallStatePreservationTests`(3개) | 실제 설치를 상대로 돌아 본 적이 없다. |
| 창에서 하는 설치 복구 | IMPLEMENTED | 7절 참고 | 다섯 결과가 확인되지 않았다. |

## 14. 상태 저장소

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 스키마 3을 만들고 검증한다. 손상된 파일, 더 새로운 스키마, 모르는 레코드 상태는 닫히는 쪽으로 실패하고 조용히 초기화되지 않는다 | UNIT TESTED | `tests/test_store.py:StoreTests.test_corrupt_database_fails_without_reset`, `test_newer_schema_and_unknown_record_state_fail_closed`, `test_existing_empty_state_is_never_silently_reset`, `test_invalid_settings_fail_closed` | - |
| 1에서 2, 2에서 3으로의 이전은 한 트랜잭션 안에서, 워처의 뮤텍스를 쥔 채로만 일어나고, 옛 파일의 사본을 먼저 남긴다 | UNIT TESTED | `tests/test_store.py:MigrationTests`(5개, `test_T37_open_without_migrate_is_refused_and_touches_nothing`, `test_T37_migration_preserves_every_row_and_backfills_the_chain`, `test_T19_T37_a_crash_during_migration_leaves_the_old_schema_or_the_new` 포함) | 이 문서를 쓴 기계에서 이전이 실제로 한 번 일어나기도 했다. 그 작업 나무에는 스키마 2 사본 `config/state.v2-backup-20260911T190545Z.sqlite`가, `events`와 `watcher_status` 표를 가진 스키마 3 `config/state.sqlite` 옆에 남아 있다. **읽는 사람은 그것을 확인할 수 없다.** `config/`는 의도적으로 추적하지 않으므로(`tests/test_repo_hygiene.py:RepositoryHygieneTests.test_no_copied_runtime_state_is_tracked`) 저장소를 복제해도 그 실행의 흔적은 없고, 이 문장이 기록의 전부다. |
| 이전이 끝나기 전까지는 자동화를 줄이는 동작만 듣는다 | UNIT TESTED | `tests/test_control_v3.py:UpgradeWindowTests.test_only_what_reduces_automation_works_until_the_old_watcher_stops`, `test_a_newer_state_is_never_called_damage` | Windows가 아니면 건너뛰고, 옛 릴리스 태그가 체크아웃에 없어도 건너뛴다. |
| 전이표는 평범한 이동만 허용하고, 전용 연산에 맡겨진 이동은 `update`에게 거절한다 | UNIT TESTED | `tests/test_store.py:TransitionTableTests`(8개, `test_T12_nothing_possibly_sent_returns_to_waiting_by_update`, `test_T12_validator_rejects_observing_without_its_proof` 포함) | - |
| 쓰기 도중의 크래시는 레코드를 온전히 남기거나 아예 남기지 않는다 | UNIT TESTED | `tests/test_store.py:CrashInjectionTests`(2개) | 크래시는 고른 지점에 주입한 것이지 프로세스를 죽인 것이 아니다. |
| 일지는 코드·id·계수·시각만 담고, 5,000건과 90일로 묶이고, 아직 돌고 있는 복구의 항목은 절대 버리지 않고, 사건 id를 다시 쓰지 않는다 | UNIT TESTED | `tests/test_store.py:JournalTests`(8개, `test_T44_pruning_keeps_the_story_of_every_record_still_running`, `test_T44_event_ids_are_never_reused`, `test_T39_a_foreign_journal_row_never_fails_an_open_or_a_read` 포함) | - |
| 같은 기다림에 다시 들어가면 한 번만, 같은 전이를 쓰는 둘이 있어도 한 번만 적히고, 거절된 변경은 아무것도 적지 않는다 | UNIT TESTED | `tests/test_store.py:JournalTests.test_T44_re_entering_the_same_wait_journals_once`, `test_T44_two_writers_of_the_same_transition_journal_once`, `test_T44_a_refused_change_journals_nothing` | - |
| 일지를 다시 읽어 무엇을 결정하는 곳은 없다 | UNIT TESTED | `tests/test_surface_properties.py:JournalIsWriteOnlyTests`(3개)가 엔진과 앱, 원본 읽기, 실패 분류가 `events()`를 결코 부르지 않기를, 그것을 부르는 모듈이 타임라인과 진단 내보내기 둘뿐이기를, 제어 계층의 그 한 번이 `timeline` 안에 있기를 요구한다 | 소스 모양 검사라서, 기대는 모양은 지키지만 새로운 방식으로 틀린 코드는 통과시킨다. |
| 통계: 구간, 중앙값, 다섯 건 이상일 때만 보이는 비율, 레코드마다 최종 결과 하나, 숨긴 행 포함 | UNIT TESTED | `tests/test_store.py:StatisticsTests`(4개) | - |
| 설정은 하나의 검증기를 지나 왕복하고, 손상되거나 지나치게 큰 파일은 기본값으로 읽히며, 임시 파일을 남기지 않는다 | UNIT TESTED | `tests/test_settings.py:PersistenceTests`(10개), `CoerceTests`(6개), `ValidateUpdateTests`(5개), `DescribeTests`(6개) | - |
| 세 인터페이스가 같은 검증기를 지나 같은 파일을 쓴다 | UNIT TESTED | `tests/test_control.py:SettingsSurfaceTests`(8개), `BridgeTests.test_a_value_written_by_the_bridge_is_what_the_control_layer_reads`; `tests/test_mcp.py:ToolSurfaceTests.test_the_settings_schema_is_generated_from_the_shared_fields`, `test_published_bounds_match_the_validator` | - |

## 15. 개인 정보와 안전 속성

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 복구 런타임은 네트워크 모듈을 import하지 않고, 네트워크에 닿는 배포 파일은 정확히 하나다 | UNIT TESTED | `tests/test_privacy_claims.py:CodePropertyTests.test_the_recovery_runtime_imports_no_networking_module`, `test_exactly_one_shipped_file_reaches_the_network` | `src/*.py`와 `scripts/*.py`를 덮는다. **`gui/*.cs`는 덮지 않는다.** |
| 분석이나 원격 측정 엔드포인트가 없고, 런타임이 Codex를 구동할 때 Codex 자신의 원격 측정도 끈다 | UNIT TESTED | `tests/test_privacy_claims.py:CodePropertyTests.test_there_is_no_analytics_or_telemetry_endpoint`, `test_the_runtime_disables_codex_own_telemetry_when_it_drives_it`; `tests/test_windows.py:BackendTests.test_queue_argv_exact_id_shell_disabled_and_no_telemetry` | Codex가 그 옵션을 지키는지는 여기서 확인하지 않고, 확인할 수도 없다. |
| 모든 기록 질의는 표지로 범위가 묶이고, 남의 행은 세기만 하고 읽지 않는다 | UNIT TESTED | `tests/test_source.py:StaticQueryTests.test_T11_content_is_marker_bounded_and_foreign_rows_are_counts`는 `src/codex_auto_resume/source.py`를 파싱해 그 안의 SQL 문자열 상수를 모두 꺼낸 뒤 정규식으로 표지 조건을 맞춰 본다. `test_T11_checker_catches_an_unbounded_query`는 하위 질의에만 걸린 조건을 그 검사기가 잡아낸다는 것을 보인다 | **이 검사는 소스를 읽을 뿐 데이터베이스를 열지도, 질의를 돌리지도 않는다.** 그래서 새로운 방식으로 틀린 질의는 그대로 통과할 수 있다. 정규식이 우연히 맞아떨어지는 조건, 검사기가 모르는 조인이나 표를 거쳐 나오는 내용, 하나의 문자열 상수가 아니라 조각을 이어 붙여 만든 SQL이 그렇다. 파싱하는 파일도 `source.py` 하나뿐이고, 질의가 실제로 무엇을 돌려주는지는 아무도 보지 않는다. |
| 프롬프트·응답·오류 문구는 로그에도, 일지에도, 응답에도 닿지 않는다 | INTEGRATION TESTED | `tests/test_engine.py:EngineScenarioTests.test_log_entries_never_contain_prompt_text`; `tests/test_failures.py:DetectionGateTests.test_no_error_text_survives_detection`; `tests/test_control_v3.py:HistoryAndStatisticsTests.test_the_timeline_is_content_free`; `tests/test_control.py:StopWatcherTests.test_every_reply_is_content_free` | `errors.log`는 이 제품이 쓰지 않은 예외 메시지를 일부러 싣는다. 개인 정보 문서가 그렇게 적고 있고, 진단 묶음에서는 걸러 내는 대신 가려 쓴다. |
| 사람에게 보이는 이름은 길이가 묶이고 여러 줄이 되지 않으며, 그것을 만들려고 프롬프트가 든 열을 읽지 않는다 | UNIT TESTED | `tests/test_failures.py:DisplayLabelTests`(2개), `IdentitySourceTests`(8개, `test_prompt_bearing_columns_are_never_read`, `test_extended_length_paths_do_not_leak_the_prefix` 포함) | - |
| 진단: 식별할 수 있는 것이 남지 않고, 별칭은 한 파일 안에서는 일관되고 파일끼리는 다르며, 기존 파일을 덮지 않는다 | UNIT TESTED | `tests/test_diagnostics.py:DiagnosticsTests`(4개) | 만들어 낸 로그를 상대로 돌 뿐, 실제 사고에서 나온 묶음을 상대로 하지 않는다. |
| 어디에도 셸이 없고, 어떤 값도 스크립트에 문자열로 들어가지 않는다 | REAL WINDOWS TESTED | `tests/test_pwsh.py:RealInterpreterTests`(2개, 진짜 PowerShell), `NoValueInScriptTests`(5개), `EnvironmentTests`(4개) | - |
| 소유한 경로는 갇혀 있고, 홈 밖으로 나가는 정션은 거절된다 | UNIT TESTED | `tests/test_cli.py:ConfinementTests`(3개); `tests/test_installer_ownership.py:PathConfinementTests`(7개) | - |
| GUI 자동화, 마우스·키보드 흉내, OCR, 화면 긁기, 접근성 API 조작을 쓰지 않는다 | UNIT TESTED | `tests/test_surface_properties.py:NoGuiAutomationTests`(2개)가 `gui/`, `src/`, `scripts/`, `install/`, `skills/` 아래 추적되는 모든 파일에서 `SendInput`, `keybd_event`, `mouse_event`, `SetCursorPos`, SendKeys, UI Automation, OCR, 화면 캡처를 거부하고, 저장소에 하나뿐인 화면 캡처인 `build/capture_window.ps1`(README의 그림을 만든다)이 릴리스 꾸러미 밖에 남아 있기를 요구한다 | 금지 목록이라 아무도 생각하지 못한 기법은 막지 못한다. 제품 안의 유일한 `user32` 호출은 `src/codex_auto_resume/tray.py`의 `SetForegroundWindow`로, 자기 창을 앞으로 가져오는 데 쓴다. |
| 한국어 문서는 최신이고, 영어 문서가 하지 않는 주장을 하지 않는다 | UNIT TESTED | `tests/test_korean.py:MappingTests`(6개, `test_no_translation_is_stale` 포함), `ClaimTests`(6개), `GeneratorTests`(6개) | - |
| 저장소 안에 실제 홈 디렉터리 이름이나 합성이 아닌 UUID가 없다 | UNIT TESTED | `tests/test_repo_hygiene.py:RepositoryHygieneTests`(5개) | - |

## 16. 빌드와 릴리스

| 기능 | 근거 등급 | 뒷받침하는 것 | 아직 없는 것 |
| --- | --- | --- | --- |
| 같은 소스로 두 번 빌드하면 PE 필드 정확히 두 개만 다르고, 정규화하면 실행 파일이 바이트까지 같아진다 | REAL WINDOWS TESTED | `tests/test_reproducible.py:RealCompilerTests`(7개)가 내장 C# 컴파일러로 진짜 실행 파일을 만들고 진짜 PE 바이트를 비교한다 | 컴파일러가 없으면 건너뛴다. 이제 기계 하나뿐은 아니다. GitHub 러너가 이번 릴리스로 발행한 압축 파일과, 이 문서를 쓴 기계에서 그 태그를 다시 빌드해 만든 압축 파일이 ZIP 전체로 바이트까지 같았고, 실행 로그를 보면 두 기계가 같은 내장 컴파일러 빌드를 썼다. 아직 한 번도 견주어 보지 않은 것은 서로 *다른* 컴파일러 빌드 둘이다. |
| 정규화한 프로그램이 그대로 돌고, 새로 넣은 MVID는 모듈 내용에서 나온다 | REAL WINDOWS TESTED | `tests/test_reproducible.py:RealCompilerTests.test_the_normalised_program_still_runs`, `test_the_mvid_depends_on_the_content`, `test_the_timestamp_is_the_fixed_value` | - |
| 릴리스 빌드는 모든 실행 파일을 정규화하고, 두 번 빌드해서 재현 가능함을 증명한다 | UNIT TESTED | `tests/test_reproducible.py:BuildScriptTests`(3개) | `build/make_gui.ps1`과 워크플로에 대한 소스 확인이고, 릴리스 실행을 다시 돌려 보지는 않는다. |
| 두 실행 파일이 플러그인 매니페스트에서 만든 버전 자원을 싣는다 | REAL WINDOWS TESTED | `tests/test_reproducible.py:VersionResourceTests`(4개)가 `build/make_gui.ps1`을 실제로 돌린 뒤, 탐색기의 속성·자세히가 쓰는 바로 그 호출로 빌드된 두 파일에서 자원을 읽어 온다. `BuildScriptTests.test_the_executables_carry_a_version_resource_from_the_manifest`는 스크립트 자체를 본다 | 내장 컴파일러가 없으면 건너뛴다. 사람이 그 탭을 직접 열어 본 적은 없다. 이번에 발행된 실행 파일들은 내려받은 압축 파일에서 같은 방식으로 읽어 보았고, 둘 다 매니페스트가 말하는 버전과 `Codex Auto Resume`를 답했다. |
| 이번 릴리스는 태그에서 다시 빌드해 견주어 볼 수 있는 첫 릴리스다 | PUBLISHED | 발행된 압축 파일을, 그것을 발행한 기계가 아닌 다른 기계에서 그 태그를 새로 복제해 다시 빌드했고, ZIP 전체가 바이트까지 같았다. 양쪽 다 `791e9248…faf8fbc3`였고, 실행 파일 둘도 릴리스 실행이 찍어 둔 해시와 일치했다. 두 도구 사슬은 [`docs/evidence/reproducible-build-2026-09-13.json`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/evidence/reproducible-build-2026-09-13.json)에 적혀 있고, 실험 자체는 [VERIFY.ko.md](VERIFY.ko.md)가 적고 있다 | **기계를 건너, 같은 컴파일러 빌드로, 바이트까지 같음을 한 번 측정했다.** 릴리스 실행 로그에 러너의 컴파일러가 찍혀 있고 다시 빌드한 기계의 것과 같은 빌드였다. 그러니까 이 비교는 [VERIFY.ko.md](VERIFY.ko.md)가 결과를 좌우한다고 말하는 그 변수를 바꾸지 않았다. 기계와 Windows 빌드는 바꾸었다. 서로 다른 컴파일러 빌드 둘은 아직 견주어 본 적이 없으므로, 아직 "어떤 Windows 기계에서나 재현된다"는 아니다. |
| 모든 외부 액션이 전체 커밋으로 고정되고, 어느 릴리스인지 이름이 붙고, 어디서나 같은 커밋으로 고정된다. Dependabot이 갱신을 제안한다 | UNIT TESTED | `tests/test_workflow_pins.py:ActionPinTests`(6개), `ParserTests`(3개) | - |
| 최상위에는 쓰기 권한이 없고, 빌드 작업은 쓸 수 없고, 게시 작업은 저장소 코드를 돌리지 않고, 태그 푸시만 게시한다 | UNIT TESTED | `tests/test_workflow_privilege.py:WorkflowPrivilegeTests`(8개), `KoSyncPrivilegeTests`(2개), `YamlShapeTests`(1개) | 워크플로 파일 확인이고, 실행을 다시 돌려 보지는 않는다. |
| 공개된 버전의 자산은 덮어쓸 수 없고, 수동 실행으로는 게시할 수 없다 | UNIT TESTED | `tests/test_convergence.py:ReleaseImmutabilityTests`(5개) | 릴리스 자체는 GitHub의 불변 릴리스가 아니다. 이 규칙은 워크플로를 묶을 뿐 쓰기 권한을 가진 모두를 묶지 않는다. [VERIFY.ko.md](VERIFY.ko.md)가 그렇게 적고 있다. |
| 릴리스 워크플로는 게시 전에 테스트를 돌리고, 매니페스트와 어긋나는 태그를 거절하고, 게시된 체크섬을 확인한다 | UNIT TESTED | `tests/test_plugin.py:ReleaseWorkflowTests`(6개) | - |
| 현재 버전은 한 곳에만 있고, 변경 기록이 그 버전으로 시작한다 | UNIT TESTED | `tests/test_plugin.py:VersionConsistencyTests`(4개), `ReleaseNotesTests`(6개); `tests/test_privacy_claims.py:WordingTests.test_no_released_version_has_lost_its_changelog_section` | - |
| 공개된 압축 파일은 해시로, 릴리스 페이지로, `main`에 고정된 해시로, 그리고 v0.5.4부터는 빌드 증명으로 확인된다 | PUBLISHED | [VERIFY.ko.md](VERIFY.ko.md); `scripts/release.json`; `tests/test_convergence.py:ReleaseManifestTests.test_every_released_version_is_pinned`, `test_digests_are_absent_or_real` | 이번 릴리스에서는 발행된 압축 파일을 빌드 바깥에서 내려받아 해시했고, 그 한 숫자가 옆에 함께 발행된 사이드카와도, GitHub이 그 자산에 대해 알려 주는 해시와도, 빌드 증명의 대상과도 일치했다. 그 증명은 `.github/workflows/release.yml`과 이 저장소와 `refs/tags/`의 그 태그를 가리킨다. 그다음 증명의 서명 자체를 GitHub 바깥에서 암호학적으로 검증했다. GitHub CLI가 아니라 `sigstore-python`으로, Fulcio 잎 인증서 키로 DSSE 서명을, Sigstore 뿌리까지의 인증서 사슬을, 내장된 인증서 투명성 타임스탬프를, Rekor 포함 증명과 서명된 체크포인트를 확인했고, 각 검사가 거절해야 할 것을 거절하는지 변조 대조 아홉 가지로 보였다. [`docs/evidence/attestation-verified-2026-09-13.json`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/evidence/attestation-verified-2026-09-13.json)이 그것을 기록하고 있고, 여전히 보여 주지 못하는 것도 함께 적혀 있다. Sigstore 뿌리는 처음 쓸 때 그대로 믿었고, 번들에는 별도의 타임스탬프 기관이 없으며, 증명은 빌드 감사가 아니다. |
| 브랜드 자산과 아이콘이 원본에서 생성되고 최신 상태로 유지된다 | UNIT TESTED | `tests/test_brand.py:GeneratedFileTests`(4개), `PaletteTests`(4개), `SurfaceTests`(6개) | - |
| 라이브 인수 기록은 기록다울 때만 받아들여진다. 빠진 필드, 관측한 것 없는 pass, 날것의 대화 id, 경로, 전자우편 주소, 검사기가 모르는 단계, 매니페스트와 다른 버전, 한 단계를 두고 엇갈리는 두 파일은 모두 거절된다 | UNIT TESTED | `scripts/live_evidence.py`를 `tests/test_live_evidence.py:WellFormedTests`(4개), `RefusalTests`(19개), `DirectoryTests`(10개), `DocumentTests`(7개)가 구동한다. 마지막 것은 [LIVE_ACCEPTANCE.ko.md](LIVE_ACCEPTANCE.ko.md)와 그 영어 원본, 그리고 검사기가 같은 단계와 같은 기록 항목을 말하도록 묶는다 | 검사기가 보는 것은 사람이 쓴 것의 모양과 그 어휘뿐이다. 그 일이 실제로 일어났는지는 확인할 수 없고, 스스로도 그렇게 적고 있다. |
| 라이브 인수 절차 자체 - 설치, 워처, 대시보드, 실제 중단, 취소, 지금 재시도, 시도 되돌려주기, 일시 중지, 업그레이드, 복구, 제거를 실제 기계에서 실제 Codex를 상대로 | UNVERIFIED | [LIVE_ACCEPTANCE.ko.md](LIVE_ACCEPTANCE.ko.md)가 단계마다 무엇을 증명하는지, 무엇을 하는지, 통과가 어떤 모습인지, 무엇을 적어야 하는지를 말한다. 기록이 들어갈 곳은 `docs/evidence/live/`다 | **아무도 돌려 보지 않았다.** `docs/evidence/live/`에는 `README.md`와, 아무것도 기록하지 않고 어떤 단계로도 세지 않는 `example.json`만 있어서, 이 나무에서 `python scripts/live_evidence.py`는 아직 인수된 것이 없다고 찍고 2로 끝난다. Codex 안에서 지켜본 적이 없다고 적힌 이 문서의 모든 항목이 이 절차를 기다리고 있다. |

---

## 근거가 가장 얇은 곳

이 제품이 한다고 말하지만 저장소 안의 무엇도 실행해 보지 않는 기능들입니다. 잘 덮인 항목들 사이에
묻히지 않도록 따로 모아 둡니다.

| 기능 | 등급 | 등급을 올릴 가장 작은 일 |
| --- | --- | --- |
| 창의 "빈 목록이 아니라 읽을 수 없음" | REAL WINDOWS TESTED, 그림 없이 | 브리지를 일부러 실패시키고 대기 중 쪽을 한 장 캡처. |
| 5초 갱신 | IMPLEMENTED | 그것을 재는 무엇이든. |
| 실제 로그인에서의 실제 `Run` 키 | UNIT TESTED, 가짜 레지스트리 | Windows 로그인 뒤에 담은 `logs/launcher.log`. |
| 실제 프로토콜 등록과 실제 알림 클릭 | UNIT TESTED, 가짜 레지스트리 | 위와 같은 것에, 활성화 기록을 더한 것. |
| 라이브 인수 절차 | UNVERIFIED | 누군가 실제 기계에서 [LIVE_ACCEPTANCE.ko.md](LIVE_ACCEPTANCE.ko.md)의 절차를 돌리고, 그 결과 파일을 `docs/evidence/live/` 아래에 커밋하기. |
| Codex 안에서 본 것이 무엇이든 | - | 이 제품이 Codex 안에서 일하는 것을 지켜본 사람이 없다. 누군가 지켜보고 저장소가 그것을 기록하기 전까지, 이 문서의 어떤 항목도 REAL CODEX VISUALLY TESTED라고 말할 수 없다. |

## 읽는 사람이 가져가야 할 것

근거가 가장 두꺼운 쪽은 복구 엔진입니다. 감지, 관문, 턴 대응, 결과 판정, 예산은 모두 제품이 쓰는
질의 계층을 지나 진짜 Codex 모양의 데이터베이스를 상대로 처음부터 끝까지 구동되고, 설계 전체가
딛고 선 세 가지 사실 - 사용량 한도의 모양, 열려 있는 대화로의 전달, 닫혀 있는 대화로 전달되지
않음 - 은 2026-09-06에 실제 Codex를 상대로 측정되어 `docs/evidence/` 아래에 공개되어 있습니다.

가장 얇은 쪽은 표면입니다. 창의 여섯 쪽은 진짜 코드지만 캡처는 셋뿐이고, 알림 영역 아이콘은 단
하나의 테스트에서 딱 한 번 진짜로 만들어졌다 사라질 뿐 그림 한 장 없으며, Codex 패널은 Codex가
한 번도 불러온 적이 없습니다. 표면이 제어 계층과 이야기하는 곳에서는, 제어 계층은 잘 시험되어
있고 표면 쪽 절반은 대개 그렇지 않습니다.

그리고 아무도 지켜보지 않았습니다. 정직하게 요약하면 이렇습니다. 조심스럽게 시험된 프로그램이지만,
이 저장소가 기록하는 한, 아직 아무도 앉아서 이것이 대화를 이어 놓는 것을 지켜본 적은 없습니다.
