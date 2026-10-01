# CLEVERCHAT 외부 크롤링 검증

2026-09-30, 저장소의 opt-in 테스트를 실제 한전 공식 사이트에 실행했다. 애플리케이션 업무 DB에는 수집 결과를 적재하지 않았다.

## 최종 결과: 6개 항목 통과

| 항목 | 결과 | 증거 |
|---|---|---|
| 지정 게시판 1페이지/상세1건 | 통과 | chat-external-smoke.log 및 전체 실행 |
| 19개 게시판 레이아웃 인식 | 통과 | chat-external-full-initial.log |
| 중첩 게시판 및 알려진 빈 게시판 | 통과 | chat-external-full-initial.log |
| 전자공고 첫 페이지 누락 방지 | 통과 | chat-external-full-initial.log |
| 사규 AJAX 전체 페이지 수집 | 통과 | chat-external-counts-final.log: 18페이지,173건, 상세173건, 실패0, 잘림없음 |
| 공식 사이트맵의 정적 메뉴 파싱 | 통과 | chat-external-counts-final.log: 58개 메뉴, 파싱 실패0 |

기본 `-Pit test`에서는 외부 환경변수가 없어 6개를 skip했다. 이후 명시적으로 활성화한 전체 외부 실행에서 4개 통과/2개 실패했고, 원인 확인 후 실패한 2개를 재실행해 통과했다. 따라서 최종6개 통과는 이 실행들을 합친 결과이며 단일 로그의 숫자를 바꾼 것이 아니다.

## 발견 이슈와 조치

1. **크롤러 런타임 누락:** 프로젝트에 고정된 Playwright1.49용 Chromium131/Headless Shell 설치. 프로젝트 실행기와 F5/VS Code 터미널에 브라우저 경로 설정.
2. **이미지 글에 줄바꿈 강제:** 전자공고 첫 글은 텍스트 없는 이미지 본문이었다. 기존 제목 fallback을 정상으로 검증하도록 테스트를 수정했다. 내용 비어있지 않음, 제목, 상세URL, 실제 목록/상세수, 메뉴 문구 혼입 방지 검증은 유지했다.
3. **사규 고정 건수172:** 현재 공식 원문은173건이다. 실제 목록의 번호/페이지 크기에서 기대 건수와 페이지 수를 읽어 수집 결과와 비교한다.
4. **정적 메뉴 고정 건수57:** 현재 사이트맵은58개다. 핵심 메뉴 존재와 모든 발견 메뉴의 파싱 성공을 검사하도록 수정했다.

## 재실행

```powershell
pwsh -NoProfile -File 'D:\00.WORK\AI\프로젝트_설정_작업\13-browser-runtime.ps1' -AllBoards
```

외부 사이트의 자료량·구조가 바뀌면 결과도 달라질 수 있다. 테스트는 현재 게시물 전체/사이트맵을 실제 읽는다. Java 크롤러는 이미지 본문 OCR을 제공하지 않으므로 이미지 내용까지 추출됐다고 판정하지 않는다.

출처: [Playwright 공식 설치 안내](https://playwright.dev/java/docs/browsers), [한전 전자공고](https://www.kepco.co.kr/home/about/invest/announce/boardList.do), [사규 및 하위 규범](https://www.kepco.co.kr/home/disclosure/regulations/internalrule/boardList.do), [공식 사이트맵이 있는 홈](https://www.kepco.co.kr/home/index.do).
