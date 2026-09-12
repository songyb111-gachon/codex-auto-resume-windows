# 릴리스 검증하기

> 🌐 한국어 문서입니다. English version: [`main` 브랜치의 docs/VERIFY.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/VERIFY.md)

설치하려는 압축 파일이 이 프로젝트가 게시한 바로 그 파일인지 확인하는 방법, Codex 플러그인이
대신 확인해 주는 것, 릴리스를 직접 다시 빌드하는 방법, 그리고 이 모든 것이 다루지 못하는 부분을
적어 둡니다.

## 왜 확인해야 하는가

릴리스 압축 파일에서 풀어낸 것은 사용자 본인의 권한으로 실행됩니다. 따로 끄지 않는 한 로그인할
때마다 시작되어 Codex 대화에 메시지를 대기열로 넣을 수 있는 워처를 설치하고, Codex가 실행하는
플러그인을 등록합니다.

`Install.cmd`는 자신이 들어 있던 압축 파일을 확인하지 않습니다. 그것이 실행될 때는 이미 압축이 풀린
뒤이고, 설치 프로그램은 진짜 다운로드와 변조된 파일을 구별할 수 없습니다. 확인은 압축을 풀기 전에
해야 하고, 수동 경로에서는 그 확인을 직접 해야 합니다.

