# Codex Auto Resume

**Windows에서 중단된 Codex 작업을 안전하게 이어서 진행합니다.**

[![tests](https://github.com/songyb111-gachon/codex-auto-resume-windows/actions/workflows/test.yml/badge.svg)](https://github.com/songyb111-gachon/codex-auto-resume-windows/actions/workflows/test.yml)
[![latest release](https://img.shields.io/github/v/release/songyb111-gachon/codex-auto-resume-windows?label=release)](https://github.com/songyb111-gachon/codex-auto-resume-windows/releases/latest)
[![platform: Windows 10/11](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078d4)](#설치)
[![license: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

<sub>🇺🇸 <a href="README.md">English README</a></sub>

긴 작업 도중에 Codex 사용량 한도에 걸리거나, rate limit이 나거나, 연결이 끊긴 적 있으신가요?
Codex Auto Resume는 안전해질 때까지 기다렸다가 **바로 그 대화**를 이어서 진행시킵니다. 돌아왔을 때
멈춰 있는 작업이 아니라 끝난 작업을 보게 됩니다.

Windows ChatGPT/Codex 데스크톱 앱을 위한 작은 로컬 watcher입니다. Codex의 로컬 상태를 읽기 전용으로
관찰하고, 무엇이 실패했는지 분류한 뒤, 공식 `codex queue` 명령으로 continuation 메시지 한 건을
보냅니다. 아무것도 이 PC 밖으로 나가지 않습니다.

**모든 실패를 재시도하지는 않습니다.** 이름 붙일 수 없는 실패는 건드리지 않습니다.

|  |  |
| --- | --- |
| **복구합니다** | Codex 사용량 한도 · rate limit(HTTP 429) · 네트워크 장애 · 타임아웃 · 일시적 서버 오류(5xx) · 스트림 끊김 |
| **손대지 않습니다** | 사용자 취소 · 권한 · 승인 필요 · 콘텐츠 정책 · 잘못된 요청 · 컨텍스트 길이 초과 · 영구 인증 실패 · 분류되지 않은 모든 것 |
| **식별 방식** | 정확한 대화 UUID 하나. `--last`도, "가장 최근 것"도, 제목이나 폴더 이름도 쓰지 않습니다 |
| **설정 방법** | Windows 설정 창, Codex 안의 설정 패널, 명령줄 |
| **알려줍니다** | 중단 감지 · 복구 시작 · 결과 · 복구 중단 시 Windows 알림 |
| **보내지 않습니다** | 완전한 로컬 동작. 텔레메트리 없음, 계정 접근 없음, 자체 네트워크 통신 없음 |

> **먼저 알아두실 제한 하나.** 복구 메시지가 전달되려면 Codex가 그 대화를 열어 둔 상태여야 합니다.
> 앱을 재시작했다면 그 대화를 한 번만 열어 주시면 이후는 알아서 진행됩니다.
> [왜 그런지](#먼저-읽어야-할-제한-사항)

## 설치

**Windows 10/11. Python 불필요. 관리자 권한 불필요.**

1. [최신 릴리스](https://github.com/songyb111-gachon/codex-auto-resume-windows/releases/latest)에서
   `CodexAutoResume-<버전>-win-x64.zip`을 받습니다.
2. 아무 곳에나 압축을 풉니다.
3. **`Install.cmd`**를 더블클릭합니다.

이게 전부입니다. 압축 파일이 자체 Python 런타임을 담고 있어서 미리 설치할 것이 없고, 끝나면 권장
설정이 이미 켜져 있습니다. `Install.cmd`를 다시 실행하면 그 자리에서 업그레이드하면서 대기 중인
재개를 그대로 유지하고, `Uninstall.cmd`가 되돌립니다.

설치 후에는 **시작 메뉴 → Codex Auto Resume**에서, 또는 Codex에게 *auto resume 설정 열어줘* 라고
말해서 설정을 바꿀 수 있습니다.

## 화면

작업이 중단되면 Windows가 알려줍니다. 보내는 주체는 알림을 띄운 프로세스가 아니라
**Codex Auto Resume**로 표시됩니다. 아무것도 하지 않으면 재개되고, 버튼은 취소만 합니다.

<img src="docs/images/notification.png" alt="Codex Auto Resume가 보낸 Windows 알림. 사용량 한도에 도달했고 초기화 후 재개한다는 내용과 재개하지 않음 버튼" width="470">

설정은 Codex를 꺼 둔 상태에서도 시작 메뉴에서 전부 바꿀 수 있습니다.

<img src="docs/images/settings-window.png" alt="Codex Auto Resume 설정 창. 복구할 장애 종류, 시도 상한, 재시도 간격, 알림 스위치" width="680">

## 먼저 읽어야 할 제한 사항

이 도구는 Windows ChatGPT/Codex 데스크톱 앱이 **현재 로드하고 있는 스레드만** 자동 재개할 수 있습니다.

앱을 재시작하면 대상 스레드는 `notLoaded` 상태가 됩니다. 그리고 **미로드 스레드를 프로그램적으로 깨우는
지원된 방식은 확인되지 않았습니다.** 미로드 스레드에 큐로 넣은 메시지는 큐에만 남고 대화 턴으로
전달되지 않습니다. 추측이 아니라 실측한 결과이며 증거는
[`docs/evidence/unloaded-thread-delivery.json`](docs/evidence/unloaded-thread-delivery.json)에 있습니다.

따라서 미로드 스레드는 **사용자가 ChatGPT 앱에서 그 대화를 직접 열어야만** 이후 자동 재개됩니다.
그전까지 watcher는 `waiting_for_loaded_thread` 상태로 조용히 기다립니다. 화면 자동화를 쓰지 않고,
대화를 강제로 열지 않으며, 혹시나 하는 마음으로 메시지를 큐에 넣지도 않습니다.

즉 **앱 재시작을 넘나드는 완전 무인 자동 재개가 아닙니다.** 이 문서는 그렇지 않은 척하지 않습니다.

## 무엇을 복구하고 무엇을 복구하지 않는가

자동으로 복구합니다:

| 장애 | 정책 |
| --- | --- |
| 사용량 한도 (`usageLimitExceeded`) | 실제 리셋 시각까지 기다린 뒤 실시간 사용량을 다시 확인 |
| 연결 실패 (`httpConnectionFailed`) | 상한 있는 backoff |
| 타임아웃 (HTTP 408/425) | 상한 있는 backoff |
| 일시적 rate limit (HTTP 429, `rateLimitExceeded`) | 상한 있는 backoff |
| 서버 오류 (HTTP 5xx, `serverOverloaded`, `internalServerError`) | 상한 있는 backoff |
| 스트림 끊김 (`responseStreamDisconnected`, `responseStreamConnectionFailed`) | 상한 있는 backoff |

절대 복구하지 않습니다. 사람이 판단해야 하고, 재시도는 시도 횟수만 낭비합니다:

사용자 취소 · 권한 · 승인 필요 · 콘텐츠 정책 · 잘못된 요청 · 컨텍스트 길이 초과 ·
영구 인증 실패 (401/403, `unauthorized`) · `badRequest` · `sandboxError` ·
`responseTooManyFailedAttempts` · **분류되지 않은 모든 것**.

분류는 구조적으로 합니다. Codex가 기록하는 `codexErrorInfo` variant를 먼저 보고, 그 variant가 담은
HTTP status를 봅니다. 메시지 문구는 구조화된 코드가 아예 없을 때만, 그리고 코드가 없는 전송 계층
장애에 한해서 참고합니다. 구조화된 코드를 메시지 문구가 뒤집는 일은 없습니다.

복구에는 두 겹의 상한이 있습니다. 하나의 중단마다 최대 4회, 그리고 눈에 보이는 진전 없이 3번 연속
복구되면 멈춥니다. 사용자가 그 대화를 직접 이어서 진행했다면 오래된 중단은 그 위에 덮어쓰지 않고
버립니다.

## 정확히 그 대화만

복구 대상은 언제나 **정확한 대화 UUID**로만 지정됩니다. `--last`를 쓰지 않고, "가장 최근 스레드"를
고르지 않으며, 제목·프로젝트 이름·작업 디렉터리·최근 사용 순서로 대화를 찾지 않습니다. 알림에 보이는
이름은 표시용일 뿐이고, 식별에는 쓰이지 않습니다.

## 설정

설정은 한 곳에 있고 세 가지 방법으로 접근합니다.

- **시작 메뉴 → Codex Auto Resume** — 독립 실행 창입니다. Codex가 꺼져 있어도, 플러그인이 비활성이어도,
  네트워크가 없어도, 로그인하지 않았어도, 시스템 Python이 없어도 동작합니다. 설정이 가장 필요한
  순간은 설정 대상이 동작하지 않을 때이기 때문입니다.
- **Codex 안에서** — auto resume 설정을 열어 달라고 하면 대화 안에 패널이 나타납니다.
- **명령줄** — 스크립트와 복구용입니다.

셋 다 같은 파일을 같은 검증기로 씁니다. 한쪽에서 바꾼 값이 다른 쪽에서 그대로 보입니다. 외울 것도,
직접 편집할 것도 없습니다. 손으로 쓴 설정 파일은 읽을 때 검증되므로, 잘못된 값은 조용히 안전한
기본값으로 대체되고 사용자는 바꿨다고 착각하게 됩니다.

바꿀 수 있는 것: 어떤 분류된 장애를 복구할지, 중단 하나당 몇 번 시도할지, 진전 없는 복구가 몇 번
이어지면 포기할지, 시도 간격, 그리고 어떤 알림을 띄울지.

**안전 속성은 설정이 아닙니다.** 분류되지 않은 장애를 재시도하거나, 제목으로 대화를 찾거나, 결과가
불확실한 전송을 다시 보내거나, 강제로 전송하는 옵션은 없습니다. 빠뜨린 것이 아니라 그렇게 설계했습니다.

## 알림

중단이 기록되면 Windows 알림이 한 번 뜹니다. 보내는 주체는 **Codex Auto Resume**로 표시되고 이
프로젝트의 아이콘이 함께 나옵니다. PowerShell이나 Python 이름은 보이지 않습니다.

이후 세 가지 알림이 더 있습니다. 복구 시작, 결과, 그리고 복구를 완전히 중단했을 때. 각각 상태 변화
자체에서 한 번만 발생하므로 알림 내용과 기록된 상태가 어긋날 수 없습니다.

첫 알림의 버튼은 **취소 전용**입니다. 아무것도 하지 않으면 재개되고, 버튼을 누르면 그 대화 하나의
자동 재개만 취소됩니다. 악의적이거나 잘못된 URI가 재개를 *발생시킬* 수는 없습니다.

알림은 표시용 이름, 로컬 시각, 대화 UUID만 담습니다. 프롬프트 내용, 오류 본문, 계정 정보는 담지
않습니다. 알림이 실패해도 복구 동작은 그대로 진행됩니다.

## 개인정보

이 도구는 아무것도 전송하지 않습니다. 텔레메트리, 분석, 크래시 리포트, 업데이트 확인이 없고, 자체
네트워크 요청 자체가 없습니다. 프롬프트, 어시스턴트 응답, 도구 입출력, 파일 내용, 계정 식별자,
자격 증명, 오류 본문 중 어느 것도 개발자에게 가지 않습니다.

상태는 전부 `%USERPROFILE%\.codex-auto-resume\` 아래에 있습니다. 자세한 내용은
[PRIVACY.md](PRIVACY.md)를 참고하세요.

## 제거

`Uninstall.cmd`를 실행하면 됩니다. 기본적으로 설정과 대기 중인 재개는 남겨 두므로 다시 설치해도
잃지 않습니다. 전부 지우려면 purge 옵션을 쓰거나
`%USERPROFILE%\.codex-auto-resume\` 폴더를 직접 지우면 됩니다.

Codex 대화는 어떤 경우에도 건드리지 않습니다.

## 도움말 · 보안

- 문제 신고와 진단 방법: [SUPPORT.md](SUPPORT.md)
- 보안 취약점 신고: [SECURITY.md](SECURITY.md)
- 기여 방법: [CONTRIBUTING.md](CONTRIBUTING.md)

공개 이슈에 자격 증명, 토큰, 비공개 대화 전문, 비공개 저장소 내용을 붙여넣지 말아 주세요. 진단에
필요하지 않습니다.

## 그 밖의 문서

영어 [README](README.md)에 명령줄 사용법, 안전 모델, 아키텍처가 더 자세히 있습니다. 플러그인 구조와
사용량 한도 안내에 체크박스를 넣지 못하는 이유는 [docs/PLUGIN.md](docs/PLUGIN.md)에 있습니다.

## 라이선스

MIT. [LICENSE](LICENSE)를 참고하세요.
