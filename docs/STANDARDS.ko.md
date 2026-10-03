# 기준

이 제품이 지키는 기준을 id별로 적었습니다. **표준판**은 0군과 A~J군의 기준을 모두 지킵니다. **고급판**은
표준판에, 그 가운데 적어도 하나를 일부러 벗어나는 기능들을 더한 것입니다. 기능마다 벗어나는 기준을 밝히고,
사람이 설명을 읽고 대시보드에서 켜기 전까지는 모두 꺼져 있습니다([EDITIONS.ko.md](EDITIONS.ko.md)). K군은
고급판 자체의 기준으로, 모든 기능이 지키며 어떤 기능도 벗어날 수 없습니다.

기준마다 어떻게 지켜지는지 적었습니다.

- **테스트** - 기준이 깨지면 테스트가 실패합니다. 그 테스트 이름을 적었습니다.
- **코드** - 코드가 지키지만, 아직 확인하는 테스트는 없습니다.
- **문서** - 이 문서들에서 약속한 것이며, 기계적으로 확인하는 것은 없습니다.
- **모델** - 플러그인 스킬이 모델에게 주는 지시로, 코드로는 강제할 수 없습니다.
- **계획** - 아직 만들지 않았습니다.

기준의 id는 바뀌지 않습니다. 기능의 설명, 레지스트리, 다른 문서가 이 id를 인용합니다. 새 기준은 그 군의
다음 번호를 받고, 소유자가 바꾼 기준은 바뀐 날짜와 함께 그렇게 적습니다. 목록은 2026-09-23에 정리했고,
K군은 2026-09-28에 더했습니다. 실행 중에 이 파일을 읽는 것은 없습니다.
`advanced/src/codex_auto_resume_advanced/standards.py`는 id를 군마다의 개수로 지니고,
`advanced/tests/test_advanced_registry.py`가 이 파일을 읽어, 둘이 다르거나 여기 적은 테스트가 저장소에 없으면
실패합니다(기준을 더하거나 바꾸는 방법은
[CONTRIBUTING.ko.md](CONTRIBUTING.ko.md)에 있습니다).

코드, 명령, 테스트의 이름은 영어 그대로 두었습니다.

## 0. 두 판의 경계

**0.1** 표준판은 지금 있는 그대로의 제품에, 모든 기준을 지키는 것만 더한 것입니다. 고급 기능의 코드는 표준판의 압축 파일과 설치 프로그램에서 빠지며, 릴리스를 빌드할 때마다 그것을 증명합니다(K1).  
*테스트*: `build/edition_audit.py`, `test_edition_audit.py`, `test_edition_build.py`, `test_edition.py`

**0.2** 제품이 이미 하는 일은 모두 지금의 제약을 그대로 지키고, 기본값은 바뀌지 않습니다. 첫 이어서 하기 메시지가 이미 전달되었을 수 있으면 다시 보내지 않습니다.  
*문서*

**0.3** 이 기준들이 금지하는 것은 고급판에만 있으며, 고급판에서도 각 기능은 무엇을 하는지 들은 사람이 켜기 전까지 꺼져 있습니다(K3, K4).  
*테스트*: `test_advanced_arming.py`, `test_advanced_registry.py`

**0.4** 판마다 압축 파일, 설치 프로그램, 고정된 다이제스트가 따로 있고, 빌드 출처 증명(attestation) 하나가 둘을 함께 다룹니다. 설치본은 자기 판 안에서만 업데이트되며, 판을 바꾸는 것은 일부러 하는 재설치입니다(K2).  
*테스트*: `test_edition_bootstrap.py`, `test_edition_installer.py`

**0.5** 표준판은 알 수 없는 실패나 로그인 실패를 재시도하지 않고, 앱 서버를 함께 쓰지 않고, 로드되지 않은 대화를 thread/resume으로 깨우지 않고, thread/inject_items를 쓰지 않고, 목표의 상태를 바꾸지 않고, 하위 에이전트를 복구하지 않고, 모델·제공자·권한 설정을 다시 적용하지 않고, 여러 작업을 한꺼번에 보내지 않고, 빈 응답을 복구하지 않습니다. 고급판은 이 가운데 일부를, 0.5에서 벗어난다고 밝히는 기능으로 제공합니다.  
*일부 테스트*: `test_recovery.py`, `test_failures.py`, `test_engine.py`, `test_control_continuation.py`, `test_compat.py`

**0.6** 판단의 기준선: 엔진은 작고, 로컬이고, 보수적이며, 실패하면 닫히게(fail-closed) 둡니다. 복잡함은 설치와 제어에 씁니다.  
*문서*

**0.7** Rust 코어(로드맵의 Rust 릴리스)는 동작이 아니라 구현을 바꿉니다. 정확한 스레드 식별, 실패하면 닫히는 것, 레지스트리의 의미, 두 판이 모두 그대로 유지됩니다.  
*계획*

## A. Codex에 무엇을 언제 보내는가

**A1** 보내는 것은 워처뿐이고, 워처 안에서도 메시지를 넘기는 것은 Engine.dispatch 하나뿐입니다. 넘기는 곳은 코어의 백엔드이거나, 고급판에서는 켜진 기능이 그 자리에 두는 채널이며, 그 채널은 플러그에 한 번 물어서 받습니다. 제어 계층, 브리지, MCP 서버, 팝업, 카드에는 보내는 경로가 없습니다.  
*테스트*: `test_structural_invariants.py`, `test_control.py`, `test_mcp.py`, `test_tray_popup.py`, `test_notice_card.py`

**A2** 채널은 하나뿐입니다. 공식 `codex queue --thread <uuid> --message <text>`이며, 한 함수(codex/transport.py의 Backend.send)에서 shell=False인 인수 목록으로 시작합니다. 그 밖에 `queue`를 쓰는 프로세스는 --help 확인뿐이고, 그 밖에 큐를 건드리는 호출은 앱 서버의 삭제뿐입니다.  
*테스트*: `test_structural_invariants.py`, `test_windows.py`

**A3** 정확한 식별: 정규 형식의 UUID만 씁니다. --last, 제목, 프로젝트, 폴더, 최근 순은 쓰지 않습니다.  
*테스트*: `test_structural_invariants.py`, `test_windows.py`, `test_mcp.py`

**A4** 중단 하나마다 마커 `[codex-auto-resume:<16 hex>]` 하나를 답니다(v0.6.10 다음 릴리스부터는 중단 id의 64자리 16진수 가운데 앞 16자리입니다. 그 전에 만든 레코드는 id 전체의 `<64 hex>`를 그대로 두며 그것으로도 찾고, `downgrade-state --to 3`은 모든 마커를 id 전체의 것으로 되돌려 씁니다. 고급판에서 사람이 켜야만 쓰는 마커 없는 보내기는 따로 된 기능입니다). 전달은 그 마커가 그 스레드에 있을 때만 인정합니다. 복구 턴은 마커가 있는 행의 턴이며, "가장 최근 턴"이 아닙니다. 마커가 둘이거나, 실패한 턴이나 그 앞에 마커가 있거나, 클라이언트 id가 맞지 않으면 모호한 것으로 봅니다.  
*테스트*: `test_source.py`, `test_correlation.py`

**A5** 중단은 어떤 프로세스든 메시지를 받을 수 있게 되기 전에 영속적으로 선점합니다(BEGIN IMMEDIATE, synchronous=FULL). 선점 뒤에 프로세스가 비정상 종료되더라도 다시 보내지 않습니다.  
*테스트*: `test_engine.py`

**A6** 전달이 불확실하면 다시 보내지 않습니다. 재시도할 수 있는 것은 "프로세스가 아예 시작되지 않았다"가 증명된 경우뿐입니다. 시작한 뒤의 0이 아닌 종료 코드, 맞지 않는 수신 확인, 시간 초과, 예외는 submission_unknown이 되고, 24시간 지켜볼 뿐 다시 보내지 않습니다.  
*테스트*: `test_engine.py`, `test_windows.py`

**A7** 확인할 수 없는 회수(thread/queue/delete)는 submission_unknown이 되고 다시 보내지 않습니다. Codex가 그것을 여전히 전달할 수 있더라도 그렇습니다.  
*테스트*: `test_engine.py`

