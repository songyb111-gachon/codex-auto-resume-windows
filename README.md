# codex-auto-resume

로컬 전용 Windows 도구입니다. Windows ChatGPT/Codex 데스크톱 앱에서 **사용량 제한(usage limit)** 으로
중단된 Codex 스레드를, 제한이 풀린 뒤 **같은 대화에서 자동으로 이어서** 진행시킵니다.

## 먼저 반드시 읽어야 할 제한 사항

- 현재 이 도구는 **Windows ChatGPT/Codex 앱에 이미 로드(loaded)되어 있는 스레드만** 자동 재개할 수 있습니다.
- 앱을 재시작한 뒤 대상 스레드가 **`notLoaded`** 상태이면, 그 스레드를 **프로그램적으로 깨우는(로드하는)
  지원된 방식은 현재 확인되지 않았습니다.** 미로드 상태에서 `codex queue`로 넣은 메시지는 큐에만 남고
  대화 턴으로 전달되지 않는 것이 실측으로 확인되었습니다.
- 따라서 미로드 스레드는 **사용자가 ChatGPT 앱에서 해당 대화를 직접 열어 `loaded` 상태로 만든 이후에만**
  자동 재개됩니다. 그 전까지 이 도구는 안전하게 `waiting_for_loaded_thread` 상태로 **대기**하며, 화면
  자동화나 강제 로드, 무작정 큐잉을 하지 않습니다.
- 이 도구는 "완전 무인 자동 재개"가 아닙니다. 위 제한을 숨기거나 과장하지 않습니다.

This tool can only auto-resume a Codex thread that the Windows ChatGPT/Codex app currently has **loaded**.
After an app restart a target thread is `notLoaded`, and there is **no verified supported way to wake an
unloaded thread programmatically** — a queued message stays in the queue and is not delivered as a turn.
Such threads resume automatically **only after you open the conversation in the ChatGPT app yourself**; until
then the tool waits safely. It is not fully unattended auto-resume.

## 무엇을 하는가

```
usage limit 도달  →  로컬 watcher가 usageLimitExceeded 감지  →  정확한 thread UUID 저장
   →  reset timestamp까지 대기  →  앱 실행/서버 확인  →  대상 thread가 loaded인지 확인
   →  loaded이면  codex queue --thread <UUID>  로 continuation 전달  →  같은 thread가 원래 작업 계속
```

continuation 메시지의 의미: "사용량 제한으로 중단된 이전 작업을 계속 진행해. 먼저 현재 스레드 컨텍스트와
실제 저장소/파일 상태를 확인하고, 이미 완료된 작업은 반복하지 말고 원래 목표를 계속 수행해."

## 안전 원칙 (설계 불변식)

- **로컬 전용.** 외부 서버·telemetry·업로드 없음. Python 자체는 네트워크에 접속하지 않습니다. 모델 요청은
  원래 인증된 공식 Codex 바이너리가 처리합니다.
- **읽기 전용 감지.** Codex의 로컬 상태(`state_5.sqlite`, `thread_history_1.sqlite`, `queue_1.sqlite`,
  rollout JSONL)는 `mode=ro`로만 읽습니다. Codex DB에 쓰지 않습니다.
- **금지된 방식 없음.** AutoHotkey, 마우스/키보드 흉내, OCR, 화면 인식, UI scraping, Accessibility 클릭,
  바이너리 수정/패치, DLL injection, 메모리 조작, 토큰/쿠키 추출, TLS 가로채기를 사용하지 않습니다.
- **정확한 스레드만.** `--last`를 쓰지 않습니다. 실제 중단이 일어난 정확한 thread UUID만 대상으로 하며,
  continuation은 argv 기반 subprocess로 전달합니다(shell 문자열 조합 없음).
- **중복 재개 방지.** 전송 직전에 상태를 durable하게 예약(reserve)하고, 전송 성공 여부가 모호하면
  자동 재전송하지 않고 `submission_unknown`으로 안전하게 멈춥니다. 스레드당 고유 marker로만
  전달/큐 정리를 판정합니다.
- **기밀 미기록.** 프롬프트 전문·오류 전문·사용량 계정 정보·자격 증명은 로그/상태에 남기지 않습니다.

## 요구 사항

- Windows 11, Python 3.12+ (표준 라이브러리만 사용, 외부 패키지 없음).
- 공식 Windows ChatGPT/Codex 앱 및 그 실행 엔진 `codex.exe` (검증된 버전 핀: `0.153.4`).
  기본 위치는 `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe` 입니다.

## 설치

```bash
python src/auto_resume.py install
```

- 소유 디렉터리 `config/`, `logs/`를 만듭니다(멱등, 여러 번 실행해도 중복 없음).
- Windows 로그인 시 자동 시작(선택, 관리자 권한 불필요, 현재 사용자 `HKCU\...\Run`만 사용):

```bash
python src/auto_resume.py install --startup
```

기본 설치는 자동 시작을 강제하지 않습니다. 자동 시작을 켜도 `pythonw.exe`로 콘솔 창 없이 watcher를 실행합니다.

## 사용

