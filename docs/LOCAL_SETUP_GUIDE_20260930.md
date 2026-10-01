# CleverSearch · CLEVERCHAT 로컬 사용 안내

작성일: 2026-09-30. 이 장치의 기존 소스를 직접 설정했다. 기존 Git 미커밋 변경과 기존 DB/컨테이너는 보존했다.

## 1. VS Code 작업영역

`D:\00.WORK\AI\프로젝트_설정_작업\CleverProjects.code-workspace`를 VS Code로 연다.

세 폴더가 함께 보인다: CleverSearch / CLEVERCHAT / 작업기록. CLEVERCHAT의 앱 루트는 저장소 아래 `3.개발\cleverchat`이다. Java 확장팩과 기존 Python 확장을 사용할 수 있다.

| 서비스 | 주소 | 로컬 DB/검색 |
|---|---|---|
| CleverSearch 검색 | http://127.0.0.1:8000/ | PostgreSQL 15432, OpenSearch 19200 |
| CleverSearch 관리자 | http://127.0.0.1:8000/admin | 문서 5개 색인 완료 |
| CLEVERCHAT 상담 | http://127.0.0.1:8080/chat | PostgreSQL 15433 |
| CLEVERCHAT 관리자 | http://127.0.0.1:8080/admin | 로컬 검증용 활성 시나리오 제공 |

외부에 공개하지 않는 localhost 개발 환경이다. CleverSearch는 기존 기본 실행기가 원격 환경을 선택하므로, 아래 workstation 실행기를 사용한다.

## 2. 실행과 중지

Docker Desktop의 Linux 엔진이 실행되어 있어야 한다.

VS Code 명령 팔레트에서 **Tasks: Run Task**를 선택한다.

- `Search: start`: DB/검색 엔진 준비 후 Python 서버 실행.
- `Chat: start`: DB 준비, Maven 빌드, Flyway 검사 후 Java 서버 실행.
- 현재 백그라운드 서버가 이미 실행 중이면 먼저 아래 중지 스크립트를 실행한다. VS Code 작업으로 시작한 서버는 해당 작업 터미널의 Ctrl+C로 중지한다.

이번 설정 작업에서 실행한 백그라운드 서버만 중지:

```powershell
pwsh -NoProfile -File 'D:\00.WORK\AI\프로젝트_설정_작업\서버중지.ps1'
```

직접 실행하려면 각각 별도 터미널에서:

```powershell
pwsh -NoProfile -File 'C:\02.Project\01.파이썬\01.WorkSpace\CleverSearch\scripts\start-workstation.ps1'
pwsh -NoProfile -File 'C:\02.Project\02.자바\01.WorkSpace\CLEVERCHAT\3.개발\cleverchat\tools\start-workstation.ps1'
```

DB 컨테이너는 앱 종료 후에도 유지된다. 데이터가 들어 있는 Docker 볼륨을 삭제하지 않는다.

## 3. 로그인과 환경 파일

비밀번호·JWT·DB 비밀값은 Markdown에 적지 않았다. 로컬 파일을 VS Code에서 확인한다.

- Search: `.env.workstation-accounts.json`의 로컬 검증 계정. 애플리케이션 기본 시드 계정이며 이 localhost 환경에서 사용한다.
- Chat: 앱 루트 `.env.workstation.json`의 `adminUsername`/`adminPassword`. 최초 생성 계정은 `localadmin`이다.
- Search DB/검색/JWT: `.env.workstation`; 자동 테스트용: `.env.workstation-test`.
- Chat F5 환경: `.env.workstation-debug`.
- 위 환경/계정 파일은 Git 제외 대상이다. 로그/MD에는 비밀값을 복사하지 않는다.

Chat 상담 화면에서 **로컬 설치 확인 안내 → 실행 주소 보기 → 안내 종료**를 선택하면 동작을 확인할 수 있다. **로컬 검증 - 시작 노드 없는 초안**은 게시 차단을 확인하기 위한 비활성 데이터다.

## 4. 디버그와 자동 테스트

F5 실행 설정:

- `CleverSearch: Debug local (8001)` — http://127.0.0.1:8001
- `CLEVERCHAT: Debug local (8081)` — http://127.0.0.1:8081/chat

일반 실행 서버와 포트가 다르며 같은 로컬 데이터를 사용한다. DB 컨테이너는 먼저 실행되어 있어야 한다. Java 프로젝트 import가 끝난 뒤 F5를 누른다. F5 편집기 클릭 자체는 자동화하지 않았고, 설정 파일·JDK·빌드·서버 구동을 검증했다.

VS Code 테스트 작업:

- `Search: tests (isolated DB)` — 전용 `cleversearch_test` DB 사용. 기본 원격 DB에서 삭제형 테스트가 실행되지 않도록 guard 추가.
- `Chat: unit tests` — 일반 JUnit 테스트.
- `Chat: integration tests` — Testcontainers를 포함한 `-Pit test`. Docker 필요.

Java 17: `D:\00.WORK\AI\dev-tools\temurin17\jdk-17.0.20.1+1`. Windows 임시 소켓 경로 문제를 피하려고 명시적 `jdk.net.unixdomain.tmpdir`을 적용했다. 통합 테스트는 SUBST 경로가 아닌 실제 프로젝트 경로에서 실행한다.

실제 HTTP 재검증 스크립트는 작업기록 폴더의 `search_scenarios.py`, `chat_scenarios.py`다. Chat 스크립트는 로컬 검증 시나리오의 새 버전과 대화 이력을 추가한다.

