# Codex auto-resume — 조사 및 Phase 2 진행 기록

작성일: 2026-09-06 (Asia/Seoul)

## 현재 판정 (2026-09-06 22:05 KST, Claude Code — Phase 3 구현 완료)

**Phase 3 구현 완료.** 로드된 스레드 자동 재개 + 미로드 스레드 안전 대기 범위를 모두 구현하고 테스트했다.
전체 단위 테스트 **123개 통과**(실환경 opt-in 6개 제외 117개 + 실환경 read-only 6개), 실환경에서 watcher
수명주기(단일 인스턴스 BUSY 종료코드 3, stop, uninstall)까지 검증했다. 어떤 실제 대화에도 메시지를
보내지 않았다. 아래 Phase 1/2 기록은 검증된 사실로 유지한다.

### 구현 상태

- **완성한 모듈**: `source.py`(읽기 전용 감지), `store.py`(durable 상태), `windows.py`(어댑터 + 단일
  인스턴스 mutex + StopEvent), `engine.py`(스케줄러), `config.py`(경로/바이너리 탐색), `logbook.py`(회전
  로그, 기밀 미기록), `startup.py`(HKCU 자동시작), `app.py`(watcher 루프), `cli.py`(enable/disable/status/
  pending/cancel/logs/run/stop/install/uninstall/doctor), `src/auto_resume.py`(진입점).
- **테스트**: `test_source`(24), `test_store`(19), `test_windows`(28), `test_engine`(필수 시나리오 18 +
  crash/uncertainty), `test_cli`(CLI/config/logging/startup), `test_integration_live`(실환경 read-only, opt-in).
- **문서**: `README.md`(맨 위 미로드 제한 명시), `SECURITY.md`(보안 검토).

### 이전 코드 대비 변경 및 이유

1. **`collect()` 치명 버그 수정**(1·2차 리뷰 최상위 확인): `detect()` 출력을 그대로 `store.register()`에
   넘겨 `status/error_info` 여분 키 때문에 항상 StoreError → 어떤 중단도 등록/재개되지 않았다. 등록에
   필요한 9개 필드만 투영하도록 수정. 실환경에서도 "detection skipped" 로그로 재현됨.
2. **진입점 종료코드 버그 수정**: `auto_resume.py`가 `main()`을 호출만 하고 `sys.exit`하지 않아 단일
   인스턴스 BUSY(3) 등 종료코드가 항상 0이 됐다. `sys.exit(main())`로 수정, 실환경에서 3 확인.