```bash
python src/auto_resume.py enable            # 전역 자동 재개 켜기 (kill switch 해제)
python src/auto_resume.py run               # watcher 실행 (단일 인스턴스, 포그라운드)
python src/auto_resume.py status            # 전역/스레드/watcher/자동시작/엔진/카운트
python src/auto_resume.py pending           # 대기 중인 중단 목록
python src/auto_resume.py logs -n 50        # 최근 로그
python src/auto_resume.py disable           # kill switch: 즉시 모든 자동 재개 중단
python src/auto_resume.py stop              # 실행 중인 watcher에 종료 요청
```

스레드 단위 제어:

```bash
python src/auto_resume.py enable  <thread-uuid>   # 특정 스레드만 켜기
python src/auto_resume.py disable <thread-uuid>   # 특정 스레드만 끄기 (기록은 유지, 전송 안 함)
python src/auto_resume.py cancel  <thread-uuid>   # 특정 스레드의 대기 재개 취소 + 비활성화
```

진단(모두 읽기 전용):

```bash
python src/auto_resume.py doctor
```

`enable` 시점 기준으로 과거 실패도 일정 시간 안쪽이면 대상에 포함됩니다(기본 6시간). 변경:

```bash
python src/auto_resume.py enable --lookback-hours 3
```

## Kill switch

`disable`(전역)는 **즉시** 모든 자동 재개를 막습니다. 대기 상태(pending)는 삭제되지 않고 보존되지만,
비활성화 동안에는 어떤 continuation도 큐잉되지 않습니다. 이미 전송된 항목의 안전한 정리(reconcile)만
계속됩니다.

## 사용량 제한(reset) 처리

- 로컬 상태에서 실제 reset timestamp를 확인할 수 있으면 그 시각까지 대기합니다(고정 5시간 sleep 아님).
- reset timestamp를 특정할 수 없으면 보수적 폴링(conservative polling)으로 대기하며, 큐잉 직전에
  공식 프로토콜로 **실시간 사용량 가용성**을 다시 확인합니다. 가용이 아니면 큐잉하지 않습니다.
- `usageLimitExceeded`는 여러 quota/usage 오류가 합쳐진 코드이므로 실제 차단 버킷을 100% 특정한다고
  가정하지 않습니다. 불확실하면 안전하게 대기합니다.

## 재시도/backoff

큐 프로세스가 시작조차 못한(전송 미발생이 증명된) 경우에만 재시도하며, 30초 → 1분 → 2분 → 5분 →
이후 5분 유지의 bounded exponential backoff를 사용합니다. 전송 후 결과가 모호하면 재전송하지 않습니다.

## 제거(uninstall)

```bash
python src/auto_resume.py uninstall             # 자동시작 해제, watcher 종료, 소유 상태/로그 삭제
python src/auto_resume.py uninstall --keep-logs # 로그는 남김
```

- 제거 대상: 로그인 자동 시작 등록, 이 도구가 만든 상태(`config/state.sqlite*`, `settings.json`)와 로그.
- **ChatGPT/Codex 자체 파일, 사용자 저장소, 임의의 다른 파일은 절대 삭제하지 않습니다.** 소유 파일 이름
  패턴에 맞는 것만 지웁니다.

## 상태 파일과 로그

- 상태: `config/state.sqlite` (SQLite, `synchronous=FULL`, 프로세스 crash에도 예약이 durable).
- 로그: `logs/auto-resume.log` (회전 rotation 적용). 오류 스택은 `logs/errors.log`에만 남고 본 로그에는
  정적 사유 코드/타임스탬프/UUID만 남깁니다.
- 기본 루트는 이 프로젝트 디렉터리입니다. `--home <경로>` 또는 환경변수 `CODEX_AUTO_RESUME_HOME`로 변경.

## 테스트

```bash
# 단위/시나리오 테스트 (안전, 실제 대화를 건드리지 않음)
set PYTHONPATH=src   &&   python -m unittest discover -s tests

# 실환경 읽기 전용 통합 확인 (선택). 어떤 대화에도 메시지를 보내지 않습니다.
set CODEX_AR_LIVE=1  &&  set PYTHONPATH=src  &&  python -m unittest tests.test_integration_live
```

단위 테스트는 필수 시나리오 18가지(완료/중단/일반 실패/malformed → 무동작, usageLimitExceeded → 등록,
중복 1회 등록, reset 전 큐 금지, reset 후 loaded 재개, notLoaded 대기, 사용자가 열어 loaded → 재개,
앱 닫힘/전역 disable/스레드 disable → 큐 금지, watcher 재시작 시 pending 유지, 큐 실패 → backoff,
중복 watcher 1개만 동작, 다중 스레드 동시 pending, 한 스레드 실패가 다른 스레드를 재개하지 않음)를
포함합니다.

## 알려진 한계 (요약)

- 미로드 스레드 자동 깨우기 미지원 (위 "먼저 반드시 읽어야 할 제한 사항" 참조).
- 실제 차단 버킷을 항상 특정하지는 못함 → 큐잉 직전 실시간 가용성 재확인으로 보완.
- 버전 핀(`codex-cli 0.153.4`) 및 검증된 로컬 스키마에 의존. 다른 버전에서는 안전하게 동작을 거부할 수
  있습니다(fail-closed).
