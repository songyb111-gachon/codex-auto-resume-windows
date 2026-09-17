# 기여자

> 🌐 한국어 문서입니다. English version: [`main` 브랜치의 CONTRIBUTORS.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/CONTRIBUTORS.md)

이 프로젝트는 한 명의 인간 관리자가 두 개의 AI 개발 도구와 함께 만들었습니다. 아래 구분은 정직하게
기록한 것입니다. AI의 기여는 상당했고, 그 사실을 숨기지 않습니다.

## Youngbin Song

프로젝트 창시자이자 관리자. 저작권자.

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
- `usageLimitExceeded` 및 리셋 타임스탬프 조사
- detector, durable store, Windows 어댑터, 최초 스케줄러의 초기 구현

## Anthropic Claude Code

*AI 지원 개발 기여.*

- Codex 프로토타입 인수 및 검토
- watcher 루프, CLI, Windows 통합, 영속성 완성
- 자동 테스트 확장
- correctness 버그 수정. 인수받은 프로토타입을 종단간 동작 불능으로 만들던 버그 두 건 포함.
- 보안 검토 및 적대적 감사 (3회, 그리고 뮤테이션 테스트, crash-window 매트릭스, 교차 프로세스 경쟁 시험)
- 공개 배포 준비

## AI 기여자에 대한 참고

**OpenAI Codex와 Anthropic Claude Code는 AI 개발 도구이지 인간 기여자나 GitHub 계정이 아닙니다.**

의미 있는 설계와 구현 작업을 수행했고, 소스를 읽는 사람이 이 코드가 어떻게 만들어졌는지 알 권리가 있기
때문에 여기에 기록합니다. 다만 의도적으로 다음은 하지 **않았습니다**.

- 지어낸 이메일 주소로 커밋 author나 co-author에 넣기
- GitHub 계정, 프로필, 기여자 아바타 부여
- 저작권자로 명시

저작권은 인간 관리자에게 있습니다. 안전 속성을 포함한 이 코드에 대한 책임은 도구가 아니라 관리자에게
있습니다.

단계별 개발 과정은 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)를 참고하세요.