3. **backoff 고정**: 30s→1m→2m→5m→이후 5m (`BACKOFF_LADDER`).
4. **enable 이전 실패 lookback**: 기본 6시간, `--lookback-hours`/`settings.json`으로 조정.
5. **reconcile 안전화**(리뷰 #5): 큐 항목 삭제는 확정 `notLoaded`/만료/무효/비허용에서만. 앱 인벤토리
   일시 부재는 `notLoaded`가 아니라 `unknown`으로 취급 → 일시적 문제로 큐 항목을 삭제하지 않음.
6. **submission_unknown/cleanup에 backoff delay**(리뷰 #2): 무delay 재조정으로 매 틱 app-server를
   spawn하던 문제 제거(300/900s).
7. **일일 제출 상한 완화**(리뷰 #6): 영구 `failed` 대신 24h 창이 지나면 재시도하는 `waiting_retry`.
8. **writer lock 간섭 제거**(리뷰 #7/#10): `loaded()`가 Restart Manager로 소유자를 먼저 확인하고,
   서버가 파일을 이미 연 경우에만 byte-lock을 관찰(획득하지 않음). 빈 인벤토리는 `notLoaded`.
9. **PowerShell OEM 인코딩 수정**(리뷰 #9): 인벤토리 스크립트에 UTF-8 콘솔 출력 강제(비ASCII 프로필 경로).
10. **transient 파일 오류 대응**(리뷰 #3/#11): `_metadata(strict=True)`로 `latest()`의 일시적 rollout I/O
    오류를 SourceError로 올려 엔진이 supersede하지 않고 대기하게 함. detection 경로는 스킵.
11. **reset hint 임계값**(리뷰 #12): fallback codex primary 힌트는 used_percent≥90일 때만 채택.

### 리뷰

- 1차(핵심 4모듈): 확인 12건 → 전부 수정. 6건은 반증(무효).
- 2차(신규/변경 모듈): 확인 3건 → 전부 수정. 반증 0건.
  1. **NTFS junction confinement**(medium): 소유 디렉터리 가드가 `is_symlink()`만 확인해 junction(관리자
     불필요)으로 `config/`·`logs/`를 홈 밖으로 리디렉션하면 홈 밖에 상태를 쓰거나 uninstall이 무관한
     사용자 파일을 지울 수 있었다. `Paths.confined()`(resolve 후 홈 포함 여부)로 `ensure()`,
     `owned_state_files/owned_log_files`, uninstall 삭제 루프를 모두 확정 검사하도록 수정.
  2. **settings 임시 파일**(low): 고정 이름 `.tmp` + write_through/경합. `tempfile.mkstemp`(O_EXCL)로
     고유 생성하고, replace 실패를 `ConfigError`로 감싸고, 실패 시 임시 파일 정리. 잔여 temp도
     uninstall 대상에 포함.
  3. **watcher poll 간격 읽기가 crash-guard 밖**(medium): 간격 계산의 `store.settings()`가 try/except
     밖이라 일시적 StoreError가 watcher를 종료시켰다. `_poll_interval()`로 추출해 실패 시 안전한 기본값
     으로 폴백(루프 미종료).

### 검증 요약 (최종)

- 단위/시나리오/CLI 테스트 **127개 통과**(+ 실환경 read-only 6개 opt-in 통과). junction 가드 테스트는
  실제 `mklink /J`로 검증됨.
- 실환경: doctor 정상, 앱 페어링/loaded 분류 정확(없는 스레드는 notLoaded), 사용량 필드 미유출,
  단일 인스턴스 BUSY(3), stop, uninstall(소유 파일만 삭제) 확인. 어떤 실제 대화에도 전송하지 않음.

**결론: Phase 3 완료.** 요구된 완료 조건(watcher/detector/exact-thread/reset waiting/loaded 감지/loaded
continuation/notLoaded 안전 대기/중복 방지/persistent state/restart recovery/multi-thread/backoff/
enable·disable·status·pending·cancel·logs/single-instance/optional startup/clean uninstall/자동 테스트/
disposable read-only 통합/README/PROGRESS/보안 검토)을 모두 충족했다.

---

## (Phase 2 시점) 현재 판정

**Phase 2 검증 완료 — 전체 판정 FAIL (요구사항 미충족).** 로드된 desktop-app 스레드 전달은 **PASS**, 실제 앱 재시작 후 미로드 스레드 전달은 **FAIL**입니다. 미로드 상태에서 90초간 관찰한 메시지는 큐에만 남았고 같은 대화의 userMessage/turn에 들어오지 않았습니다. 테스트 큐 항목을 공식 API로 삭제했고 잔여 항목 0을 확인했습니다. Watcher, startup task, 서비스, 자동 재개 시스템은 구현하거나 설치하지 않았습니다.

현재 작업 디렉터리와 `work/`, `outputs/`에서 기존 `PROGRESS.md`를 찾지 못했습니다. 이전 턴은 이 파일을 저장하기 전에 사용량 제한으로 중단됐습니다. 이 파일은 기존 대화의 도구 결과와 현재 로컬 상태를 대조해 새로 만든 체크포인트입니다.

## 완료한 Phase 1 — 반복하지 않을 조사

- Windows 앱 패키지: `OpenAI.Codex_26.901.5280.0_x64__2p2nqsd0c76g0`.
- 앱 실행 파일: `C:\Program Files\WindowsApps\OpenAI.Codex_26.901.5280.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe`.
- 설치된 실행 엔진: `C:\Users\ExampleUser\AppData\Local\OpenAI\Codex\bin\27d6a192e9c98618\codex.exe`, 버전 `0.153.4`.
- 최초 조사 PID: ChatGPT main `30492`, 그 자식 app-server `22280`. 재시작 시험에서는 PID뿐 아니라 실행 경로와 생성 시각을 재검증합니다.
- 실제 실행 인자는 `app-server --analytics-default-enabled`이며 `--listen`이 없습니다. 기본 stdio 연결입니다. 해당 프로세스들이 소유한 TCP listener는 관찰되지 않았습니다.
- 설치 패키지의 `app.asar`, `.vite/build/src-VqXTPopo.js`에서 child stdio pipe 연결과 Windows의 shared-daemon 경로 제외를 확인했습니다. 앱 파일은 수정하지 않았습니다.
- 별도의 app-tools named pipe는 존재하지만 내부 API입니다. 외부 제어 경로로 사용하지 않았습니다.
- `codex app-server daemon version`은 이 빌드에서 Unix-only lifecycle 오류를 반환했습니다. 예상 control socket 파일도 없었습니다. `proxy` 연결 시험은 OS 오류 10050으로 실패했으므로 이것만으로 모든 Windows socket 지원이 없다고 단정하지 않습니다.
- 같은 사용자 Codex 저장소는 `C:\Users\ExampleUser\.codex`입니다. thread metadata는 `state_5.sqlite`, paginated turn/item history는 `thread_history_1.sqlite`, 큐는 `queue_1.sqlite`, goal 상태는 `goals_1.sqlite`에 있습니다. JSONL rollout과 thread UUID writer lock도 존재합니다.
- 현재 조사 thread UUID: `0a1b2c3d-0101-7000-8000-000000000101`. 저장된 originator는 `Codex Desktop`, source는 `vscode`, history_mode는 `paginated`입니다. `source=vscode`만으로 실제 생성 UI를 판정하면 안 됩니다.
- 설치 바이너리로 protocol schema를 생성해 `work/protocol-schema`에 보관했습니다.
- 공식 소스의 설치 버전 대응 태그 `rust-v0.153.4` commit은 `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`입니다. 관련 소스만 `work/official-research`에 있습니다. 최신 main 소스와 설치 태그 소스를 혼동하지 않습니다.

## Phase 2A — 앱에 로드된 스레드: PASS

전용 테스트 task: **Auto-resume disposable protocol test**

정확한 UUID: `0a1b2c3d-0103-7000-8000-000000000103`

이 task는 공식 desktop-app `create_thread` 도구로 생성했으며 실제 연구 저장소를 사용하지 않습니다.

1. 준비 턴 ID는 **`0a1b2c3d-0104-7000-8000-000000000104`**입니다. 응답은 `AUTO_RESUME_POC_READY`, 상태는 `completed`입니다.
2. 외부 PowerShell에서 설치된 공식 CLI로 다음 한 번의 명령을 실행했습니다. 재시도하지 않았습니다.

   `codex -c analytics.enabled=false queue --thread 0a1b2c3d-0103-7000-8000-000000000103 --message "Disposable protocol test only. Reply exactly AUTO_RESUME_POC_QUEUE_ACK and then stop. Do not call tools, inspect files, browse, or change anything."`

3. CLI는 queue item `0a1b2c3d-0105-7000-8000-000000000105`을 **위 UUID**에 저장했다고 반환했습니다.
4. 같은 desktop-app task를 공식 `wait_threads`로 읽어 새 턴 **`0a1b2c3d-0107-7000-8000-000000000107`**, `completed`, 응답 **`AUTO_RESUME_POC_QUEUE_ACK`**를 확인했습니다.
5. 중단 후 재검증에서도 같은 UUID의 `thread_items`에 표식을 포함한 **userMessage와 agentMessage 둘 다** 존재합니다. 테스트 큐 잔여 항목은 0입니다. 따라서 CLI의 접수 문구만으로 성공을 판정한 것이 아닙니다.
6. 이번 재개 시 앱 도구가 이 task를 `idle`로, 다른 미로드 task를 `notLoaded`로 구분해 반환했습니다. 성공한 warm 전송은 반복하지 않았습니다.

이 결과는 **앱이 이미 소유하고 로드한 스레드에 대한 정확한 대화 전달**을 증명합니다. 외부 프로세스가 앱의 stdio 서버에 직접 attach하거나 `thread/resume`을 실행했다는 의미는 아닙니다.

## Phase 2B — 실제 앱 재시작 후 미로드 스레드

<!-- COLD_RESULT -->

- 검증 완료: **2026-09-06 08:00 KST**
- Cold test: **FAIL — 미로드 상태에서 90초 동안 실제 대화로 전달되지 않음**
- 큐 항목: `0a1b2c3d-0108-7000-8000-000000000108`
- 접수 시각: **07:58:40 KST**. 관찰 종료: **08:00:10 KST**.
- 상태: 공식 앱 `list_threads`가 전송 전/관찰 중 **`notLoaded`**, 종료 후 `read_thread`도 **`notLoaded`**를 반환했습니다.
- 대화 확인: 같은 UUID에 기존 턴 2개만 존재. cold 표식의 userMessage/agentMessage/새 turn은 **0개**.
- 정리 결과: **`thread/queue/delete` 성공**, 테스트 큐 잔여 항목 **0개**.
- 최종 전달 증거: `phase2-cold-delivery-evidence.json` 및 `phase2-app-confirmation.json`.
- Phase 2 전체: **FAIL — watcher 구현 단계로 진행하지 않음**.

<!-- /COLD_RESULT -->

실제 재시작 및 중단 복구:

1. 일회성 WMI helper PID `10488`이 기존 앱 main `30492`를 종료했습니다. 기존 Codex `22280`도 종료됐습니다.
2. 이미 종료된 Codex 프로세스의 경로 확인에서 helper가 `process_path_query_failed`로 중단했습니다. 이때 **cold 큐 전송은 아직 하지 않았습니다**. 복구 경로가 앱을 다시 실행했습니다.
3. 새 앱 main **`4048`**의 생성 시각은 **07:40:31 KST**, 부모는 helper **`10488`**입니다. 새 Codex app-server **`14684`**는 **07:40:35 KST**에 생성됐습니다. 따라서 단순히 미로드를 흉내 낸 것이 아니라 실제 app/server 프로세스 교체를 확인했습니다.
4. 사용자가 이 조사 task에서 상태를 물은 뒤, 테스트 task를 열지 않은 채 나머지 실험을 이어갔습니다. **두 번째 앱 재시작은 하지 않았고 warm 메시지도 반복하지 않았습니다.**
5. 07:57 공식 앱 목록이 테스트 UUID를 `notLoaded`로 반환했고 writer lock도 없었습니다. 이 조건에서 07:58:40 단 한 번 cold 메시지를 큐에 넣었습니다.
6. 90초 동안 저장한 30개 snapshot 모두 writer가 없고, 메시지는 자기 큐 항목에만 존재하며, 대화의 turn/item은 바뀌지 않았습니다. 08:00:10 최종 snapshot을 추가로 확인한 뒤 항목을 삭제했습니다.
7. 08:00 공식 앱 `read_thread` 재확인에서도 같은 task 제목/UUID, `notLoaded`, 이전 warm 메시지 및 응답만 확인됐습니다. UI scraping이나 화면 자동화는 사용하지 않았습니다.
8. 초기 재시작 단계의 `INCONCLUSIVE` 기록은 `phase2-cold-evidence.json`에 보존합니다. 이것은 최종 cold 전달 판정 파일이 아닙니다. 최종 판정은 `phase2-cold-delivery-evidence.json`입니다.

실험 코드의 종료된 process-handle 처리 오류는 수정했고, PID 재사용 방어를 유지하는 회귀 테스트를 포함해 **안전성 테스트 10개 통과**를 확인했습니다. 이 수정 뒤 앱 재시작 시험을 반복하지 않았습니다.

시험 절차:

사전 검증(07:30 KST): warm writer lock 보정 성공, 설치 버전/저장소 일치 확인, 공식 stdio `initialize` 및 `thread/queue/list` 읽기 검증 성공. 최초 안전성 테스트 6개에 종료된 프로세스 관련 회귀 검사 4개를 추가해 최종 10개가 통과했습니다. 이러한 코드 검사는 실제 app restart 결과를 대체하지 않습니다.

- 일회성 helper의 앱과 독립된 실행 경로를 확인한 후에만 재시작합니다. 최초 detached/breakaway 실행은 Job membership 때문에 보수적으로 중단했으며 앱 종료/큐 전송은 없었습니다. 추가 읽기 검사에서 **로컬 WMI가 생성한 프로세스의 부모는 `WmiPrvSE.exe`, 동일 사용자 profile, job flags는 `6144`, `KILL_ON_JOB_CLOSE=false`**임을 확인했습니다. 재시작 실험은 이 별도 WMI 프로세스 경로를 사용하고 실제 helper에서 같은 조건을 재검증합니다. 단순히 `in_job=true`라는 사실만으로 앱 종료 때 같이 종료된다고 단정하지 않습니다.
- 현재 앱 main PID/생성 시각/실행 경로와 그 자식 Codex PID를 확인합니다. 다른 작업으로 확장되는 process-tree kill은 사용하지 않습니다.
- API로 정상 종료할 수 있는 안정된 경로가 조사되지 않아, 이 시험은 **지정 프로세스 종료 후 동일 앱 실행 파일을 시작하는 재시작**입니다. 메뉴를 통한 graceful quit 시험이나 Windows reboot 시험으로 표기하지 않습니다.
- 앱 종료는 현재 조사 턴도 끊을 수 있습니다. 독립 helper가 결과를 이 파일과 `phase2-cold-evidence.json`에 저장한 뒤 종료합니다. 이 조사 스레드에 continuation을 자동 전송하지 않습니다.
- 새 ChatGPT main과 그 자식 Codex app-server 생성이 확인돼야 진행합니다.
- 테스트 thread의 writer lock 검사를 warm 상태에서 먼저 보정합니다. 기존 lock 파일을 읽기 권한으로만 열고, 비차단 byte lock을 즉시 풀며 파일 내용을 읽거나 쓰거나 생성하거나 삭제하지 않습니다. free/absent는 writer가 없는 시점의 증거이며 UI 표시 여부 자체를 증명하는 것은 아닙니다. 이 검사는 구현 세부에 의존합니다.
- 테스트 task를 열지 않은 상태로 cold 조건을 확인합니다. 앱이 자동으로 이 task를 로드했으면 `INCONCLUSIVE`로 중지하고 메시지를 보내지 않습니다.
- 정확히 한 번 `codex queue --thread <위 UUID>`로 고정 harmless 표식 `AUTO_RESUME_POC_COLD_ACK_20260906`을 보냅니다. CLI timeout도 재전송하지 않습니다.
- 최대 90초 동안 해당 UUID의 turn/item과 해당 테스트 큐 항목만 읽기 전용으로 관찰합니다. 같은 UUID의 userMessage 기록을 전달 증거로 사용합니다. 큐 접수만으로는 성공이 아닙니다.
- 아직 남아 있는 **자신의 고정 표식/UUID에 해당하는 큐 항목만** 공식 `thread/queue/delete`로 제거합니다. SQLite 직접 수정은 하지 않습니다.
- 미로드 상태에서 90초 동안 큐에만 남는 경우는 `FAIL`입니다. 이는 나중에 수동으로 스레드를 로드해도 영원히 전달되지 않는다는 주장이 아닙니다.

## 실제 사용량 제한 샘플

- 조사 스레드의 실패 턴: `0a1b2c3d-0102-7000-8000-000000000102`.
- 완료/오류 기록 시각: **2026-09-06 02:12:29 KST**.
- DB 상태: **`failed`**, `error_json.codexErrorInfo`: **`usageLimitExceeded`**.
- 원본 rollout 이벤트: **`task_complete`에 error가 포함됨**, `error.codex_error_info`: **`usage_limit_exceeded`**. 이벤트 이름 `task_complete`만 보고 정상 완료로 분류하면 안 됩니다.
- 오류 표시에서 시간 구절만 보존: **`try again at 7:03 AM`**.
- 실패 직전의 `codex` 한도 snapshot: `used_percent=98`, window 300분, **`resets_at=1788645827` → 2026-09-06 07:03:47 KST**. 표시 시각과 **분 단위로 일치**합니다. 07:03:00과 정확히 같은 초 단위 timestamp는 아닙니다.
- weekly snapshot의 used_percent는 34였습니다.
- 오류 바로 전 `premium` snapshot에는 primary/secondary/reset 값이 없습니다. 오류 자체에도 blocking bucket ID나 numeric reset은 없습니다. 따라서 기본 `codex` bucket이 실제 차단 원인이었다고 단정할 수 없습니다.
- 새 사용 창의 현재 reset 값은 위 과거 실패의 reset 검증에 사용하지 않았습니다.
- 정제된 증거: `limit-sample.json`. 프롬프트, tool output, 인증정보를 내보내지 않았습니다.

## 남아 있는 안전/호환성 제약

- 공식 queue 소스는 저장소 변경을 약 10초마다 감지하지만 **이미 로드된 thread ID들만** 대상으로 삼습니다. 실제 cold 시험에서도 큐 접수는 스레드를 로드하거나 턴을 시작하지 않았습니다.
- 사용자 취소된 스레드에는 큐를 즉시 실행하지 않지만, 저장된 큐 항목이 나중에 로드될 때 실행될 가능성을 고려해야 합니다.
- queue/add에는 “latest failed turn ID가 아직 X일 때만 전송”이라는 원자적 조건이 없습니다. client message ID를 자동 중복 제거 키로 간주하면 안 됩니다.
- `usageLimitExceeded`는 여러 quota/usage 오류가 합쳐진 코드입니다. enum 하나만으로 재설정 가능한 사용량 제한을 확정해서는 안 됩니다.
- 공식 프로토콜의 존재와 **현재 desktop-owned 인스턴스에 접속할 수 있음**은 별개의 조건입니다.
- 이번 결과로 watcher 안전성, reboot, cancellation race, 즉시 disable/kill switch, 중복 재개 방지까지 검증됐다고 주장하지 않습니다.

## 보안 및 변경 범위

앱/Codex 바이너리, 앱 설정, 인증 파일, 다른 연구 저장소를 수정하지 않았습니다. auth.json, token, cookie, process memory는 읽지 않았습니다. 관리자 권한이나 startup 등록은 요구하지 않습니다. CLI 실험은 analytics를 명시적으로 끕니다. 원래 Codex가 OpenAI에 정상 모델 요청을 보내는 동작과 외부 watcher가 데이터를 업로드하는 동작을 구분합니다. 실험의 고정 harmless 메시지는 원래 인증된 Codex 경로로 처리됩니다.

조사 코드는 `work/phase2/`에 있고 설치된 도구가 아닙니다. 이번 실험은 예약 파일로 중복 실행을 막으며, 상시 프로세스/서비스/자동 재개 루프를 만들지 않습니다. 재시작 helper와 cold 전달 시험 프로세스는 종료됐습니다. 앱과 Codex의 새 정상 프로세스는 실행 중입니다.

## 다음 단계 판단

**현재 `codex queue` 기반 설계로 전체 자동 재개 시스템을 만들지 않습니다.** 요구한 두 상태 중 미로드 상태에서 exact-thread continuation이 실행되지 않았기 때문입니다. 현재 Windows desktop-owned stdio 인스턴스에 외부에서 안전하게 붙어 task를 로드하는 지원 경로도 입증되지 않았습니다.

스레드를 수동으로 열면 대기 큐가 나중에 처리될 가능성은 이 요구사항의 무인 재개 성공과 다릅니다. 이번 시험에서는 그 잠재적 지연 실행을 방지하기 위해 항목을 삭제했습니다. 비공개 pipe, 앱 패치, GUI 자동화로 우회하지 않습니다. 후속 구현은 지원되는 외부 exact-thread 로드/재개 경로를 별도 검증한 뒤에만 재검토할 수 있습니다.

## 공식 근거

- [공식 app-server 문서](https://learn.chatgpt.com/docs/app-server)
- [설치 버전의 CLI queue 구현](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/tui/src/session_queue_commands.rs)
- [설치 버전의 외부 큐 변경 감지/dispatch](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/ext/queue/src/service.rs)
- [설치 버전의 큐 protocol 처리](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/thread_queue_processor.rs)
- [설치 버전의 thread writer lock](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/thread-store/src/local/writer_lock.rs)
- [Windows의 로컬 프로세스 생성 API](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/create-method-in-class-win32-process)