**A8** 관문 13개가 정해진 순서로 돕니다: consent, engine_compatible, single_owner, submission_safe, identity, known_failure, schedule, chain_budget, attempt_budget, no_progress_budget, thread_available, no_newer_user_work, usage. 평가하지 않은 관문은 거절로 셉니다. 상태 데이터베이스는 선점 트랜잭션 안에서 consent, submission_safe, schedule, 예산을 다시 확인합니다.  
*테스트*: `test_engine.py`

**A9** 선점과 전송 사이에 무언가 바뀌면(취소, 일시 정지, 대화 끄기, 대체됨, 기록 지연, 누군가 큐에 넣은 입력, 이미 있는 우리 마커, 잃어버린 홈 잠금) 보내지 않고 선점을 돌려줍니다. 시도 횟수는 돌려주고, 선점 시각은 상한 계산을 위해 남깁니다.  
*테스트*: `test_correlation.py`

**A10** 디스패치 잠금 안에서 앱 프로세스의 신원, 로드 상태, 실시간 사용량(30초 이내에 읽은 값)을 다시 확인합니다.  
*코드*

**A11** 데스크톱 앱이 실행 중이고 정확히 그 스레드가 로드되어 있을 때만 보냅니다. notLoaded나 알 수 없음이면 waiting_for_loaded_thread에서 기다리며, 혹시나 해서 큐에 넣어 두는 일은 없습니다.  
*테스트*: `test_engine.py`

**A12** 실제 초기화 시각 전에는 보내지 않으며, 실시간 사용량을 다시 확인합니다.  
*테스트*: `test_engine.py`

**A13** 분류된 종류만 복구합니다: 사용 한도, 연결 실패, 시간 초과(408/425), 요청 한도(429, 429를 담은 responseTooManyFailedAttempts 포함), 5xx, 스트림 끊김. 구조화된 코드를 먼저 보며, 메시지 글은 코드가 없을 때만 정해진 문구 목록과 맞춰 봅니다.  
*테스트*: `test_failures.py`

**A14** 재시도하지 않는 것: 분류되지 않은 모든 것, 사용자 취소, 권한, 승인, 콘텐츠 정책, 잘못된 요청, 컨텍스트 길이, 401/403, badRequest, sandboxError, 429가 없는 responseTooManyFailedAttempts.  
*테스트*: `test_recovery.py`, `test_failures.py`, `test_settings.py`

**A15** 데스크톱 앱의 사용자 대화만 다룹니다. 하위 에이전트, 보관된 스레드, 데스크톱 밖의 스레드는 감지하지 않습니다.  
*테스트*: `test_engine.py`

**A16** 실패는 그것이 스레드의 가장 최근 턴이고, 켠 시각에서 되돌아보기 기간(기본 6시간, 최대 7일)을 뺀 시각 뒤에 끝났을 때만 대상이 됩니다.  
*테스트*: `test_engine.py`

**A17** 사람의 새 작업이 이깁니다. 뒤에 온 턴은 실패를 대체하고, 누군가 큐에 넣은 입력이 있으면 기다리며, 우리 것 뒤에 턴이나 큐 입력이 생기면 우리 것을 거둬들입니다. 사람이 고친 큐 항목은 그 사람의 것이 되어 지우지 않습니다.  
*테스트*: `test_engine.py`, `test_recovery.py`

**A18** 롤아웃보다 뒤처진 기록은 새 전송을 막고, 투영(projection) 테이블이 없으면 호환되지 않는 것으로 막습니다.  
*테스트*: `test_engine.py`

**A19** 대화 하나에 진행 중인 이어서 하기는 하나이며, 잠금 하나 아래에서 차례로 보냅니다. 일괄 재시도는 없고, 일괄 동작은 레코드를 하나씩 정확히 짚어 가며 하는 모두 취소뿐입니다.  
*일괄 동작은 테스트; 진행 중 관문은 코드*: `test_control_continuation.py`

**A20** 설정이 아니라 엔진 상수인 상한: 대화 하나에 24시간 동안 선점 최대 5번, 적어도 15분 간격; 큐 실행 실패 최대 5번; 7일 동안 쓸 수 없는 사용량 체인은 만료되지만, 초기화 시각에 하루를 더한 때보다 먼저 만료되지는 않습니다.  
*테스트*: `test_engine.py`

**A21** 예산은 범위가 제한된 설정입니다: 일시적 실패 시도 4번(1~20), 진행 없이 이어진 복구 3번(1~10), 작업 체인당 이어서 하기 6번(1~10, 그보다 높게는 안 됨). 사용 한도는 시도를 쓰지 않습니다.  
*테스트*: `test_engine.py`, `test_recovery.py`

**A22** 대기는 한정됩니다. 일시적 실패의 대기는 미리 정한 단계표나, 저마다 정해진 목록에서 고르고 직접 입력하지 않는 직접 설정의 다섯 대기에서만 나옵니다. Retry-After나 흔들림(jitter)은 대기를 늘리기만 하며, 요청 한도의 첫 대기는 적어도 1분입니다.  
*테스트*: `test_recovery.py`, `test_ladder_and_guards.py`

**A23** 실패 하나는 한 번만 복구합니다. 같은 Codex 턴이 새 신원으로 오면 거절합니다. 체인의 자식은 카운터를 물려받으며, 부모가 취소되었거나 넘겨졌거나 예산을 다 썼으면 처음부터 멈춘 채로 만들어집니다.  
*테스트*: `test_store.py`, `test_recovery.py`

**A24** 시도 횟수 되돌리기: 소진된 레코드에만, 작업당 최대 3번이며, 취소되었거나 보냈을 수 있는 레코드에는 하지 않습니다. 아무것도 보내지 않고, 대화를 켜지도 않습니다.  
*테스트*: `test_store.py`

**A25** 지금 다시 확인은 일정만 옮깁니다. 아무것도 보내지 않고, 관문을 건너뛰지 않으며, 사용량 창을 열지 않습니다.  
*테스트*: `test_mcp.py`, `test_store.py`

**A26** 이어서 하기 메시지의 글은 기본 제공 템플릿이나 직접 입력 메시지에서만, 복구할 수 있는 종류에만 나오며, 선점 전에 정해집니다. 무엇을 복구할지는 그 글로 바꿀 수 없습니다.  
*테스트*: `test_continuation.py`

**A27** 직접 입력 메시지와, 대화 하나에만 쓰는 메시지는 대시보드에서만 씁니다. MCP update_settings는 둘 다 거부하고, 미리보기 도구는 글을 받지 않습니다. 저마다 최대 2000자이며 입력한 그대로 보냅니다. 자리표시자는 허용 목록({reason},{category},{attempt},{max_attempts},{reset_time})에서만 오고, 위험한 것은 이름으로 거부합니다. 읽을 때 다시 확인하며, 확인을 통과하지 못한 글은 설정되지 않은 것으로 봅니다.  
*테스트*: `test_continuation.py`, `test_mcp.py`, `test_conversation_message.py`

**A28** 알림이나 카드의 버튼은 정확히 한 중단(불투명한 64자리 16진수 id)을 취소하거나, 한 묶음에 한해 전원 동작을 멈추거나(그 묶음의 불투명한 16자리 16진수 id로 가리키며, 묶음이 끝날 때마다 새 id로 바뀝니다), 정해진 목록의 페이지 하나를 여는 것만 할 수 있습니다. 그 밖의 것은 무시하고 기록하며, 버튼이 전송을 일으키는 일은 없습니다(2026-10-03 소유자가 고침).  
*테스트*: `test_notify.py`, `test_notice_card.py`, `test_cli.py`
<!-- A28은 소유자의 말로 개정했습니다(2026-10-03, "예, 버튼 넣기"): 전원 동작의 알림과 카드에 그 묶음 하나만 멈추는 단추를 두며, 묶음은 그 nonce로 가리킵니다. -->

