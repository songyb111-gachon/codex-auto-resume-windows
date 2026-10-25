# 기여자

> 🌐 한국어 문서입니다. English version: [`main` 브랜치의 docs/CONTRIBUTORS.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/CONTRIBUTORS.md)

이 프로젝트는 한 명의 인간 제작자가 두 개의 AI 개발 도구와 함께 만들었습니다. 아래 구분은 정직하게
기록한 것입니다. AI의 기여는 상당했고, 그 사실을 숨기지 않습니다.

## songyb111-gachon

프로젝트 창시자이자 제작자. 저작권자.

- 프로젝트 착상 및 목표 정의
- 요구사항 정의
- 안전 제약 정의 (로컬 전용, 읽기 전용, exact-thread, fail-closed, 그리고 사용 금지 기법 목록)
- 아키텍처 방향 결정
- 실제 Windows / ChatGPT / Codex 환경 제공 및 검증
- 테스트 및 검증 의사결정
- 최종 승인
- 배포 및 유지관리

## OpenAI Codex

*AI 지원 개발 기여.*

- Windows ChatGPT/Codex 데스크톱 앱 아키텍처 초기 조사
- Codex 프로토콜 및 로컬 상태 조사
- exact-thread queue 개념 증명
- loaded / notLoaded 동작 검증. 이 프로젝트의 핵심 제한을 규명한 실측을 포함합니다.
- `usageLimitExceeded` 및 재설정 시각 조사
- 감지기, 영속 저장소, Windows 어댑터, 최초 스케줄러의 초기 구현

## Anthropic Claude Code

*AI 지원 개발 기여.*

- Codex 프로토타입 인수 및 검토
- 워처 루프, CLI, Windows 통합, 영속성 완성
- 자동 테스트 확장
- 정확성 버그 수정. 인수받은 프로토타입을 종단간 동작 불능으로 만들던 버그 두 건 포함.
- 보안 검토 및 적대적 감사 (3회, 그리고 뮤테이션 테스트, crash-window 매트릭스, 교차 프로세스 경쟁 시험)
- 공개 배포 준비
- v0.6.x의 개발, 유지보수, 릴리스: 대시보드, 두 판, 설치 프로그램과 릴리스 자체. 릴리스마다의 내용은
  [CHANGELOG.ko.md](CHANGELOG.ko.md)에 있습니다

## 문제를 알리고, 제안하고, 시험해 주신 분들

아래는 모두 프로젝트 밖에서 도와 주신 분들이며, 처음 도와 주신 순서입니다.

- [@cervinho](https://github.com/cervinho) 님은 모든 복구가 끝나면 컴퓨터를 종료하거나 절전 상태로 두는 기능을
  요청했습니다([토론 #22](https://github.com/songyb111-gachon/codex-auto-resume-windows/discussions/22)).
- [@barkshah2002-pixel](https://github.com/barkshah2002-pixel) 님은 감지되지 않은 사용량 한도 중단을
  알렸고([#27](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/27)), 워처가 이어 가지 않은 실패한 턴을 이유와 함께 기록하자고 제안했습니다.
- [@ZionZhang42](https://github.com/ZionZhang42) 님은 그 감지 누락의 원인을 증명했습니다([#27](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/27)).
- [@aca22jy](https://github.com/aca22jy) 님은 Codex가 턴을 다른 ID로 기록하는 대화를 알렸고, 그에 앞서 데스크톱 대화에서 감지가 빠진 경우도 알렸습니다([#27](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/27), [#30](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/30)).
- [@Hunweibyn](https://github.com/Hunweibyn) 님은 사용량 한도를 미리 지켜보고 안전하게 멈췄다가 다시
  시작하자고 제안했습니다([#29](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/29)).
- [@Zephreo](https://github.com/Zephreo) 님은 실행 중이던 목표를 이어서 하자고 제안했습니다([#36](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/36)).
- [@Kdevaulo](https://github.com/Kdevaulo) 님은 Codex Desktop에서 이어 간 터미널 대화가 복구에서 빠지는 문제([#37](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/37))와
  GitHub에 닿지 못할 때 잘못 알려 주는 업데이트 상태([#41](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/41))를 알렸고,
  사용량 한도가 풀린 뒤 목표를 다시 이어 가게 하는 수정([#49](https://github.com/songyb111-gachon/codex-auto-resume-windows/pull/49))을 보내 주셨습니다.
- [@weng-wen-jun](https://github.com/weng-wen-jun) 님은 오래된 대기 중 복구를 정리하는 수동 '다시 살펴보고 정리'를
  요청했고([#39](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/39)), 이어서 대기열 메시지를 위한 대기 중과 편집 창, 그리고 지금 다시 확인과 다시 살펴보기의
  사용량 확인을 제안했습니다([#50](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/50)).
- [@zerocodefast](https://github.com/zerocodefast) 님은 이 프로젝트를 awesome-ai-plugins 목록에 초대하고 그곳의 등재를
  검토해 주셨습니다([#52](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/52)).

## AI 기여자에 대한 참고

**OpenAI Codex와 Anthropic Claude Code는 AI 개발 도구이지 인간 기여자나 GitHub 계정이 아닙니다.**

의미 있는 설계와 구현 작업을 수행했고, 소스를 읽는 사람이 이 코드가 어떻게 만들어졌는지 알 권리가 있기
때문에 여기에 기록합니다. 다만 의도적으로 다음은 하지 **않았습니다**.

- GitHub 계정, 프로필, 기여자 아바타 부여
- 저작권자로 명시
- 지어낸 이메일 주소 부여

Claude와 함께 쓴 커밋에는 그것을 쓴 Claude 모델의 이름을 밝히는 `Co-Authored-By` 트레일러가 붙어 있으며,
주소는 Anthropic 자신의 `noreply@anthropic.com`입니다. 사람은, 곧 제작자와 무언가를 신고하거나 제안한 모든 사람은
GitHub 로그인으로 기록합니다.

저작권은 인간 제작자에게 있습니다. 안전 속성을 포함한 이 코드에 대한 책임은 도구가 아니라 제작자에게
있습니다.

단계별 개발 과정은 [docs/DEVELOPMENT.ko.md](DEVELOPMENT.ko.md)를 참고하세요.
