# 개발 과정

> 🌐 한국어 문서입니다. English version: [`main` 브랜치의 docs/DEVELOPMENT.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/DEVELOPMENT.md)

이 프로젝트는 한 명의 인간 관리자가 두 개의 AI 코딩 도구와 함께 네 단계에 걸쳐 만들었습니다. 여기에
기록하는 이유는 **조사 과정 자체가 이 프로젝트 가치의 큰 부분**이기 때문입니다. 대부분의 노력은 Windows
ChatGPT/Codex 데스크톱 앱이 실제로 무엇을 지원하는지 알아내고, 무엇을 **지원하지 않는지** 증명하는 데
들어갔습니다.

링크된 증거 파일의 식별자는 가명화되어 있고 절대 경로와 프로세스 ID는 일반화되어 있습니다. 대화 내용,
프롬프트 전문, 자격 증명은 로컬 기기를 벗어난 적이 없습니다.

그때의 발견들과 그 위에 쌓아 올린 모든 것이 *지금* 무엇으로 뒷받침되는지는 기능별로
[FEATURE_MATRIX.ko.md](FEATURE_MATRIX.ko.md)에 적혀 있고, 그중 실제 기계 앞의 사람만 매듭지을 수 있는 부분은
[LIVE_ACCEPTANCE.ko.md](LIVE_ACCEPTANCE.ko.md)의 절차입니다.

## Phase 0 — 목표와 안전 제약 (Youngbin Song)

관리자가 문제, 아키텍처 방향, 그리고 가장 중요하게는 이후 모든 결정을 규정한 안전 제약을 정의했습니다.

- 로컬 전용. 외부 서버 없음, telemetry 없음, 저장소나 대화 데이터 업로드 없음.
- Codex 자체 상태에 대해 읽기 전용. Codex 데이터베이스에 절대 쓰지 않음.
- **정확한** 중단 스레드를 재개. `--last` 금지, 추측한 스레드 금지.
- 같은 중단을 두 번 재개하지 않음.
- 불확실하면 멈춤: 모호함은 전송하지 *않는* 결과로 이어져야 함.
- 명시적으로 범위 밖: GUI 자동화, 마우스·키보드 흉내, OCR, 화면 스크래핑, 접근성 API 클릭, 바이너리 패치,
  DLL 인젝션, 프로세스 메모리 조작, 자격 증명 추출.

이것들은 선호가 아니라 **불변 조건**으로 취급되었습니다.

## Phase 1 — 조사 (OpenAI Codex)

Codex가 Windows ChatGPT 데스크톱 앱과 그 Codex 엔진의 실제 동작을 조사했습니다.

- 데스크톱 앱은 별도의 `codex.exe` 엔진 프로세스를 자식으로 실행하며 stdio로 연결합니다.
- 로컬 상태는 Codex home 디렉터리에 있습니다. 스레드 메타데이터, 페이지네이션된 턴/아이템 기록, 큐
  데이터베이스, JSONL rollout 파일, 그리고 스레드별 writer lock 파일입니다.
- 공식 CLI는 정확히 한 스레드를 대상으로 하는 `codex queue --thread <UUID>`를 제공합니다.
- 설치된 바이너리에서 app-server 프로토콜 스키마를 생성해 대응하는 업스트림 릴리스 태그와 비교했습니다.
  덕분에 어댑터는 추측이 아니라 검증된 버전에 고정되어 있습니다.

## Phase 2 — 되는 것과 안 되는 것 증명 (OpenAI Codex)

두 실험 모두 **일회용 테스트 스레드**로만 수행했고, 실제 대화는 건드리지 않았습니다.

**로드된 스레드: 됨.** 앱에 스레드가 이미 로드된 상태에서 `codex queue --thread <UUID>` 한 번 호출이 그
정확한 대화에 실제 사용자 메시지로 전달되었고 에이전트가 응답했습니다. 증거:
[`evidence/loaded-thread-delivery.json`](evidence/loaded-thread-delivery.json).

**미로드 스레드: 안 됨.** 실제로 앱을 재시작하고 대상 스레드가 `notLoaded`임을 확인한 뒤, 큐에 넣은 메시지
한 건이 90초 관찰 내내 큐에만 남아 있었고 대화 턴이 되지 못했습니다. 테스트 큐 항목은 이후 공식 API로
제거했습니다. 증거: [`evidence/unloaded-thread-delivery.json`](evidence/unloaded-thread-delivery.json),
[`evidence/unloaded-thread-observation.json`](evidence/unloaded-thread-observation.json).

이것이 이 제품의 핵심 제한이 생긴 이유입니다. 문서화된 발견이지 버그가 아닙니다.

**사용량 제한의 형태.** 실제 사용량 제한 중단을 읽기 전용으로 포착했습니다. 해당 턴은 `status=failed`와
`codexErrorInfo=usageLimitExceeded`로 기록되고, 바로 앞의 rate-limit 스냅샷이 UI에 표시된 시각과 분 단위로
일치하는 숫자형 리셋 타임스탬프를 담고 있었습니다. 특히 원본 rollout 이벤트 이름이 `task_complete`인데도
오류를 함께 담고 있으므로, **이벤트 이름만 보고 성공으로 판단해서는 안 됩니다.** 정제된 샘플:
[`evidence/usage-limit-sample.json`](evidence/usage-limit-sample.json).