**A29** 스위치 클릭은 정확한 중단과 대화를 함께 싣습니다. 오래되었거나, 끝났거나, 다른 대화의 클릭은 거절되어 아무것도 바꾸지 않으며, 스위치는 아무것도 보내지 않습니다.  
*테스트*: `test_control_continuation.py`, `test_tray_popup.py`

**A30** 엔진은 `codex queue --help`가 여전히 --thread와 --message를 내놓을 때만 받아들입니다. 증명되지 않은 것은 모두 거절하며, 버전 고정은 없습니다.  
*테스트*: `test_windows.py`

## B. 무엇을 어떻게 읽는가

**B1** Codex SQLite는 읽기 전용으로 엽니다: mode=ro, PRAGMA query_only=ON, trusted_schema=OFF.  
*테스트*: `test_source.py`

**B2** Codex의 데이터베이스, 롤아웃, 설정 파일은 어느 것도 쓰기로 열지 않습니다. WAL의 -shm 갱신은 밝혀 둡니다.  
*코드*

**B3** Codex의 상태는 공식 인터페이스로만 바뀝니다: codex queue, thread/queue/delete, 그리고 설치와 제거 때의 codex plugin CLI.  
*코드*

**B4** 앱 서버는 따로 떨어진, 잠깐 쓰고 끝나는 stdio 도우미입니다. 보내는 것은 initialize(와 initialized), account/rateLimits/read, thread/queue/delete뿐입니다. 서버가 보내는 요청은 거절하고, 잘못된 codexHome은 거부합니다.  
*테스트*: `test_windows.py`

**B5** 가장 새로운 세대의 데이터베이스만, 그리고 읽는 열이 모두 있을 때만 읽습니다. 경로는 Codex 홈 안에 있어야 합니다.  
*테스트*: `test_source.py`

**B6** 롤아웃 파일은 <home>\sessions 아래 것만 읽습니다. 첫 줄(최대 256 KiB: id와 출처)을 읽고, 사용 한도일 때만 실패 앞의 최대 8 MiB를 메모리에서 읽어 초기화 시각과 한도 id만 남깁니다.  
*경로는 테스트; 바이트 상한은 코드*: `test_source.py`

**B7** 메시지 내용을 돌려주는 쿼리는 instr(col, marker)>0으로 좁힙니다. 다른 사람의 행은 개수나 참거짓으로만 돌아옵니다.  
*테스트*: `test_source.py`

**B8** title, preview, first_user_message는 조회하지 않습니다. 표시 이름은 threads.name, 프로젝트, cwd의 마지막 이름에서만 오며, 한 줄 최대 72자이고, 스레드를 식별하는 데 쓰지 않습니다.  
*테스트*: `test_failures.py`

**B9** 원래 오류는 분류한 뒤 버리고, 종류만 남깁니다. 진행 여부는 수명 주기 열과 정해진 항목 종류 목록에서만 판단하고 내용에서는 판단하지 않으며, 예외는 메시지에 우리 마커가 있는지 여부뿐입니다.  
*테스트*: `test_failures.py`, `test_recovery.py`

**B10** 사용량 응답에서는 숫자로 된 창, 초기화 시각, 버킷 이름만 남깁니다.  
*테스트*: `test_windows.py`

**B11** auth.json, 토큰, 쿠키, 인증 헤더, 자격 증명 저장소, 프로세스 메모리는 읽지 않습니다.  
*문서*

**B12** 로드 상태는 Restart Manager 목록에서만 옵니다. 바이트 잠금 API는 없고 앱의 쓰기 잠금은 잡지 않습니다. 모호함, PID 재사용, 쓸 수 없는 API는 알 수 없음으로 읽습니다.  
*테스트*: `test_windows.py`

**B13** GUI 자동화, 입력 흉내, UI Automation, OCR, 화면 캡처가 없습니다. 다른 창을 읽거나 움직이는 것은 없습니다. 팝업은 화면 낭독기에게 자기 자신에 대해 답할 뿐이고, 하나뿐인 PrintWindow는 빌드 전용 도구입니다.  
*테스트*: `test_surface_properties.py`

**B14** 웹 스택이 없습니다: 브라우저 제어, WebView, 연결을 기다리는 소켓, localhost 서버, 두 번째 런타임이 없으며, 창은 System, System.Drawing, System.Windows.Forms만으로 컴파일합니다.  
*테스트*: `test_surface_properties.py`

**B15** 호환성 확인은 스키마의 테이블과 열 이름, 폴더가 있는지만 읽고, 행은 읽지 않습니다.  
*코드*

**B16** Windows에는 내용이 없는 질문만 하며, AppsUseLightTheme와 TrayNotify는 읽기만 하고 쓰지 않습니다. 전원 동작은 세 가지를 더 묻습니다. 이 계정이 SeShutdownPrivilege를 지녔는지와 이 PC가 어떤 절전 상태를 제공하는지는 대시보드가 전원 동작의 카드를 보여 줄 때와 그것을 켤 때, 그리고 켜져 있는 동안 묻습니다. 마지막 입력이 얼마나 전에 있었는지(시간뿐이며 무엇이었는지는 묻지 않고, 후크도 없습니다)와 다른 세션이 몇 개 로그인해 있는지(개수뿐이며 사용자 이름은 묻지 않습니다)는 켜져 있는 동안에만 묻습니다.  
*일부 테스트*: `test_power_action_windows.py`

**B17** 계층: 엔진은 sqlite3, ctypes, subprocess를 import하지 않고 주입받은 어댑터로만 Codex에 닿습니다. UI와 MCP는 Codex 읽기 모듈을 import하지 않고, 도메인 계층은 순수한 표준 라이브러리이며, subprocess는 목록에 있는 모듈만 import합니다.  
*테스트*: `test_layers.py`, `test_structural_invariants.py`

## C. 네트워크

