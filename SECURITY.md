# 보안 검토 (Security review)

작성: 2026-09-06 (Claude Code, Phase 3). 대상: 이 저장소의 모든 구현 파일.

이 도구는 **로컬 전용**이며, 외부 네트워크 접속·telemetry·업로드가 없습니다. Python 코드는 소켓을 열지
않습니다. 모델 요청은 오직 원래 인증된 공식 Codex 바이너리가 처리합니다.

## 검토 방식

1. 정적 검토: 저자(Claude Code)가 모든 모듈을 직접 검토.
2. 적대적 다중 에이전트 검토 2회(각 5개 차원 리뷰 + 각 발견에 대해 3인 독립 반증 투표):
   - 1차: 핵심 4개 모듈(`source`, `store`, `windows`, `engine`) — 확인된 결함 12건, 모두 수정.
   - 2차: 신규/변경 모듈(`cli`, `app`, `config`, `logbook`, `startup`, 변경된 `windows/engine/source`) —
     확인된 결함 3건, 모두 수정:
     (a) 소유 디렉터리 가드가 NTFS junction을 놓침 → `Paths.confined()`(resolve 후 홈 포함) 확정 검사로
         `ensure`/`owned_*`/uninstall 전부 강화(실제 `mklink /J`로 회귀 테스트),
     (b) `settings.json` 임시 파일 고정 이름/경합 → `mkstemp`(O_EXCL) 고유 생성 + 오류를 `ConfigError`로,
     (c) watcher poll 간격 읽기가 crash-guard 밖 → `_poll_interval()`로 감싸 일시 오류 시 안전 폴백.
3. 실환경 읽기 전용 통합 검증(`tests/test_integration_live.py`, opt-in): 어떤 대화에도 전송하지 않음.

## 위협 항목별 결론

- **토큰/자격 증명 유출**: Python은 `auth.json`, 토큰, 쿠키, 프로세스 메모리를 읽지 않습니다.
  `Backend._environment`는 `CODEX_HOME`만 설정하고 나머지는 공식 바이너리가 자신의 인증 컨텍스트로
  처리합니다. 프로토콜 클라이언트는 `initialize`, `account/rateLimits/read`, `thread/queue/delete` 세
  메서드만 허용하며 로그인/재개/턴 시작을 거부합니다.
- **로그/상태 기밀 유출**: 로그(`logbook`)는 정적 사유 코드 + 타임스탬프 + UUID + 정수만 기록합니다.
  `_safe_detail`은 16진/숫자 형태가 아닌 값을 `?`로 마스킹하고, 스레드 ID는 canonical UUID일 때만
  붙입니다. 프롬프트 전문·오류 전문·사용량 계정 필드는 파싱 단계에서 폐기됩니다(`parse_usage`는
  숫자 필드만 allowlist). 예외 스택은 `errors.log`에만 남고 본 로그에는 예외 클래스명만 남깁니다.
- **subprocess / shell injection**: 모든 외부 실행은 `shell=False`의 argv 리스트입니다. 스레드 ID는
  `canonical_uuid`로, continuation은 고정 문자열 + marker로만 구성됩니다. CLI의 `cancel/enable/disable`은
  `canonical_thread_id`로 UUID를 강제하며 `--last`나 임의 문자열을 거부합니다. PowerShell 인벤토리는
  고정 스크립트에 인자 주입이 없습니다.
- **네트워크 접속**: Python 측 소켓 없음. 공식 바이너리의 정상 모델 요청과 본 도구의 데이터 유출은
  구분되며, 후자는 존재하지 않습니다.
- **경로 traversal / symlink·reparse·junction**: 소유 디렉터리·상태 파일은 symlink면 거부하고,
  추가로 `Paths.confined()`가 **resolve 후 홈 내부인지**를 확정 검사하여 NTFS junction(관리자 불필요,
  `is_symlink()`가 놓침)으로 홈 밖으로 리디렉션하는 경우 `ensure`/`owned_*`/uninstall 모두에서 거부합니다.
  `source._safe_path`는 `\\?\` 확장 경로를 정규화하고, rollout 경로는 `sessions/` 하위로 confine하며
  `.jsonl` 접미사와 파일명에 thread_id 포함을 요구합니다. SQLite는 `mode=ro` + `query_only=ON`.
- **불안전 임시 파일**: 설정 저장은 `tempfile.mkstemp`(O_EXCL)로 고유 임시 파일을 만든 뒤 원자적
  `os.replace`하며, 실패 시 임시 파일을 정리하고 `ConfigError`로 감쌉니다(고정 이름/경합/write-through
  없음). 상태 DB는 `synchronous=FULL`.
- **race / 중복 재개**: 전송 직전 durable `reserve`(단일 트랜잭션, `BEGIN IMMEDIATE`). 디스패치 구간은
  프로세스 뮤텍스 + 재확인(app identity, loaded, usage) 후에만 진행. 전송 성공이 모호하면
  `submission_unknown`으로 정지하고 자동 재전송하지 않음. 정리·전달 판정은 스레드별 고유 marker로만.
- **corrupted state**: 스키마·무결성(`quick_check`)·레코드 검증 실패 시 fail-closed로 열기를 거부하고
  기존 파일을 덮어쓰지 않습니다.
- **단일 인스턴스**: 사용자별 named mutex로 중복 watcher를 거부(교차 프로세스 검증 완료, 실환경에서
  두 번째 `run`이 BUSY 종료코드 3 반환 확인).
- **앱 파일 간섭**: `loaded()`는 Restart Manager로 소유자를 먼저 확인하고, 서버가 파일을 이미 연
  경우에만 byte-lock을 관찰합니다(획득하지 않음). 비어 있으면 `notLoaded`. 이로써 앱의 writer lock과
  경합하지 않습니다.
- **악성 저장소 입력**: rollout/queue/스레드 제목 등 저장소가 통제하는 입력은 데이터로만 취급합니다.
  큐 payload는 버전 고정 serde 형태만 인정하고, 사용량/오류 필드는 allowlist 파싱하며, 알 수 없는 값은
  fail-closed 처리합니다.
- **uninstall 안전성**: 소유 파일 이름 패턴(`state.sqlite*`, `settings.json`, `auto-resume.log[.N]`,
  `errors.log[.N]`)에 맞는 것만 삭제하고, 빈 소유 디렉터리만 제거합니다. ChatGPT/Codex 파일이나 사용자
  저장소는 삭제하지 않습니다. 관리자 권한을 요구하지 않으며 autostart는 `HKCU\...\Run`만 사용합니다.

## 알려진 잔여 위험

- 실제 차단 버킷을 항상 특정하지 못함. 큐잉 직전 실시간 가용성 재확인으로 보완하되, 100% 보장은 아님.
- 버전 핀(`codex-cli 0.153.4`)과 검증된 로컬 스키마 의존. 다른 버전에서는 fail-closed로 동작 거부 가능.
- 미로드 스레드는 자동 재개하지 않음(설계상 안전 대기). README의 제한 사항 참조.