Phase 2가 끝난 시점에 Codex는 detector, durable store, Windows 어댑터, 최초 스케줄러와 테스트 65개를
만들어 두었습니다. 그 작업은 이 저장소의 첫 커밋에 보존되어 있습니다.

## Phase 3 — 완성 (Anthropic Claude Code)

Claude Code가 미완성 프로토타입을 인수해 검토하고, 건전한 부분은 유지한 채 완성했습니다.

인수받은 코드에서 종단간 실행을 해봐야만 드러나는 잠복 버그 두 건을 발견했습니다.

- `collect()`가 detector 출력을 그대로 store에 넘겼는데, 여분 키 두 개 때문에 store가 이를 거부했습니다.
  결과는 치명적이었습니다. **어떤 중단도 등록되거나 재개되지 않았습니다.** watcher는 "detection skipped"만
  영원히 기록했습니다.
- 진입점이 `sys.exit()` 없이 `main()`을 호출해 모든 종료 코드가 0이 되었고, 단일 인스턴스 "busy" 신호가
  보이지 않았습니다.

이 단계에서 추가된 것: watcher 루프, 전체 CLI, 프롬프트를 기록하지 않는 회전 로그(`errors.log`에는 이
도구가 쓰지 않은 예외 문구가 담깁니다. `PRIVACY.ko.md` 참고), 선택적 사용자별 Windows 자동 시작,
깨끗한 제거, 설정 및 바이너리 탐색, 그리고 테스트 suite의 대폭 확장.

## Phase 4 — 검토와 적대적 감사 (Anthropic Claude Code)

세 차례의 검토를 수행했습니다. 각 회차는 차원별로 독립 리뷰어를 여러 명 두고, 이어서 세 명의 추가 독립
에이전트에게 모든 발견을 *반증*하도록 시켰습니다. 반증을 견딘 발견만 수정했습니다.

| 회차 | 범위 | 확인 | 반증 |
|---|---|---:|---:|
| 1 | detector, store, Windows 어댑터, 스케줄러 | 12 | 6 |
| 2 | CLI, app, config, 로깅, 자동 시작 | 3 | 0 |
| 3 | 9개 차원 최종 감사 | 8 | 3 |

확인되어 수정된 대표적 문제들:

- 로드 상태 프로브가 byte range가 순간적으로 비었을 때 **앱 자신의 배타적 스레드 writer lock을 획득**할 수
  있었고, 이는 앱 자체의 잠금 시도를 실패시킬 수 있었습니다. 잠금 코드를 통째로 제거하고, 소유 판정은
  재시작 관리자 목록만으로 하게 했습니다.
- `install --startup`이 환경변수로 설정된 home 디렉터리를 누락해, 자동 시작된 watcher가 다른 상태
  데이터베이스와 **다른 단일 인스턴스 뮤텍스**를 쓰게 만들었습니다.
- 제거가 자기가 만들지 않은 동명 파일을 지울 수 있었습니다. 이제 provenance marker를 요구하며, 직접 만들지
  않은 디렉터리는 건드리지 않습니다.
- 로그인 시점의 일시적 엔진 프로브 실패가 watcher를 세션 내내 종료시켰습니다.
- NTFS junction이 디렉터리 봉쇄 검사를 우회했습니다. `is_symlink()`가 junction을 감지하지 못하기 때문입니다.

반증된 발견도 기록해 둡니다. 예를 들어 "임의로 오래된 실패가 재개될 수 있다"는 주장은 반증되었습니다.
재개하려면 그 실패한 턴이 여전히 해당 스레드의 최신 턴이어야 하고, 전송 직전에 실시간 사용량 가용성을 다시
확인하기 때문입니다.

코드 검토 외에 세 가지 실증 기법을 사용했습니다.

- **뮤테이션 테스트.** 안전 가드 약 20개를 의도적으로 망가뜨려 테스트가 잡아내는지 확인했습니다. 살아남은
  3건이 실제 테스트 공백을 드러냈고 모두 제거 안전성 영역이었으며, 회귀 테스트를 추가했습니다. 이 과정에서
  `store.reserve()`의 가드 하나는 **없으면 실제로 이중 전송이 가능**함이 증명되었습니다.
- **crash-window 매트릭스.** 전송을 둘러싼 네 지점(예약 직후, CLI 실행 전, 전달 후 기록 전, 큐 등록 후 기록
  전)에서 프로세스를 강제 종료했습니다. 재시작 후 모든 경우에서 전송은 최대 1회였습니다.
- **교차 프로세스 경쟁.** 네 개 프로세스가 같은 중단 건을 두고 여덟 번 경쟁했고, 매번 정확히 하나만
  성공했습니다.

## 크레딧

[`../CONTRIBUTORS.md`](../CONTRIBUTORS.md)를 참고하세요. OpenAI Codex와 Anthropic Claude Code는 AI 개발
도구이지 인간 기여자나 GitHub 계정이 아닙니다. 저작권은 인간 관리자에게 있습니다.