**C1** 런타임에는 네트워크 코드가 없습니다. src/나 advanced/src/ 아래 어떤 파일도, scripts/*.py 어떤 파일도 네트워킹 모듈을 import하지 않습니다.  
*테스트*: `test_privacy_claims.py`

**C2** 네트워크에 닿는 배포 파일은 정확히 하나, scripts/bootstrap.ps1입니다. build/는 릴리스를 빌드하는 동안 고정된 Python을 내려받으며, 거기서 배포되는 것 - 설치 스크립트와 설치 프로그램 - 은 어디에도 닿지 않습니다.  
*테스트*: `test_privacy_claims.py`, `test_setup.py`

**C3** 텔레메트리, 분석, 충돌 보고가 없으며, 배포 파일은 예상하지 않은 호스트를 적지 않습니다. api.github.com은 주소 두 개에만 적으며, 둘 다 이 저장소의 릴리스 목록입니다. 업데이트 확인이 읽는 최신 열 개와, 버전 고르기가 읽는 30개씩의 쪽입니다(2026-10-03 소유자가 고침).  
*테스트*: `test_privacy_claims.py`

**C4** 아무것도 저절로 일어나지 않습니다: 업데이트 폴링도, 일정도, 시작할 때 하는 일도, 자동 호환성 새로 고침도 없습니다.  
*테스트*: `test_convergence.py`, `test_gui_update.py`

**C5** 업데이트 확인은 사람이 버튼을 누를 때만 돕니다. 고정된 releases/latest URL에 HEAD 요청 하나를 보내고, 정확히 이 저장소 아래로 온 리디렉션에서 버전을 읽어 그 정수들로 다시 만듭니다. 더 새로운 프리 릴리스를 찾으려고 이 저장소의 릴리스 목록도 읽으며, 찾으면 질문으로 권하고 '예'라고 답할 때만 설치합니다. 버전 고르기(*다른 버전 설치...*)는 사람이 열 때와 확인할 때만 이 저장소의 릴리스 목록 전체를 쪽마다 읽고, 고른 버전과 판은, 릴리스든 프리 릴리스든, 더 오래된 것이든 더 새로운 것이든, '예'에 해당하는 그 확인 뒤에만 설치합니다(2026-09-28과 2026-10-03 소유자가 고침).  
*테스트*: `test_update_check.py`, `test_convergence.py`, `test_prerelease_offer.py`, `test_version_picker.py`, `test_gui_versions.py`

**C6** 설치 다운로드: HTTPS, 리디렉션 최대 5번, 상수와 매니페스트 버전(또는 릴리스 목록에서 고른 버전을 그 정수들로 다시 만든 것)으로 만든 URL, 마지막 호스트는 GitHub 호스트 세 곳 가운데 하나(내려받은 뒤에 확인하며, 이 점은 밝혀 둠), 받는 것은 많아야 압축 파일과 그 .sha256뿐입니다(2026-10-03 소유자가 고침).  
*테스트*: `test_convergence.py`, `test_update_check.py`, `test_version_picker.py`

**C7** 호환성 새로 고침은 요청할 때만 합니다. 쿼리 없는 고정된 raw.githubusercontent.com URL에 GET 하나, 최대 256 KiB이며, PowerShell이 해석하거나 실행하지 않고, 워처나 어떤 MCP 도구도 시작하지 않습니다.  
*테스트*: `test_compat_bootstrap.py`, `test_compat_surfaces.py`

**C8** 요청에는 제품이 만든 식별자가 없습니다. GitHub는 IP, 시각, PowerShell의 User-Agent를 보며, 이 점은 밝혀 둡니다.  
*고정 URL은 테스트; bootstrap.ps1에는 사용자 지정 헤더가 없음*: `test_update_check.py`

**C9** OpenAI에는 공식 Codex를 통해서만 닿습니다: 복구할 때가 되었을 때 하는 사용량 조회이며, 30초 동안 다시 쓰고, codex_auto_resume과 실제 버전으로 자신을 밝힙니다.  
*코드*

**C10** 이 제품이 시작하는 모든 codex 프로세스는 OTEL_SDK_DISABLED, 분석 끔, OTel 내보내기 none, log_user_prompt=false, 고정된 chatgpt_base_url로 돕니다.  
*테스트*: `test_privacy_claims.py`, `test_windows.py`

**C11** 설치 프로그램은 이 제품의 마켓플레이스만, 이름으로 새로 고칩니다.  
*코드*

**C12** 번역, 패널, 창은 아무것도 가져오지 않습니다. MCP 매니페스트는 환경도 네트워크도 선언하지 않습니다.  
*테스트*: `test_l10n.py`, `test_mcp.py`, `test_plugin.py`

**C13** 밝혀 둠: 도구와 명령이 돌려주는 것은 Codex 대화의 일부가 되어 OpenAI로 갑니다.  
*문서*

## D. 개인정보와 보관하는 데이터

**D1** 개발자에게는 아무것도 가지 않습니다: 프롬프트, 답변, 파일, id, 자격 증명, 원래 오류, 제목, 경로, 통계 모두.  
*문서*

**D2** 상태에는 id, 열거값, 카운터, 시각만 두며, 글은 길이가 제한되고 제어 문자가 없고, 프롬프트·답변·오류 글은 없습니다. 밝혀 둔 예외 하나는 알림에 쓰는 대화 제목입니다.  
*테스트*: `test_store.py`, `test_engine.py`

**D3** 로그는 정해진 메시지 표로 씁니다. 믿을 수 없는 값은 16진수나 숫자가 아니면 가리고, 주 로그는 예외 클래스 이름만 남기며, 추적 정보는 errors.log로 갑니다. 밝혀 둔 것: 상태 폴더 경로와 엔진 버전.  
*테스트*: `test_engine.py`

**D4** 기록부(journal)는 정해진 어휘의 코드와 정수 플래그만 담고, 최대 5,000개와 90일로 제한되며, 무엇을 정하는 데 읽지 않습니다.  
*테스트*: `test_store.py`, `test_surface_properties.py`

**D5** 진단 내보내기는 요청할 때만, 고른 경로에, 덮어쓰지 않고 하며, 그것을 보내는 것은 없습니다. id는 파일마다의 별칭이 되고, 경로·사용자 이름·이메일 주소는 가리며, 직접 입력 메시지는 설정되었다는 것만 적고 인용하지 않습니다.  
*테스트*: `test_diagnostics.py`

**D6** 알림: 최대 72자인 한 줄 표시 이름 최대 2개와 UUID, 오류나 계정 글은 없고, 최대 3줄, XML 이스케이프. 카드는 토스트가 보여 주는 것을 보여 줍니다.  
*테스트*: `test_notify.py`

**D7** get_status는 호환성 요약을 코드로만 싣고, 설치 경로는 싣지 않습니다. 설정은 돌려주며 직접 입력 글과 codex_exe 경로도 읽기 전용으로 들어 있는데, 이 점은 밝혀 둡니다.  
*테스트*: `test_mcp.py`, `test_compat_surfaces.py`

**D8** PowerShell에 닿는 값은 환경 변수로 고정된 스크립트에 가며, PowerShell은 System32 전체 경로로 실행합니다.  
*테스트*: `test_pwsh.py`, `test_gui_update.py`

**D9** 화면에 닿는 오류는 정적인 코드이며, 모든 거절은 닫힌 집합 하나의 코드를 답니다.  
*테스트*: `test_control.py`, `test_mcp.py`

**D10** 제거는 기본적으로 설정과 대기 중인 상태를 남깁니다. 모두 지우는 것은 골라야만 합니다.  
*테스트*: `test_installer.py`

**D11** 저장소와 증거의 위생: 합성한 UUID와 자리표시자 홈만 쓰고, 라이브 인수의 증거에는 내용이 없습니다.  
*테스트*: `test_repo_hygiene.py`, `test_screenshots.py`, `test_live_evidence.py`

**D12** 언어는 IP, 시간대, 사용자 이름, 국가, 키보드 배열로 추측하지 않습니다. Windows UI 언어의 첫 번째만 셉니다.  
*코드*

**D13** 사용자에게 공개 이슈에 자격 증명, 대화, 가리지 않은 로그를 붙여넣지 말라고 안내합니다.  
*문서*

## E. 실패했을 때의 동작

**E1** 실패하면 닫힘: 알 수 없는 로드 상태, 알 수 없는 사용량, 쓸 수 없는 확인, 없는 투영 테이블, 손상된 상태, 돌리지 못한 호환성 평가는 모두 기다리거나 거절하는 것이지, 보내는 것이 아닙니다.  
*테스트*: `test_engine.py`, `test_compat_io.py`

**E2** 두 번 이어 가느니 한 번 놓칩니다.  
*문서*

**E3** 손상되었거나 비었거나 심볼릭 링크이거나 형식이 틀린 상태, 더 새로운 스키마, 알 수 없는 레코드 상태는 닫힌 채 실패하며 초기화하지 않습니다. 마이그레이션은 워처 뮤텍스 아래에서, 포렌식 사본을 만든 뒤, 트랜잭션 하나로만 합니다.  
*테스트*: `test_store.py`

**E4** 더 오래된 워처가 더 오래된 스키마를 여전히 쥐고 있는 동안에는 자동화를 줄이는 동작만 됩니다.  
*테스트*: `test_control_v3.py`

**E5** 형식이 틀렸거나 너무 큰 설정 파일은 기본값으로 읽고, 틀린 형식은 쓸 때 거부하며, 풀 수 없는 관문 벡터는 UNKNOWN으로 읽습니다.  
*테스트*: `test_settings.py`, `test_control.py`

**E6** 끝나지 않는 턴은 outcome_unverified이며 성공이 아니고, 읽을 수 없는 기록은 "진행 없음"이 되지 않습니다.  
*테스트*: `test_outcomes.py`

**E7** 제거는 워처가 확실히 돌고 있지 않은 것이 아니면, 등록을 포함해 무엇이든 지우기 전에 멈춥니다. 경로를 읽을 수 없는 프로세스는 건너뛰고 끝내지 않습니다.  
*테스트*: `test_cli.py`

**E8** 멈추기는 언제나 요청입니다. 업그레이드는 최대 1분 기다리며 강제로 끝내지 않습니다. 끝낼 수 있는 것은 이 플러그인 자신의 MCP 실행기(경로로 확인)와 자신의 짧게 사는 Codex 도우미뿐입니다.  
*테스트*: `test_control.py`, `test_installer.py`, `test_upgrade_handover.py`

**E9** 부트스트랩은 모든 확인을 통과하기 전에는 압축 파일의 어떤 것도 실행하지 않으며, 어떤 실패든 내려받은 파일을 지웁니다. 오래된 버전을 위해 상태를 바꾸는 것은 압축 파일이 모든 확인을 통과한 뒤, 압축 파일의 어떤 것도 아직 실행하지 않았을 때뿐입니다(2026-10-03 소유자가 고침).  
*테스트*: `test_convergence.py`, `test_version_picker.py`

**E10** 다운로드가 실패하면 스킬은 멈춥니다: 다른 출처도, 손으로 맞춘 설치도 없습니다.  
*모델*

**E11** 알림, 트레이, 실패 확인 파일은 복구를 결정하거나 늦추지 않습니다. 카드는 확실하지 않을 때 토스트로 물러서고, 알림을 꺼도 바뀌는 것은 없습니다.  
*테스트*: `test_notice_card.py`

**E12** 무결성이 더 낮은 프로세스가 심어 둔 뮤텍스, 멈춤 이벤트, 깨우기 이벤트는 거부합니다. 실행 중인 워처의 뮤텍스를 가로채는 것은 다루지 않으며, 이 점은 밝혀 둡니다.  
*테스트*: `test_named_objects.py`

**E13** 물어보지 못한 업데이트 확인은 "최신"으로 읽히지 않습니다: 답 네 가지, 종료 코드 네 가지.  
*테스트*: `test_gui_update.py`

**E14** 로그온 때 어댑터, 상태 데이터베이스, 확인이 잠시 실패하면 그 틱을 미룰 뿐 워처를 끝내지 않습니다.  
*테스트*: `test_cli.py`

## F. 컴퓨터에 남기는 흔적

**F1** 관리자 권한이 필요 없고, 사용자 단위로만 설치하며, 서비스도 예약 작업도 컴퓨터 전체에 걸친 것도 없습니다.  
*테스트*: `test_installer.py`

**F2** 레지스트리 쓰기는 모두 HKCU 아래입니다: Run 값(고른 경우에만 쓰고, 우리 것일 때만 지움), Software\Classes\codex-auto-resume, Software\Classes\AppUserModelId\CodexAutoResume.Watcher.  
*키마다 테스트; 다른 키를 쓰지 않는 것은 코드*: `test_cli.py`, `test_notify.py`, `test_plugin.py`

**F3** 자기 파일: 출처 표시가 있는 config/와 logs/, 홈(%USERPROFILE%\.codex-auto-resume, AppData가 아님)의 프로그램 파일, 시작 메뉴 바로 가기, 그리고 요청한 곳에만 쓰는 진단.  
*테스트*: `test_plugin.py`

**F4** 경로 가두기: 링크이거나 홈 바깥으로 풀리는(NTFS 정션 포함) 소유 디렉터리는 거부합니다.  
*테스트*: `test_cli.py`, `test_installer_ownership.py`

**F5** 소유가 증명되지 않은 것은 지우지 않습니다. 밝혀 둔 예외는 이름으로 바꾸는 사용자 단위의 단일 항목들과, 다시 가리키게 하는 마켓플레이스입니다.  
*테스트*: `test_installer_ownership.py`

**F6** 시작하는 프로세스: 자기 것 - 워처, 설정 창, 그 뒤에서 도는 함께 들어 있는 Python; codex app-server --stdio, codex queue, --version과 queue --help 확인; 설치하고 제거할 때의 codex plugin 명령; 그리고 고정된 스크립트를 전체 경로로 실행하는 PowerShell. 모두 인수 목록으로 시작합니다.  
*테스트*: `test_structural_invariants.py`, `test_pwsh.py`

**F7** 단일 인스턴스: 사용자와 상태 디렉터리마다의 뮤텍스, 멈춤 이벤트, Codex 홈마다의 잠금. 두 번째 워처는 끝나고, 전송 관문은 그 잠금을 요구하며, 두 번째 설치는 거부합니다.  
*테스트*: `test_engine.py`, `test_surface_properties.py`, `test_plugin.py`

**F8** 상주하는 도우미가 없습니다: 워처 프로세스 하나가 아이콘, 팝업, 카드를 모두 담고, 트레이 프로세스·감독 프로세스·서비스·웹 UI·두 번째 엔진이 없으며, Codex 도우미는 짧게 삽니다.  
*일부 테스트*: `test_tray_popup.py`

**F9** 업그레이드나 복구 설치는 복구를 다시 켜지 않고, 지운 로그인 항목을 다시 넣지 않습니다(--keep-state). 더 오래된 플러그인은 -Force 없이 더 새로운 설치를 대체하지 않습니다.  
*테스트*: `test_installer.py`, `test_plugin.py`, `test_update_check.py`

**F10** 로그인 실행기는 이 설치본, 이 제품의 마켓플레이스 사본, 또는 기록된 사본만 시작하며, 그 밖에는 아무것도 시작하지 않습니다.  
*테스트*: `test_plugin.py`, `test_upgrade_handover.py`

**F11** 스킬은 매니페스트가 이 제품을 가리키는지 확인한 뒤, 절대 경로로만 bootstrap.ps1을 실행합니다.  
*모델*

**F12** 설치 안전: 이름 있는 설치 잠금(부트스트랩의 복구 분기 포함), 첫 이동 전에 쓰는 옮김 기록, 실패하면 되돌리기, 첫 쓰기 전에 루트를 차지하기, 상태 디렉터리는 바꾸지 않기.  
*테스트*: `test_installer.py`, `test_convergence.py`, `test_installer_ownership.py`

**F13** 함께 들어 있는 Python에서 표준 라이브러리만 씁니다. 시스템 Python으로는 두 번째 설치를 만들지 않습니다.  
*일부 테스트*: `test_installer.py`, `test_layers.py`

**F14** Codex가 시작할 때 워처를 시작하는 것은 표준판에서 제공하지 않습니다. Codex 안에서 시작한 워처는 Codex가 닫힐 때 끝나므로(Codex 26.915에서 측정), 설정은 있지만 제공하지 않습니다. 고급판의 Codex와 함께 시작은 WMI를 통해 Codex의 작업 개체 바깥에서 이 일을 합니다.  
*테스트*: `test_start_with_codex.py`, `test_settings.py`

**F15** 전원 동작은 워처가 자기 토큰에서 SeShutdownPrivilege를 켠 뒤 직접 부르는 SetSuspendState 또는 강제 플래그 없는 ExitWindowsEx(EWX_POWEROFF)이며, 그 권한이 없는 계정에는 어떤 동작도 제공하지 않습니다. 프로세스, 작업, 서비스를 시작하지 않고, 관리자 권한이 필요 없으며, Windows 설정을 바꾸지 않고, 다른 사람이 로그인해 있는 동안에는 절대 시스템을 종료하지 않습니다.  
*테스트*: `test_power_action_windows.py`

## G. 호환성 레지스트리의 권한

**G1** 데이터는 제한만 할 수 있습니다. 로컬 확인이 실패하면 언제나 그것이 이기며(INCOMPATIBLE, 또는 데이터가 그 버전을 보증했다면 FAILED_HERE), 둘 다 모든 전송을 막습니다.  
*테스트*: `test_compat.py`, `test_compat_io.py`

**G2** 데이터가 올릴 수 있는 것은 로컬 PASS뿐이고, 정확한 버전에만, CHECKED나 VERIFIED로만 올립니다. 그것은 보내는 것이 아니라 표시되는 낱말을 바꾸며, 범위는 제한만 합니다.  
*테스트*: `test_compat.py`

**G3** 관문은 verified, checked, structurally_compatible이면 보내고, failed_here와 incompatible은 막습니다. 그 밖의 것은 UNKNOWN으로 아무것도 보내지 않으며, 실패한 평가는 닫힌 채 실패합니다.  
*테스트*: `test_compat_io.py`

**G4** 증거 규칙: VERIFIED에는 바로 그 버전에서, 그 기능을 실제로 거친 실제 복구로 기록한 증거 파일의 인용이 필요합니다. CHECKED에도 증거가 필요하고, URL 인용은 안 되며, 빌드는 검증기가 거부할 데이터를 거부합니다.  
*테스트*: `test_compat.py`

**G5** 검증기(controlcli compat-import)만 compat-cache.json을 씁니다. 알 수 없는 형식, 형식이 틀린 내용, 256 KiB 초과(해석 전에 확인), 중복 키, 유한하지 않은 수, 지나친 깊이, 신뢰를 주는 범위, requires_signature, 되돌림, 하루보다 더 앞선 날짜, 더 새로운 제품이면 문서 전체를 거부하며, 거부하면 캐시는 그대로입니다.  
*테스트*: `test_compat.py`, `test_compat_io.py`

**G6** 캐시는 읽을 때마다 검증합니다. 만료되었거나 미래 날짜인 데이터는 제한은 그대로 두고 신뢰만 잃습니다. 어떤 시계도 제한을 풀지 않으며, 잘못된 캐시는 무시할 뿐 지우지 않습니다.  
*테스트*: `test_compat.py`, `test_compat_io.py`

**G7** 워처의 보고서는 실행 파일(경로 다이제스트, 크기, 수정 시각)에 묶입니다. 읽는 쪽은 손상되었거나, 오래되었거나, 바뀐 바이너리에 대한 보고서를 거부합니다.  
*테스트*: `test_compat_io.py`

**G8** 사람이나 모델에게 보여 주는 것은 모두 닫힌 목록의 코드이며 문서의 글이 아닙니다. MCP는 코드만 읽고, 새로 고치거나 가져올 수 없습니다.  
*테스트*: `test_compat.py`, `test_compat_surfaces.py`

**G9** 설치된 모든 릴리스는 main의 가장 새로운 데이터를 통째로 씁니다. 동작 테스트는 얼려 둔 사본을 읽습니다.  
*테스트*: `frozen_registry.py`

**G10** 함께 들어 있는 데이터로는, 관문이 레지스트리가 생기기 전에 정하던 대로 정합니다.  
*테스트*: `test_compat_characterization.py`

**G11** 데이터에는 서명이 없습니다. 서명 자리는 비워 두었고 requires_signature는 거부합니다. 한정된 최악의 경우는 빌드 하나 동안 복구가 멈추는 것입니다.  
*남는 위험은 문서; 거부는 테스트*: `test_compat.py`, `test_compat_io.py`

**G12** 확인할 방법이 없는 기능(빈 응답, notLoaded, 목표, 하위 에이전트)은 'unsupported' 등급에 머뭅니다.  
*테스트*: `test_compat.py`

**G13** 다른 사람의 보고는 따로 보여 주고, 어떤 버전도 검증됨이나 점검됨으로 올리지 않으며, 제품이 하는 일을 아무것도 바꾸지 않습니다. 표준판은 그것 때문에 아무것도 보내지 않습니다.  
*테스트*: `test_community_report.py`, `test_compat.py`, `test_compat_surfaces.py`

## H. 사용자의 제어

**H1** 기본값: 복구 켜짐, 복구할 수 있는 종류 모두 선택, 알림·카드·아이콘 켜짐, 인터페이스 언어의 기본 메시지, -NoStartup이 없으면 로그인 때 시작. 새 상태는 설치가 켤 때까지 꺼진 채 시작합니다.  
*테스트*: `test_settings.py`

**H2** 설정은 정책일 뿐입니다. 어떤 설정도 알 수 없는 실패를 재시도하거나, 제목으로 찾거나, 불확실한 전송을 다시 보내거나, 전송을 강제하거나, 재확인을 건너뛰거나, 엔진 상수를 움직일 수 없습니다. 쓰기는 엄격해서, 범위 밖 값은 잘라 맞추지 않고 거부합니다.  
*테스트*: `test_engine.py`, `test_settings.py`

**H3** 세 화면이 검증기 하나를 거쳐 설정 파일 하나에 쓰며, 직접 입력 글은 대시보드만 씁니다. update_settings는 엔진 경로, 되돌아보기 기간, 트레이 아이콘, 움직임 줄이기, 카드, 직접 입력 글을 제공하지 않으며, 스키마를 무시하고 보내도 거부합니다.  
*테스트*: `test_mcp.py`

**H4** 전체 일시 정지는 곧바로 듣는 차단 스위치이며, 대기 중인 레코드는 남깁니다. 큐에 들어간 이어서 하기는 회수하고, 회수가 확인되면 레코드는 시도를 돌려받고 대기로 돌아가며, 불확실한 전송 위에서 일시 정지하면 그 레코드는 최종으로 끝납니다.  
*테스트*: `test_engine.py`, `test_pause_unknown.py`

**H5** 대화를 끄면 거기서 기다리던 것이 취소되고, 취소는 최종입니다. 다시 켜도 되살아나지 않고, 예산 되돌리기도 거부합니다.  
*테스트*: `test_engine.py`, `test_store.py`

**H6** 취소는 언제나 되며, 체인 전체를 다루고, 아직 큐에 있는 항목을 회수하며, 진행 중인 턴을 멈추지는 않습니다.  
*테스트*: `test_store.py`

**H7** 아무것도 하지 않으면 이어집니다. 다만 설정이 복구를 사람에게 맡겨 두는 경우 - '먼저 묻기'나 '알림만'으로 둔 대화, '이어 가도 되는 프로젝트'가 허용하지 않는 프로젝트나 목록 방식에서 프로젝트를 읽을 수 없는 작업, 작업 변경 보호를 '보류'로 두었을 때 바뀌었다고 본 작업, 컨텍스트 비용 보호의 '넘으면 보류' 기준을 넘은 대화, '이보다 오래 절전한 뒤에는 먼저 묻기'보다 긴 절전 동안 예정 시각이 된 것 - 에는 사람을 기다리고, '지켜보기만'이 켜져 있는 동안에는 아무것도 보내지 않습니다. '재개하지 않음' / '다시 시도하지 않음'은 취소만 합니다.  
*테스트*: `test_notify.py`, `test_postpone_and_tiers.py`, `test_observe_and_admission.py`, `test_ladder_and_guards.py`, `test_power.py`

**H8** 자동화를 더하거나 되돌릴 수 없는 MCP 도구에는 destructiveHint가 붙습니다(resume, enable_conversation, update_settings, restore_default_settings, cancel_recovery, reset_recovery_budget, start_watcher, release_hold, clear_recovery_history). pause, 대화 끄기, retry_now, postpone, turn_off_power_action에는 붙지 않습니다. 이것은 잠금이 아니라 요청입니다.  
*테스트*: `test_mcp.py`, `test_mcp_v3.py`, `test_postpone_and_tiers.py`

**H9** 표시된 도구가 거절되면 모델은 그에 맞는 명령을 실행하면 안 되고, 재개를 "강제"해서도 안 되며, 없는 안전 설정을 우회해서도 안 됩니다.  
*모델*

**H10** 기록 지우기는 행을 숨기기만 합니다. 숨긴 행도 모든 상한과 중복 확인에 셈하며, 아직 바뀔 수 있는 것은 숨기지 않습니다.  
*테스트*: `test_store.py`

**H11** 스위치 명령은 진짜 JSON 불리언만 받으므로, 문자열 "false"가 자동화나 Run 값을 켜는 일은 없습니다.  
*테스트*: `test_control.py`

**H12** 복구할 수 있는 종류마다 스위치가 따로 있고, 꺼진 종류는 기록하지도 않습니다.  
*테스트*: `test_engine.py`

**H13** 사람이 직접 고른 인터페이스 언어는 Windows와 CODEX_AUTO_RESUME_LANG보다 우선하며, 다시 시작, 복구 설치, 업데이트 뒤에도 남습니다. 움직임은 움직임 줄이기, Windows의 애니메이션 설정, 고대비, 배터리 절약, 잠긴 세션, 넘침 영역에서 멈춥니다.  
*테스트*: `test_locale.py`, `test_tray_icon_motion.py`

**H14** 사용량 한도 복구 뒤의 전원 동작은 기본으로 꺼져 있고, 대시보드에서만 한 번 또는 항상으로 켭니다. MCP, 아이콘, 알림은 그것을 끄거나 그 묶음에 한해 멈추는 것만 할 수 있으며, 멈춤은 다른 무엇을 보기 전에 먼저 따릅니다. 그 묶음의 모든 사용량 한도 복구가 사람이 고른 대로 끝났고, 열려 있거나 지켜보는 복구가 없고, Codex의 기록이 따라잡았고, Codex 턴이 돌지 않고, 대기 중인 입력이 없고, 2분 동안 아무도 PC를 쓰지 않았고, 알림의 카운트다운이 다 지났을 때만 동작합니다. 읽을 수 없는 것이 하나라도 있으면 아무것도 하지 않으며, 아무것도 보내지 않습니다.  
*테스트*: `test_power_action.py`, `test_power_action_watcher.py`, `test_power_action_control.py`, `test_cli.py`

## I. 릴리스와 공급망

**I1** 릴리스는 전체 테스트를 통과한 뒤, 태그가 달린 커밋에서 Actions가 빌드합니다. 태그는 매니페스트의 버전과 같고, 프리 릴리스 태그(-alpha나 -beta, 그 뒤로 번호: -alpha.2, -beta.2 등)는 최신 릴리스가 되지 않는 GitHub 프리 릴리스로 게시합니다.  
*테스트*: `test_workflow_privilege.py`, `test_plugin.py`, `test_version_rule.py`

**I2** 권한에 따라 나뉜 두 작업. build는 contents: read이고 토큰을 남겨 두지 않으며 저장소 코드를 실행합니다. publish는 저장소 코드를 실행하지 않고 태그 push 때만 돌며, 수동 실행은 시험 실행이고, 실행 스크립트에 식을 끼워 넣지 않습니다.  
*테스트*: `test_workflow_privilege.py`, `test_convergence.py`

**I3** 모든 Action은 전체 SHA로 고정하며, Dependabot은 제안만 하고 자동 병합하지 않습니다.  
*테스트*: `test_workflow_pins.py`

**I4** 게시한 버전은 바꾸지 않습니다. 이것은 GitHub의 불변성이 아니라 워크플로의 규칙이며, 이 점은 밝혀 둡니다.  
*테스트*: `test_convergence.py`

**I5** 게시된 버전마다 그 다이제스트를, 게시된 파일에서 구해 main의 scripts/release.json에 고정합니다.  
*테스트*: `test_convergence.py`

**I6** 부트스트랩은 SHA-256을 고정값과, 없으면 옆에 놓인 파일과 비교하고 어느 쪽인지 말합니다. 고정값 없는 -ArchivePath에는 "NOT checked"라고 말합니다. 무엇이든 실행하기 전에 압축 파일이 이 버전의 이 제품이고 바깥으로 빠져나가는 항목이 없는지 확인하며, 확인하지 않은 압축 파일을 확인했다고 알리지 않습니다.  
*테스트*: `test_convergence.py`

**I7** v0.5.4 이후의 모든 압축 파일에는 빌드 출처 증명(attestation)이 있고, 사용자에게 확인하는 법을 알려 줍니다. 제품 자체는 그것을 확인하지 않습니다.  
*코드*

**I8** 재현 가능한 실행 파일(정규화한 PE 타임스탬프와 MVID, 두 번 빌드해 다르면 거부)과 결정적인 압축 파일(목록에 있는 파일, 정렬, 고정 타임스탬프; build/, tests/, config/, logs/, 상태는 제외).  
*테스트*: `test_reproducible.py`, `test_surface_properties.py`

**I9** 압축 파일의 항목은 build에서 확인하고, publish에서 체크섬을 다시 확인합니다. 필수 항목 목록은 설치된 부트스트랩들이 필요로 하는 것과 같습니다.  
*테스트*: `test_convergence.py`, `test_installer.py`

**I10** 함께 들어 있는 Python은 버전과 SHA-256으로 고정합니다.  
*버전은 테스트; SHA-256은 코드*: `test_python_support.py`

**I11** 저장소의 매니페스트는 스킬만 선언합니다. MCP 서버는 빌드 때 그 런타임 옆에 더합니다.  
*테스트*: `test_plugin.py`

**I12** 업데이트는 -Force 없이 더 오래된 버전으로 가지 않고, 정확히 이 저장소 아래에서 찾은 버전으로만 가며, --keep-state로 설치합니다. 업데이트 확인이 권하는 프리 릴리스는 사람이 그 권유에 '예'라고 답해야만 설치하며, 업데이트 확인은 설치된 것보다 오래된 프리 릴리스를 권하지 않습니다. 사람이 *다른 버전 설치...*에서 이름으로 골라 확인한 버전은, 프리 릴리스든, 더 오래된 것이든 더 새로운 것이든, 첫 문장을 따릅니다. 더 오래된 것은 -Force로만 설치하며, 그 확인이 '예'입니다. 프리 릴리스는 게시된 .sha256과 비교해 확인합니다(2026-09-28과 2026-10-03 소유자가 고침).  
*테스트*: `test_update_check.py`, `test_prerelease_offer.py`

**I13** 어떤 것도 Authenticode 서명이 없으며 이 점은 밝혀 두고, 사용자에게 SmartScreen이나 스마트 앱 컨트롤을 끄라고 하지 않습니다.  
*문서*

**I14** 릴리스 전마다 사람이 라이브 인수를 하며, 릴리스에는 두 절반이 모두 있어야 합니다.  
*문서; 모든 릴리스에서 지켜지지는 않았음*

**I15** 안전 검사는 스캐너 하나로 패키지 전체를 읽고, import는 아래나 옆으로만 향하며, 모듈 크기 상한은 줄어들기만 합니다.  
*테스트*: `srcscan.py`, `test_layers.py`, `test_sizes.py`

**I16** 영어 글이 바뀌면 모든 카탈로그에 반영하거나 검토했다고 표시합니다. 한국어 문서는 영어 문서가 말하지 않는 것을 주장하지 않으며, 모든 릴리스는 변경 이력의 자기 절을 유지합니다.  
*테스트*: `test_korean.py`, `test_privacy_claims.py`

**I17** 사용자가 보는 수정에는 회귀 테스트가, 안전에 관한 변경에는 그것이 없으면 실패하는 테스트가 함께 갑니다. 저장소의 역사는 다시 쓰지 않습니다. 하나뿐인 예외는 2026-09-27에 모든 커밋에서 개인정보를 지운 것입니다.  
*문서*

## J. 약속이 되는 표현 규칙

**J1** 증거 등급은 얻은 만큼만 주장합니다: 닫힌 집합, 인용한 테스트는 모두 존재, REAL CODEX VISUALLY TESTED 행은 없음, PUBLISHED는 게시된 바이트를 다시 돌려 본 곳에만.  
*형식만 테스트; 내용의 참과 PUBLISHED 규칙은 문서*: `test_feature_matrix.py`

**J2** 스크린샷은 생성기와 합성 데이터로 만들고, 손으로 고치지 않으며, 복구의 증거가 아니고, 입력이 바뀌면 다시 만듭니다.  
*테스트*: `test_screenshots.py`

**J3** 네트워크에 관한 주장은 한정어 없이 두지 않습니다. PRIVACY는 GitHub와 그 제3자를 밝히고, README의 개인정보 행은 "내려받기를 인정"해야 합니다.  
*테스트*: `test_privacy_claims.py`

**J4** 로드맵은 약속이 아니라 방향이며, 한계는 먼저 밝힙니다: 대화가 로드되어 있어야 하고, 실제 환경의 증거는 실행 한 번입니다.  
*문서*

**J5** 라이브 인수: 빈 디렉터리는 통과가 아니고, 사용 한도를 꾸며 내거나 상태를 고치지 않으며, 모든 클릭은 사람이 하고, 검증기는 참이 아니라 형태를 확인합니다.  
*형식만 테스트*: `test_live_evidence.py`

**J6** 승인 프롬프트가 뜬다고 주장하지 않습니다.  
*문서*

**J7** 상태를 부풀려 말하지 않습니다. 공개 상태는 설정이 아니라 레코드만의 순수 함수이고, failed는 최종이며 "재시도 중"이 아닙니다. 덧씌우는 표시는 보내지 않은 레코드에만 쓰고, 알 수 없음은 실행 중으로 읽히지 않으며, outcome_unverified는 성공이 아니고, "복구됨"은 우리 턴이 진행을 만들었을 때만 씁니다.  
*테스트; SKILL.md 부분은 모델*: `test_labels_v3.py`, `test_outcomes.py`, `test_control.py`, `test_engine.py`

**J8** 통계는 레코드마다 최종 결과 하나를 세고, 숨긴 행을 포함하며, 결과가 다섯 개 미만이면 성공률을 보이지 않습니다.  
*테스트*: `test_store.py`

**J9** 불확실한 전송은 불확실하다고 알리고, 알림은 하나마다 한 번만 띄우며, 멈춘 채 만들어진 레코드는 멈췄다고 알립니다.  
*테스트*: `test_engine.py`, `test_notice_card.py`

**J10** 카운트다운은 워처가 다시 본다는 뜻일 뿐입니다. 지금 다시 확인과 예산 되돌리기의 답에는 "모든 확인은 그대로 적용된다"는 단서가 남습니다.  
*테스트*: `test_tray_popup.py`, `test_control.py`, `test_mcp.py`

**J11** 모델은 명령이 출력한 것만 전하고, 다이제스트를 스스로 말하지 않으며, 네 단계를 모두 마친 뒤에만 "완전히 제거했다"고 말합니다.  
*모델*

**J12** 낱말 없이 색만 쓰지 않습니다. 대비는 글자 7:1, 보조 글자와 강조색 4.5:1, 포커스 테두리 3:1입니다.  
*대비는 테스트; 나머지는 문서*: `test_brand.py`, `test_focus_rings.py`

**J13** 호환성 낱말: 검증됨, 점검됨, 호환됨은 똑같이 보내고, 이 PC에서 실패와 호환되지 않음은 막습니다. 알 수 없음은 호환됨으로 보이지 않으며, 모든 화면이 관문의 낱말을 씁니다.  
*테스트*: `test_compat_surfaces.py`

**J14** 볼 때까지 빨강: 아이콘은 확실하고, 숨기지 않았고, 아직 보지 않은 실패로 그 뒤에 아무것도 시작하지 않았을 때만 빨갛게 되며, 본 시각은 앞으로만 움직입니다.  
*테스트*: `test_failure_seen.py`

## K. 고급판 자체의 기준

**K1** 표준판의 압축 파일과 설치 프로그램에는 고급판 코드가 없습니다. 압축 파일은 advanced/를 넣지 않은 트리들로 만들고, build/edition_audit.py가 릴리스를 빌드할 때마다, 무엇이든 남기기 전에 두 압축 파일과 두 설치 프로그램의 바이트로 이를 증명합니다. 어떤 항목, 글 파일, 바이너리, zip 안의 zip에도 고급판의 경로, 파일, 이름, 표시가 없고, advanced/를 지운 `git archive`로 다시 만든 표준판 압축 파일이 같은 파일이며, 표준판의 모든 항목이, 판마다 따로 빌드하는 설정 창과 매니페스트의 표시 이름만 빼고, 고급판 압축 파일에 바뀌지 않은 채 들어 있다는 것입니다. publish 작업은 목록을 다시 확인합니다.  
*테스트*: `build/edition_audit.py`, `test_edition_audit.py`, `test_edition_build.py`, `test_edition.py`

**K2** 업데이트는 판 안에 머뭅니다. 업데이트와 업데이트 확인이 권하는 프리 릴리스는 설치된 판의 압축 파일을 가져와, 설치본이 그 판과 그 버전에 고정한 다이제스트가 있으면 그것과, 없으면 옆에 게시된 .sha256과 비교합니다(지금은 모든 프리 릴리스와 모든 고급판 압축 파일이 그렇습니다). 다른 판을 만난 부트스트랩이나 설치 프로그램은, 그 전환을 요청하고 확인한 것이 아니면 무엇이든 옮기기 전에 거부하고, 먼저 그렇다고 말합니다. 판을 바꾸는 것은 설정과 대기 중인 복구를 그대로 두고 모든 고급 기능을 끈 채 시작하는 재설치입니다.  
*테스트*: `test_edition_bootstrap.py`, `test_edition_installer.py`, `test_prerelease_offer.py`

**K3** 켜는 것은 대시보드에서만. Arming.arm은 대시보드가 아닌 모든 주체를 거부하고, 한 번에 기능 하나씩만 받으며, 설명의 개정 번호, 세대, 경고, 그리고 켤 때는 대시보드가 보여 준 Codex 버전이 필요하고, 그 하나하나가 여전히 맞아야 합니다. 다른 모든 화면(MCP, 아이콘, 카드)은 기능을 끌 수만 있고, 클라이언트가 무엇을 보내든 켜는 MCP 도구는 없으며, 한 번 쓰고 끝나는 브리지는 플러그에 닿지 않습니다.  
*테스트*: `test_advanced_arming.py`, `test_advanced_surfaces.py`

**K4** 기본은 꺼짐이며, 벗어나야만 고급판입니다. 모든 기능은 꺼진 채 시작하고, 이 판으로 들어오면 모두 꺼지며, 지켜보는 기능이 스스로 켜짐으로 올라가지 않습니다. departs_from은 비어 있지 않고 표준판이 지키는 기준(0.1-0.7, A-J)만 적습니다. 그러므로 모든 기준을 지키는 기능은 표준판에 속합니다.  
*테스트*: `test_advanced_arming.py`, `test_advanced_registry.py`

**K5** 모든 기능보다 일시 정지와 동의가 먼저입니다. 코어는 동의 관문을 지난 뒤에만 플러그에 묻습니다. 일시 정지된 워처는 아무것도 묻지 않고, 꺼진 대화나 취소된 레코드는 넘기지 않으며, 전송 직전 확인 뒤에 확정된 일시 정지는 실행 보호 장치(launch guard)에서 경로나 채널을 멈추고, 일시 정지는 WMI로 무엇을 만들기 전에 Codex와 함께 시작을 멈춥니다. 모든 관문, 영속하는 선점, 전송 직전 확인은 코어의 것으로 남습니다.  
*테스트*: `test_plug_points.py`, `test_advanced_start_with_codex.py`, `test_advanced_marker_free.py`, `test_advanced_goal.py`

**K6** 실패한 측정은 사람이 확인하는 경고이며, 거부하는 것은 정책 키뿐입니다. 경로가 기대는 측정이 실패했거나 지금의 Codex에서 통과한 적이 없는 것, FAILED_HERE, INCOMPATIBLE, UNKNOWN 등급, 알 수 없는 Codex 버전은 설명에 보이고 켜면서 확인하는 것이지, 거부가 아닙니다(2026-09-26 소유자가 결정 C7을 대신해 정함). 거부하는 것은 HKLM과 HKCU의 Software\Policies\CodexAutoResume 아래 ForbidAdvanced, AllowedCapabilities, ForceShadow(켜기에 대해)이며, 읽기만 하고 쓰지 않습니다. 둘을 합치면 더 엄격한 쪽이고, 읽을 수 없으면 가장 엄격하게 봅니다.  
*테스트*: `test_advanced_arming.py`, `test_advanced_goal.py`, `test_advanced_marker_free.py`

**K7** 안전선(tripwire)은 기능을 끄며, 다시 켜는 것은 언제나 됩니다. 설명의 새 개정, 사람이 확인하지 않은 경고 가운데 기능이 기대는 것이 잘못되었다고 말하는 것(이 PC에서 실패, 로컬 확인 실패, 호환되지 않음, 측정 실패), 기능의 훅이 예외를 내는 것, 기능이 맡아 보낸 전송이 submission_unknown이 되는 것, 그리고 켜진 기능이라면 새 Codex 버전이 기능을 끕니다. 무엇이 껐든, 대시보드는 그때 읽히는 설명으로 기능을 다시 켤 수 있습니다.  
*테스트*: `test_advanced_arming.py`, `test_advanced_goal.py`, `test_advanced_marker_free.py`