이 프로젝트가 빌드하는 프로그램과 스크립트에는 코드 서명이 없으므로(함께 들어 있는 Python
인터프리터는 배포될 때의 서명을 그대로 가지고 있습니다. Python Software Foundation의 서명이고, Visual
C++ 런타임 DLL 두 개에는 Microsoft의 서명입니다. [코드 서명](#코드-서명) 참고),
보통이라면 게시자를 알려 줄 Windows 대화 상자가 이 파일들에 대해서는 알려 줄 게시자가 없습니다.
다이제스트가 곧 확인 수단입니다.

## 내려받은 압축 파일을 풀기 전에

[릴리스 페이지](https://github.com/songyb111-gachon/codex-auto-resume-windows/releases)에서
`CodexAutoResume-vX.Y.Z-win-x64.zip`과 그 옆에 게시된 `.sha256` 파일을 내려받습니다. 아직 아무것도
풀지 마세요. 저장한 폴더에서 PowerShell로 다음을 합니다.

1. **압축 파일의 해시를 구합니다.**

   ```powershell
   (Get-FileHash .\CodexAutoResume-vX.Y.Z-win-x64.zip -Algorithm SHA256).Hash
   ```

   `Get-FileHash`는 다이제스트를 대문자로 출력하고, 게시된 값은 소문자입니다. 대소문자를 무시하고
   비교하세요. PowerShell의 `-eq`는 원래 대소문자를 구분하지 않으므로, 아래의 비교는 모두 `True`나
   `False`를 출력합니다.

2. **압축 파일 옆에 게시된 `.sha256`과 비교합니다.**

   ```powershell
   $hash = (Get-FileHash .\CodexAutoResume-vX.Y.Z-win-x64.zip -Algorithm SHA256).Hash
   $hash -eq ((Get-Content .\CodexAutoResume-vX.Y.Z-win-x64.zip.sha256 -Raw) -split '\s+')[0]
   ```

   릴리스 페이지에도 각 asset 옆에 SHA-256 다이제스트가 표시됩니다. GitHub가 저장하고 있는 파일에서
   계산한 값이며, 같은 값이어야 합니다.

3. **`main`에 고정된 그 버전의 다이제스트와 비교합니다.**
   [main 브랜치의 `scripts/release.json`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/scripts/release.json)을
   열고, `sha256` 표에서 앞의 `v`를 뺀 버전 번호를 찾습니다. 그다음:

   ```powershell
   $hash -eq '<X.Y.Z에 적힌 값>'
   ```

   반드시 `main`에서 읽으세요. 압축 파일에는 `release.json` 자체가 들어 있으므로 자기 다이제스트를
   담을 수 없습니다. 고정값은 릴리스가 게시된 뒤에 커밋되므로, 그보다 먼저 커밋된 태그 시점의 사본에도
   그 버전의 다이제스트가 없습니다(있더라도 `null` 자리표시자이고, bootstrap은 이것을 항목이 없는 것으로
   봅니다). v0.5.0과 v0.5.1은 항목이 아예 없습니다. 이 단계들 뒤의 설명을 보세요.

4. **[GitHub CLI](https://cli.github.com/)가 있다면 빌드 provenance를 확인합니다.**

   ```powershell
   gh attestation verify .\CodexAutoResume-vX.Y.Z-win-x64.zip `
       --repo songyb111-gachon/codex-auto-resume-windows `
       --signer-workflow songyb111-gachon/codex-auto-resume-windows/.github/workflows/release.yml `
       --source-ref refs/tags/vX.Y.Z
   ```

   정확히 이 파일의 다이제스트에 대한 attestation이 있고, 그것이 이 저장소에서 태그 `vX.Y.Z`에 대한
   `.github/workflows/release.yml` 실행이 서명한 것일 때에만 성공합니다. `--signer-workflow`와
   `--source-ref`가 없으면 이 명령은 저장소 안의 어떤 워크플로 실행에서, 어떤 브랜치나 태그에 대해
   만들어진 attestation이든 받아들입니다. v0.5.4 이후의 모든 압축 파일에는 attestation이 있습니다.

   attestation에는 커밋도 하나 적혀 있습니다. 태그 push로 게시된 압축 파일이라면 그것이 실제로 빌드된 커밋입니다. v0.5.0부터 여덟 개 릴리스의 압축
   파일을 모두 빌드한 예전의 단일 작업 워크플로는 수동 실행으로도 게시할 수 있었습니다. 그 워크플로 가운데 attestation을 기록하는
   버전(v0.5.4부터)에서는, 그 버전에 아직 asset이 없을 때 태그에 대해 시작한 실행이 `plugin.json`에 그 태그의 버전이 적힌 ref라면 어느
   것이든 빌드해 게시하고 attestation을 기록할 수 있었습니다. 어떤 이벤트가 그 실행을 시작했는지는 attestation에 기록됩니다. 태그 push일 때만
   게시하는 워크플로는 main 브랜치에 있으며, 그 여덟 개 릴리스 이번 릴리스에 들어 있습니다.

직접 한 확인이 모두 일치할 때에만 압축을 풀고 `Install.cmd`를 실행하세요. 하나라도 어긋나면 풀지
마세요. 파일을 지우고, 버전과 얻은 값을 적어 이슈를 열어 주세요.

v0.5.0과 v0.5.1은 `sha256` 고정 표보다 먼저 나왔으므로 항목이 없습니다. 이 두 버전에는 `.sha256`과
릴리스 페이지의 다이제스트만 적용됩니다(attestation도 없습니다). 그 밖에 릴리스 페이지에는 있지만
표에 없는 버전은 최근에 게시되어 고정 커밋이 아직 들어오지 않은 것입니다. 그 커밋을 기다리거나, `.sha256`과 attestation이
각각 무엇을 증명하고 무엇을 증명하지 못하는지 알고서 그 둘에 기댈 수 있습니다.

GitHub CLI가 없다면 같은 증명을 `sigstore-python`으로 확인할 수 있고, 여기서 쓴 것도 그것입니다.
쓰고 버릴 가상 환경에 설치한 뒤, 직접 잰 해시에 대한 번들을 받아 검증하면 됩니다.

```powershell
py -3 -m venv .\sigstore-venv
.\sigstore-venv\Scripts\python.exe -m pip install sigstore
$digest = (Get-FileHash .\CodexAutoResume-vX.Y.Z-win-x64.zip -Algorithm SHA256).Hash.ToLower()
$url = "https://api.github.com/repos/songyb111-gachon/codex-auto-resume-windows/attestations/sha256:$digest"
(Invoke-WebRequest $url -UseBasicParsing).Content |
    ConvertFrom-Json | ForEach-Object { $_.attestations[0].bundle } |
    ConvertTo-Json -Depth 40 | Set-Content bundle.sigstore.json -Encoding utf8
.\sigstore-venv\Scripts\python.exe -m sigstore verify identity `
    --bundle bundle.sigstore.json `
    --cert-identity "https://github.com/songyb111-gachon/codex-auto-resume-windows/.github/workflows/release.yml@refs/tags/vX.Y.Z" `
    --cert-oidc-issuer "https://token.actions.githubusercontent.com" `
    .\CodexAutoResume-vX.Y.Z-win-x64.zip
```

`gh attestation verify`가 묻는 것과 같은 질문을 다른 길로 묻습니다. 수명이 짧은 Fulcio 인증서로
만든 서명, 그 인증서가 Sigstore 뿌리까지 이어지는 사슬, 거기 박힌 인증서 투명성 타임스탬프,
그리고 Rekor 투명성 로그의 항목입니다. 이번 릴리스에서는 넷 다 통과했고,
[`docs/evidence/attestation-verified-2026-09-13.json`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/evidence/attestation-verified-2026-09-13.json)이
그 실행을 기록하고 있습니다. 인증서가 담고 있던 신원, 검사가 헛돌지 않음을 보이려고 쓴 변조 대조
아홉 가지, 그리고 그래도 알려 주지 않는 세 가지가 적혀 있습니다. Sigstore 뿌리는 처음 쓸 때
그대로 믿는다는 것, 번들에 별도의 타임스탬프 기관이 없다는 것, 그리고 증명이 말하는 것은 어떤
워크플로가 이 바이트를 만들었다는 것이지 그 워크플로가 자기가 말하는 것을 만든다는 것은 아니라는
것입니다.

| 확인 | 알 수 있는 것 | 알 수 없는 것 |
| --- | --- | --- |
| 압축 파일 옆의 `.sha256` | 다운로드가 온전하다는 것. GitHub가 제공하는 바로 그 파일을 받았습니다. | 누가 그것을 올렸는지. 압축 파일과 같은 곳에서 오므로, 바뀐 압축 파일은 그에 맞게 바뀐 `.sha256`과 함께 올 수 있습니다. |
| 릴리스 페이지의 다이제스트 | 같은 것. 다만 워크플로가 아니라 GitHub가 계산한 값입니다. | 같습니다. |
| `main`의 `release.json`에 고정된 다이제스트 | 게시 후 관리자가 기록한 바로 그 파일이라는 것. 릴리스 파일이 아니라 저장소 이력 속의 커밋이라는 별도의 경로로 기록됩니다. 바꾸려면 `main`에 커밋이 하나 더 필요하고, 쓰기 권한이 있는 누군가가 force-push로 이력을 다시 쓰지 않는 한 그 커밋은 이력에 보입니다. 브랜치가 그런 일로부터 보호되어 있는지는 확인되지 않았습니다. | 그 파일이 태그된 소스에서 빌드되었다는 것. 관리자는 게시된 파일에서 다이제스트를 가져왔습니다. |
| 4단계의 옵션을 붙인 `gh attestation verify` | 이 저장소에서 그 태그에 대해 실행된 릴리스 워크플로가 그 파일을 빌드했다는 것. 태그 push로 게시된 압축 파일이라면 attestation에 적힌 커밋에서 빌드되었습니다. 예전의 단일 작업 워크플로는 태그에 대해 수동으로 실행해, `plugin.json`에 그 버전이 적힌 다른 ref를 빌드한 경우에도 게시할 수 있었고, 어떤 이벤트가 그 실행을 시작했는지는 attestation에 기록됩니다. | 그 커밋에 원하는 내용이 들어 있는지. |
| 직접 다시 빌드하기 | 태그에 `build/normalize_pe.py`가 들어 있는 릴리스라면, 그 바이트가 태그된 소스에서 나온다는 것. | v0.5.0부터 여덟 개 릴리스에는 어느 것에도 쓸 수 없습니다. 그 태그 중 어디에도 그 파일이 없기 때문입니다. 아래의 [한계](#다시-빌드해서-지금-알-수-있는-것과-없는-것)를 보세요. |

## 플러그인 경로가 대신 확인하는 것

Codex에서 설치하면 플러그인의 `scripts/bootstrap.ps1`이, 압축 파일 안의 무엇이든 실행하기 전에 스스로
다음을 확인합니다.

- URL 형태 하나로만 내려받습니다. `scripts/release.json`의 상수와 플러그인 자신의 매니페스트에 적힌
  버전으로 만듭니다. "latest"는 없고, 사용자가 입력한 어떤 것도 URL의 일부가 되지 않습니다.
- TLS 1.2 이상의 HTTPS를 쓰고, 리디렉션을 거친 최종 호스트가 `github.com`,
  `objects.githubusercontent.com`, `release-assets.githubusercontent.com` 중 하나가 아니면 다운로드를
  거부합니다.
- 압축 파일의 SHA-256을 플러그인이 가진 `scripts/release.json` 사본에 고정된 다이제스트와 비교합니다.
  GitHub 마켓플레이스에서 추가한 플러그인은 Codex가 그것을 마지막으로 가져왔을 때 `main`에 있던
  고정값을 갖습니다. 고정 커밋이 들어오기 전에 추가했다면 `.sha256`으로 대신 확인하고, 그렇다고
  알립니다. 설치는 어느 경로로 하든 보통 설치된 사본에서 플러그인을 다시 등록하는데, 그 사본의
  `release.json`은 압축 파일에서 나온 것이라 자기 버전의 다이제스트를 담을 수 없습니다. 그 사본을 통해
  나중에 `-Force`나 `-ArchivePath`로 실행하면 `.sha256`으로 대신 확인하거나 아무것과도 대조하지 않고,
  그렇다고 알립니다.
- 모든 릴리스에 반드시 들어 있어야 하는 파일(인터프리터, MCP 서버와 그 런처 및 `.mcp.json`, 설정 창,
  플러그인 매니페스트, 설정 스크립트, 설치 프로그램)이 있는지, 페이로드 루트에 설정 창과 그 아이콘만
  있고 다른 것은 없는지(설치 프로그램이 그 루트를 설치 홈으로 복사하기 때문입니다), 안에 든
  매니페스트가 이 제품의 이 버전을 가리키는지, 풀 때 폴더 바깥으로 빠져나가는 항목이 없는지
  확인합니다.
- 어느 단계에서든 실패하면 멈추고, 스크립트는 그다음 내려받은 파일의 작업 사본을 지웁니다.

attestation은 확인하지 않습니다. 이미 설치된 버전과 같으면 `-Force`를 주지 않는 한 아무것도 내려받지
않고 설정만 다시 실행합니다.

압축 파일을 직접 내려받았고 플러그인도 있다면, 같은 스크립트에 `-ArchivePath`로 그 파일을 건넬 수
있습니다. 그 버전에 고정된 다이제스트가 있으면 그것과 대조합니다. 설치가 등록한 플러그인 사본에서는
설치된 버전에 고정값이 없습니다(위 참고). 고정값이 없으면 로컬 파일에는 가져올 게시 체크섬이
없으므로, 스크립트는 SHA-256을 아무것과도 대조하지 않았다고 출력하고 내용 검사만 적용됩니다.
이미 설치된 버전과 같으면 `-Force`도 함께 주지 않는 한 스크립트는 그 파일을 전혀 쓰지 않고 설정만 다시
실행합니다. 스크립트에 대한 자세한 내용은 [docs/PLUGIN.ko.md](PLUGIN.ko.md)에 있습니다.

## 릴리스를 직접 다시 빌드하기

다시 빌드하기는 게시된 압축 파일을 그 태그의 소스가 만들어 내는 것과 비교합니다. 일치할 수 있는 것은 태그에 `build/normalize_pe.py`가 들어 있는
릴리스뿐이고, v0.5.0부터 여덟 개 릴리스 중에는 그런 것이 없습니다. 재현 가능한 빌드 - `build/normalize_pe.py`, CRLF 체크아웃, 릴리스
워크플로의 두 번째 빌드 - 는 main 브랜치에 있으며, 그 여덟 개 릴리스 이번 릴리스에 들어 있습니다. 지금까지 게시된 모든 압축 파일, 곧 v0.5.0부터 여덟 개
릴리스의 압축 파일은 예전의 단일 작업(job) 릴리스 워크플로가 빌드했습니다. 그 워크플로는 action을 고정된 커밋이 아니라 움직이는 태그로 참조했고, 그 실행
파일에는 어떤 재빌드로도 재현되지 않는 빌드 시각과 무작위 GUID가 찍혀 있습니다. 그런 릴리스에는 위의 다이제스트 확인이 적용되고, attestation 확인은
v0.5.4부터 적용됩니다(v0.5.0과 v0.5.1에는 고정된 다이제스트가 없습니다).

태그에 `build/normalize_pe.py`가 있는 릴리스라면 다음이 필요합니다.

- .NET Framework 4.8이 있는 Windows 10 또는 11. 빌드는 그 C# 컴파일러를 씁니다. Windows 11과 Windows
  10 버전 1903 이상에는 들어 있습니다. LTSC 2019 같은 그보다 오래된 Windows 10 빌드에는 4.7.2가 들어
  있으므로, 다이제스트를 비교하려면 먼저 4.8을 설치하세요.
- Git.
- `PATH`에 있는 Python. 빌드는 Python 3.12 이상에서 되지만, 다이제스트를 비교하려면 릴리스
  워크플로가 쓰는 계열인 Python 3.13을 쓰세요. 압축 파일은 `build/make_release.py`를 실행하는
  Python의 `zipfile`과 `zlib` 모듈이 쓰는데, Windows에서 Python 3.14 이상은 다른 zlib 구현(zlib-ng)을
  쓰므로, 더 새로운 Python은 똑같은 파일들로 다른 압축 파일을 만들 수 있습니다.
  `python -c "import zlib; print(zlib.ZLIB_RUNTIME_VERSION)"`는 사용 중인 Python의 zlib를 출력합니다.
  지금까지 비교한 빌드는 모두 zlib 1.3.1을 썼습니다. 워크플로는 3.13의 패치 릴리스를 고정하지 않으며,
  실제로 설치한 버전은 실행 로그에 적힙니다.

관리자 권한은 필요하지 않습니다. 빌드는 함께 넣을 embeddable Python을 python.org에서 내려받고, 그
SHA-256이 `build/make_release.py`에 적힌 값과 다르면 거부합니다.

새로 clone해서 시작하세요. 압축 파일에는 소스 파일이 들어가므로 그 줄 끝도 압축 파일 바이트의
일부이고, 기존 작업 트리는 다른 설정으로 체크아웃되었을 수 있습니다([아래](#빌드를-재현-가능하게-만드는-방법) 참고).

```powershell
git clone --branch vX.Y.Z --depth 1 https://github.com/songyb111-gachon/codex-auto-resume-windows.git
cd codex-auto-resume-windows
git rev-parse HEAD
powershell -ExecutionPolicy Bypass -File build/make_gui.ps1
python build/make_release.py
Get-Content .\build\dist\CodexAutoResume-vX.Y.Z-win-x64.zip.sha256
```

`git rev-parse HEAD`는 빌드한 커밋을 출력하며, attestation에 적힌 커밋과 같아야 합니다. 마지막 줄은
게시된 `.sha256`, 그리고 `main`에 고정된 다이제스트와 같아야 합니다. 같다면 게시된 압축 파일은 정확히
그 소스가 만들어 내는 것입니다.

`build/make_gui.ps1`은 사용한 컴파일러(버전이 적힌 `compiler` 줄)와 빌드한 각 실행 파일의 SHA-256을 출력합니다. 저장소 Actions
탭에 있는 릴리스 실행 로그에도 GitHub가 그 실행의 로그를 보관하는 동안에는 같은 줄이 있습니다. 보관 기간은 저장소의 보존 기간(따로 정하지 않았다면 90일)이고,
GitHub는 그 로그를 로그인한 사용자에게만 보여 줍니다. 그 로그에서는 실행 파일을 두 번째로 빌드하는 단계가 각각의 다이제스트를 다시 출력합니다. 이것들을 비교하면
차이가 컴파일된 두 프로그램에 있는지, 다른 곳에 있는지 알 수 있습니다. 이 줄들과 두 번째 빌드는 main 브랜치에 있으며, v0.5.0부터 여덟 개 릴리스 이번
릴리스에 들어 있습니다. 그 여덟 개 릴리스를 빌드한 실행은 각 실행 파일의 크기만 출력하고, `compiler` 줄도 실행 파일 다이제스트도 없습니다.

### 빌드를 재현 가능하게 만드는 방법

아래 내용은 main 브랜치에 있으며, v0.5.0부터 여덟 개 릴리스 이번 릴리스에 들어 있습니다.

- Windows에 기본 포함된 C# 컴파일러에는 `/deterministic` 스위치가 없습니다. 같은 소스를 두 번 빌드하면,
  측정한 바로는 정확히 두 필드가 다릅니다. PE 헤더의 타임스탬프와, 모듈에 무작위로 찍히는 버전 GUID(MVID)입니다.
  `build/normalize_pe.py`가 타임스탬프를 상수로, GUID를 모듈 자신의 내용에서 얻은 값으로 바꿉니다.
  구조 검사를 통과하지 못한 파일, 예를 들어 디버그 디렉터리나 PE 체크섬이 있는 파일은 거부합니다.
- `build/make_release.py`는 파일 순서, 항목 타임스탬프, 압축 수준을 고정해 압축 파일을 쓰고, 빌드한
  기기의 경로를 하나도 넣지 않습니다. 그래도 압축된 바이트는 그것을 실행하는 Python의 zlib에서
  나옵니다.
- `.gitattributes`가 기기의 Git 설정과 상관없이 모든 텍스트 파일을 CRLF로 체크아웃하므로, 압축 파일에
  들어가는 소스 파일의 줄 끝은 새로 한 체크아웃이라면 어디서나 같습니다. 저장소 자체에는 LF로
  저장됩니다.
- 릴리스 워크플로는 실행 파일을 두 번 빌드하고, 두 빌드가 다르면 더 진행하지 않습니다.

### 다시 빌드해서 지금 알 수 있는 것과 없는 것

한 커밋을 새로 clone한 사본 두 개에서, 같은 기기와 같은 컴파일러, 같은 Python으로 빌드했더니 실행
파일을 포함해 바이트 하나까지 똑같은 압축 파일이 나왔습니다. 이번 릴리스부터는 두 번째 결과가, 그것도
더 강한 결과가 있습니다. GitHub의 runner가 발행한 압축 파일과, 다른 Windows 기기에서 그 태그를 새로
clone해 다시 빌드한 압축 파일의 SHA-256이 같았습니다. 안에 든 파일들만이 아니라 ZIP 전체가 같았습니다.

이것은 두 기기에 걸친 한 번의 측정이고, 두 기기가 같은 도구 사슬을 썼다는 뜻은 아닙니다. runner의
컴파일러 빌드는 릴리스 실행 로그에만 찍히고 그 로그는 저장소에 접근할 수 있는 계정이라야 읽을 수
있으므로, 같은 도구 사슬끼리의 일치였는지 다른 도구 사슬끼리의 일치였는지는 **확인되지 않았습니다**.
확인된 것은 이 두 빌드가 일치했다는 것입니다. 결과는 여전히 Windows에 기본 포함된 컴파일러의 빌드에
달려 있고, 그것은 Windows 설치마다 다를 수 있습니다. 압축 파일을 쓰는 Python에도 달려 있습니다.

그래서 일치하면 강한 증거입니다. 일치하지 않으면 더 살펴볼 이유이지, 변조의 증거는 아닙니다.

- **재현 가능한 빌드 이전의 태그.** v0.5.0부터 여덟 개 릴리스가 모두 여기에 해당합니다. 태그의 소스에
  `build/normalize_pe.py`가 없다면 그 실행 파일에는 빌드 시각과 무작위 GUID가 찍혀 있으므로, 다시
  빌드해도 일치하지 않습니다.
- **다른 컴파일러 빌드.** 직접 빌드할 때 출력된 `compiler` 줄을, 로그가 보관되어 있는 동안 릴리스
  실행 로그의 것과 비교하세요.
- **다른 Python이나 zlib 빌드.** 두 압축 파일 안의 파일이 모두 같은데(아래 비교가 아무것도 출력하지
  않는데) 압축 파일의 다이제스트가 다르다면, 차이는 압축 파일을 쓰는 방식에 있고 압축기를 가리킵니다.
  Python 3.13으로 빌드했는지, 그 Python이 어떤 zlib를 출력하는지 확인하세요.
- **어떤 파일이 다른지.** 아래 코드는 두 압축 파일을 풀지 않은 채 안의 파일들을 비교합니다. clone한
  폴더에서, `$published`를 내려받은 파일을 저장한 위치로 바꿔 실행하세요. 모든 파일이 같으면 아무것도
  출력하지 않고, 그렇지 않으면 다른 파일을 어느 쪽에서 왔는지와 함께 나열합니다. 내용이 다른 파일은
  양쪽 압축 파일에서 한 번씩 나오고, 한쪽 압축 파일에만 있는 파일은 한 번 나옵니다.

  ```powershell
  function Get-ZipDigests([string]$Zip) {
      Add-Type -AssemblyName System.IO.Compression.FileSystem
      $archive = [IO.Compression.ZipFile]::OpenRead((Resolve-Path $Zip))
      try {
          foreach ($entry in $archive.Entries) {
              $stream = $entry.Open()
              try { $digest = (Get-FileHash -InputStream $stream -Algorithm SHA256).Hash }
              finally { $stream.Dispose() }
              [pscustomobject]@{ Name = $entry.FullName; SHA256 = $digest }
          }
      } finally { $archive.Dispose() }
  }
  $published = "$HOME\Downloads\CodexAutoResume-vX.Y.Z-win-x64.zip"   # 내려받은 파일을 저장한 곳
  Compare-Object (Get-ZipDigests $published) `
                 (Get-ZipDigests .\build\dist\CodexAutoResume-vX.Y.Z-win-x64.zip) -Property Name, SHA256
  ```

  재현 가능하게 빌드된 태그라면 압축 파일 안의 Python, PowerShell, 배치 파일은 체크아웃한 소스에서
  그대로 복사된 것이므로, 그중 하나라도 다르다면 이슈로 알려 주실 만합니다.

## 코드 서명

이 프로젝트가 빌드하는 것에는 Authenticode 서명이 없습니다. 두 실행 파일도, `Install.cmd`와
`Uninstall.cmd`도, PowerShell 스크립트도 서명되어 있지 않습니다. 함께
들어 있는 Python 인터프리터 - python.org embeddable 런타임의 `pythonw.exe`, `python.exe`와 그 DLL -
는 배포될 때의 서명을 그대로 가지고 있습니다. Python Software Foundation의 서명이고, Visual C++ 런타임
DLL 두 개(`vcruntime140.dll`과 `vcruntime140_1.dll`)에는 Microsoft의 서명입니다.

- **로그인할 때 시작되는 프로세스는 서명된 인터프리터입니다.** 릴리스 압축 파일로 설치했고 로그인 시
  시작이 켜져 있다면, Windows는 함께 들어 있는 `pythonw.exe`를 시작합니다. 그 인터프리터가 실행하는
  Python 코드는 이 프로젝트의 것이고 서명되어 있지 않습니다.
- **서명되지 않은 것:** 설정 창 `CodexAutoResumeSettings.exe`, Codex가 플러그인의 도구와 패널을 위해
  시작하는 MCP 런처 `codex-auto-resume-mcp.exe`, `Install.cmd`와 `Uninstall.cmd`, 그리고 이 프로젝트의
  스크립트들입니다. `.cmd` 파일은 애초에 Authenticode 서명을 담을 수 없습니다.
- main 브랜치에서는 두 실행 파일에 버전 리소스가 있어서 **Properties → Details**(한국어 Windows에서는
  속성 → 자세히)에 제품 이름, 버전, 그리고 작성자 이름이 적힌 저작권 줄이 보입니다. 이것은 v0.5.0부터
  여덟 개 릴리스 이번 릴리스에 들어 있습니다. 그 여덟 개 릴리스의 실행 파일은 그 제품 정보 없이
  빌드되었습니다. 이것은 파일 안의 텍스트일 뿐 서명이 아닙니다. 누구나 쓸 수 있고,
  Windows의 보안 알림은 여전히 게시자를 알 수 없다고 표시합니다.

그 때문에 보게 될 수 있는 것은 이렇습니다.

- **SmartScreen, 수동 경로에서.** 내려받은 ZIP을 탐색기로 풀면 다운로드에 붙은 웹 표시(mark of the
  web)가 풀려 나온 파일에도 옮겨지므로, `Install.cmd`를 실행할 때 게시자를 알 수 없다는
  *Windows protected your PC* 창(한국어 Windows에서는 "Windows의 PC 보호")이 뜰 수 있습니다. 이 경고는
  파일이 서명되지 않았고 널리 보이는 파일이 아니라는 뜻이지, 어떤 검사에 실패했다는 뜻이 아닙니다. 그것이
  게시된 파일임을 알려 주는 것은 위의 다이제스트 확인입니다.
- **스마트 앱 컨트롤(Smart App Control).** 켜져 있는 PC에서는 서명되지 않은 프로그램과 스크립트를
  차단할 수 있고, 파일 하나만 예외로 두는 방법은 없습니다. 워처의 프로세스는 서명된 인터프리터입니다.
  차단은 그 대상이 된 것에 적용됩니다 - 예를 들어 설정 창, 플러그인의 도구와 패널, `Install.cmd`,
  설치 프로그램의 PowerShell 스크립트, 또는 시작 메뉴 바로 가기를 만들려고 설정 과정이 PowerShell로
  컴파일하는 C# 코드. 이 목록을 스마트 앱 컨트롤로 시험해 보지는 않았습니다. 이 프로젝트는 스마트 앱
  컨트롤을 끄라고 요청하지 않습니다.

둘 중 하나에 막혔다면 파일 이름과 메시지를 적어 이슈를 열어 주세요.

## 확인되지 않은 것

- **릴리스는 GitHub의 immutable release가 아닙니다.** GitHub는 v0.5.0부터 여덟 개 릴리스를 모두
  immutable이 아니라고 표시합니다. immutable release는 게시된 릴리스의 파일을 바꾸거나 태그를 옮기는
  것을 GitHub 자체가 거부하게 하는 저장소 설정입니다. 릴리스 워크플로는 v0.5.4부터 이미 asset이 있는
  버전 위에 다시 게시하는 것을 거부합니다. 그 워크플로의 v0.5.2와 v0.5.3 버전은 반대였습니다. 태그를
  지정한 수동 실행이 그 태그를 다시 빌드해 릴리스의 asset을 교체했고(`--clobber`), 그 워크플로 사본은
  지금도 그 태그에 남아 있습니다. 어느 쪽이든 그것은 워크플로의 규칙일 뿐 저장소에 쓰기 권한이 있는
  모든 사람을 막지는 않습니다. 그런 사람은 asset을 손으로 바꾸거나, 그 예전 사본 중 하나를 그것을 담은
  브랜치에서 실행할 수 있습니다(자기 태그에서 수동 실행하면, 이미 있는 릴리스를 만들려고 할 때 멈춥니다). 바뀐 압축 파일을 드러내 주는 것은 `main`에 고정된 다이제스트, 그리고 4단계처럼 릴리스
  워크플로와 태그를 지정해 확인한 attestation이고, 위의 절차가 둘 다 쓰는 이유가 그것입니다.
- **게시된 압축 파일은 예전 릴리스 워크플로에서 나왔습니다.** 지금까지 게시된 모든 압축 파일, 곧
  v0.5.0부터 여덟 개 릴리스의 압축 파일은 action을 고정된 커밋이 아니라 움직이는 태그로 참조하는 단일
  작업(job)이 빌드했고, 그 실행 파일은 재현할 수 없습니다. 빌드 작업과 게시 작업으로 나눈 구조, 전체
  커밋 SHA로 고정한 action, Dependabot은 main 브랜치에 있으며, 그 여덟 개 릴리스 이번 릴리스에 들어 있습니다.
- **태그는 서명되어 있지 않습니다.** `vX.Y.Z`를 clone한다는 것은 그 태그가 여전히 원래 자리를
  가리킨다고 믿는다는 뜻입니다. 태그 push로 게시된 압축 파일이라면 attestation은 실제로 빌드된 커밋을
  기록하고, 다시 빌드할 때 `git rev-parse HEAD`를 출력하는 이유가 그것입니다. v0.5.0부터 여덟 개
  릴리스의 압축 파일을 모두 빌드한 예전의 단일 작업 워크플로는, 태그에 대해 수동으로 실행해
  `plugin.json`에 그 버전이 적힌 다른 ref를 빌드한 경우에도 게시할 수 있었습니다. 어떤 이벤트가 그
  실행을 시작했는지는 attestation에 기록됩니다.
- **새 릴리스에는 한동안 고정값이 없습니다.** 고정값은 게시된 뒤에 커밋됩니다. 그 전까지, 그리고 그
  전에 가져온 플러그인 사본에서는, 플러그인 경로가 게시된 `.sha256`으로 대신 확인하고 그렇다고
  알립니다. 설치가 등록한 플러그인 사본은 압축 파일의 `release.json`을 가지고 있고, 그것은 자기 버전의
  다이제스트를 담을 수 없습니다. 그래서 `main`에 고정값이 생긴 뒤에도, 그 사본을 통한 `-Force` 실행은
  `.sha256`으로 대신 확인하고 `-ArchivePath` 실행은 아무것과도 대조하지 않으며, 각각 그렇다고 알립니다.
- **기기 사이의 재현성.** 위에 적은 대로이며, v0.5.0부터 여덟 개 릴리스는 어느 것도 게시된 바이트
  그대로 다시 빌드할 수 없습니다.
- **`Install.cmd`는 압축 파일을 확인하지 않고**, **플러그인 경로는 attestation을 확인하지 않습니다.**
- **v0.5.4보다 앞선 압축 파일에는 attestation이 없습니다.**
- **제안된 액션 업그레이드 넷을 이번 릴리스 뒤로 일부러 미뤘다.** Dependabot이 `actions/checkout`을
  v7.0.1로, `actions/setup-python`을 v7.0.0으로, `actions/attest-build-provenance`를
  v4.2.2로, 산출물 한 쌍을 `upload-artifact` v7.0.1과 `download-artifact` v8.0.1로 올리는 풀
  리퀘스트를 열어 두었다. 넷 다 전체 커밋 고정과 버전 주석을 지키며, 어느 것도 공개된 보안
  수정이 아니다.

  이번 릴리스는 빌드와 발행을 나눈 워크플로가 처음으로 만드는 릴리스다. 산출물 한 쌍은 권한 없는
  빌드 작업에서 권한 있는 발행 작업으로 보관 파일을 나르는 것이고, 증명 액션은 발행 작업이
  서명하는 것이다. 그 경로를 처음 실제로 쓰는 순간에 둘 중 하나를 바꾸면, 실패했을 때 그것이
  어느 변경 탓인지 가릴 수 없게 된다. 유일하게 실제로 밀어붙이는 것은 `checkout`과
  `setup-python`이 선언한 Node 20이 폐기되어 GitHub가 Node 24로 강제 실행하며 매번 경고한다는
  점인데, 그래도 돌아가고 있고 이 릴리스가 거기에 기대는 것은 없다.

  이번 릴리스를 발행하고 확인한 뒤에 하나씩 넣는다. 그 폐기 때문에 `checkout`과 `setup-python`이
  먼저고, 그다음 산출물 한 쌍을 함께(한쪽만은 결코 안 된다), 그다음 증명이며, 각각 다음 태그
  전에 `workflow_dispatch` 예행으로 확인한다.

검증은 그 파일이 이 프로젝트가 게시한 파일이라는 것을 알려 줍니다. 코드가 안전하다는 것까지 알려
주지는 않습니다. 코드가 무엇을 할 수 있고 그것이 어떻게 강제되는지는
[SECURITY.ko.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/SECURITY.ko.md)를
보세요.