## 5. 검증 결과와 수정 내용

| 검증 | 결과/증거 |
|---|---|
| CleverSearch pytest | 33/33 통과 (`search-tests-final.log`) |
| CleverSearch 실제 HTTP | 37/37 통과 (`CleverSearch_시나리오_결과.md`) |
| 검색 관리자 화면 | 18개 탭 렌더링, 가중치 저장·복원, 품질 평가 5/5 |
| CLEVERCHAT 기본 단위·통합 | 485건 중 479 통과, 외부 opt-in 6건 skip (`chat-tests-final.log`) |
| CLEVERCHAT 실제 HTTP | 57/57 통과 (`CLEVERCHAT_시나리오_결과.md`) |
| CLEVERCHAT 상담 화면 | 주제 선택, 답변/링크, 종료 확인 |
| 외부 사이트 테스트 | 별도 `외부크롤링_검증결과.md` 참고 |

주요 수정:

1. Search의 인덱스 이름 고정값을 환경 설정과 일치시킴. 기본 볼륨 삭제 보호에도 적용.
2. Search 스케줄러 시작 인자 불일치와 실제 반복 간격 처리 수정.
3. 한국어 OCR 모델 설치 및 로컬 tessdata 연결. 준비된 PDF/DOCX/PPTX/XLSX/JPG 검색 검증.
4. Search 다중 업로드에 개수·개별 크기·실제 총용량 사전 검증 적용. 제한 초과를 색인 전에 거부.
5. Search 미리보기의 `<mark>` 문자열 노출 수정. 기존 HTML escaping 유지.
6. Chat 관리자 PUT/PATCH/DELETE의 CSRF 검사 누락 수정. 토큰 누락·재사용 거부 회귀 검증.
7. Windows JDK/소켓/경로 문제 및 VS Code 실행·디버그 설정 정리.

전체 이슈와 변경 파일은 `작업일지_2026-09-30.md`, 실제 권한 처리 내역은 `승인내역_2026-09-30.md`, 수정 전 원본은 `source-backups`에 있다. 최초 dirty 상태는 `baseline`에 기록했다.

## 6. 프로젝트별 남은 사항

쉬운 설명은 `프로젝트별_남은사항_쉬운설명.md`를 참조한다. 프로젝트 안의 사본 이름은 `LOCAL_SETUP_REMAINING_EXPLAINED_20260930.md`다.

| 항목 | 대상 프로젝트 | 현재 상태와 필요한 작업 |
|---|---|---|
| 회사 운영 DB | 둘 다 | 이 PC의 DB는 정상 구성·검증. 실제 회사 운영 DB 대상 검증은 별도로 필요 |
| 회사 자료용 DB·SMB/SSH 공유 폴더 수집 | CleverSearch | 실제 운영 자료 저장소/접근 계정을 확정해 연결·수집 검증 필요 |
| 회사 통합 로그인(SSO) | CLEVERCHAT | 로컬 로그인 검증 완료. 실제 회사 로그인 시스템 연동은 미검증 |
| 생성형 AI 답변(LLM/vLLM) | CLEVERCHAT | 현재 상담·검색 답변은 동작. 실제 AI 서버 연결은 미구성·미검증 |
| 메일 알림 | CLEVERCHAT | 전송 코드 존재. 실제 메일 서버 연결 및 수신 확인은 미검증 |
| 대용량·장시간 시험 | 둘 다 | 기능 시험 통과. 운영 규모 부하/장시간 안정성은 미검증 |
| 웹 이미지 본문 OCR | CLEVERCHAT 크롤러 | 미지원. 이미지 글은 제목만 남을 수 있음. CleverSearch 업로드 이미지 OCR은 검증 완료 |
| 외부 공개 운영·인증·HTTPS | 둘 다 | 현재 localhost HTTP 개발 환경. 실제 서비스 주소/인증/HTTPS 별도 설정 필요 |

- '연결 정보가 없다'는 이전 표현을 '운영 대상을 확정해 실제 연결 검증을 하지 않았다'로 바로잡는다. Search에는 기존 원격 환경 설정이 있었고 이번에는 별도 로컬 환경을 사용했다.
- CleverSearch의 검색용 AI 모델은 실행·검증했다. 위 표의 미연결 생성형 AI는 CLEVERCHAT의 답변 생성 기능이다.
- Search는 이 로컬 환경에서만 관리자 MFA 필수 옵션을 해제했고 날짜 표시/통계는 기존 UTC 기준을 유지한다.
- 대규모/장시간 미검증은 현재 장애가 발견됐다는 뜻이 아니다. 이번에 실행한 시나리오 범위를 넘는 보증을 하지 않는다는 뜻이다.
- 사용자가 언급한 '동우 것'은 자료 경로가 확인되지 않아 비교하지 못했다.

## 7. 참고한 문서

- CleverSearch `README.md`, `docs/test_scenarios_20260320.md`, `docs/발표시나리오_강광민.md`, 2026-04-29 보안 조치 문서.
- CLEVERCHAT 루트/앱 README, `4.테스트/02.테스트시나리오/M2_시나리오테스트.md`, 기존 JUnit/통합 테스트와 실행 도구.
- [Temurin 공식 배포](https://adoptium.net/installation/archives), [VS Code Java 안내](https://code.visualstudio.com/docs/java/java-tutorial), [Tesseract 한국어 모델](https://github.com/tesseract-ocr/tessdata_fast), [Playwright 브라우저 설치](https://playwright.dev/java/docs/browsers).
