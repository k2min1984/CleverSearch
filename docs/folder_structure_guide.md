# CleverSearch 폴더 구조 분리 가이드

> 작성일: 2026-03-25  
> 목적: 사용자(User) / 관리자(Admin) 소스 분리를 통한 유지보수성 향상

---

## 1. 현재 구조 (AS-IS)

프론트엔드와 백엔드 모두 한 폴더에 혼재되어 있어, 역할별 파일 구분이 어렵습니다.

```
static/
├── index.html          ← 사용자 검색 페이지
└── admin.html          ← 관리자 페이지

app/api/v1/
├── admin.py            ← 관리자 API
├── auth.py             ← 인증 API
├── file.py             ← 파일 업로드/삭제 API
├── index.py            ← 인덱스 조회 API
├── search.py           ← 검색 API
└── system.py           ← 시스템 설정 API
```

---

## 2. 분리 원칙

| 원칙 | 설명 |
|------|------|
| **역할 기준 폴더** | `user/`, `admin/`, `common/` 3개로 나눈다 |
| **URL 프리픽스 일치** | 폴더 경로와 URL 경로를 맞춰 파일 위치를 직관적으로 만든다 |
| **공통 로직 별도 관리** | 인증, 유틸 등 양쪽에서 쓰는 코드는 `common/`에 둔다 |

---

## 3. 목표 구조 (TO-BE)

### 3-1. 프론트엔드

```
static/
├── user/                        ← 사용자(일반) 페이지
│   ├── index.html
│   ├── css/
│   │   └── user.css
│   ├── js/
│   │   └── user.js
│   └── assets/
│       └── logo.png
│
├── admin/                       ← 관리자 페이지
│   ├── index.html
│   ├── css/
│   │   └── admin.css
│   ├── js/
│   │   └── admin.js
│   └── assets/
│       └── admin-logo.png
│
└── common/                      ← 공통 리소스 (양쪽 공유)
    ├── css/
    │   └── reset.css
    └── js/
        └── api-client.js
```

### 3-2. 백엔드 API 라우터

```
app/
├── api/
│   ├── user/                    ← 사용자용 엔드포인트
│   │   ├── __init__.py
│   │   ├── search.py            ← 검색 API
│   │   └── file.py              ← 파일 업로드/조회
│   │
│   ├── admin/                   ← 관리자용 엔드포인트
│   │   ├── __init__.py
│   │   ├── dashboard.py         ← 통계/대시보드
│   │   ├── system.py            ← 시스템 설정
│   │   ├── index.py             ← 인덱스 관리
│   │   └── user_mgmt.py         ← 사용자/권한 관리
│   │
│   └── common/                  ← 공통 (인증, 헬스체크)
│       ├── __init__.py
│       ├── auth.py              ← 로그인/토큰
│       └── health.py            ← 헬스체크
│
├── services/                    ← 비즈니스 로직 (기존 유지)
├── core/                        ← 설정/DB/OpenSearch (기존 유지)
├── schemas/                     ← DTO (기존 유지)
├── common/                      ← 유틸리티 (기존 유지)
└── main.py
```

---

## 4. URL 프리픽스 규칙

| 구분 | URL 패턴 | 예시 |
|------|----------|------|
| 사용자 API | `/api/v1/user/...` | `/api/v1/user/search` |
| 관리자 API | `/api/v1/admin/...` | `/api/v1/admin/dashboard` |
| 공통 API | `/api/v1/common/...` | `/api/v1/common/auth/login` |
| 프론트(사용자) | `/` 또는 `/user/` | `https://도메인/` |
| 프론트(관리자) | `/admin/` | `https://도메인/admin/` |

---

## 5. 현재 → 목표 매핑표

| 현재 파일 | 이동 후 위치 | 역할 구분 |
|-----------|-------------|----------|
| `static/index.html` | `static/user/index.html` | 사용자 |
| `static/admin.html` | `static/admin/index.html` | 관리자 |
| `app/api/v1/search.py` | `app/api/user/search.py` | 사용자 |
| `app/api/v1/file.py` | `app/api/user/file.py` | 사용자 |
| `app/api/v1/admin.py` | `app/api/admin/dashboard.py` | 관리자 |
| `app/api/v1/system.py` | `app/api/admin/system.py` | 관리자 |
| `app/api/v1/index.py` | `app/api/admin/index.py` | 관리자 |
| `app/api/v1/auth.py` | `app/api/common/auth.py` | 공통 |

---

## 6. main.py 라우터 등록 예시 (변경 후)

```python
from fastapi import FastAPI

app = FastAPI()

# 사용자 라우터
from app.api.user import search, file
app.include_router(search.router, prefix="/api/v1/user", tags=["User-Search"])
app.include_router(file.router,   prefix="/api/v1/user", tags=["User-File"])

# 관리자 라우터
from app.api.admin import dashboard, system, index
app.include_router(dashboard.router, prefix="/api/v1/admin", tags=["Admin-Dashboard"])
app.include_router(system.router,    prefix="/api/v1/admin", tags=["Admin-System"])
app.include_router(index.router,     prefix="/api/v1/admin", tags=["Admin-Index"])

# 공통 라우터
from app.api.common import auth, health
app.include_router(auth.router,   prefix="/api/v1/common", tags=["Common-Auth"])
app.include_router(health.router, prefix="/api/v1/common", tags=["Common-Health"])
```

---

## 7. 주의사항

- `services/`, `core/`, `schemas/`, `common/` 등 **비즈니스 로직 계층은 분리하지 않는다** (양쪽 공용)
- 프론트 분리 시 기존 `index.html`, `admin.html`에서 참조하는 **CSS/JS 경로**를 반드시 함께 수정
- API 경로 변경 시 프론트에서 호출하는 **fetch URL**도 함께 변경 필요
- `file copy.py`, `file copy 2.py` 등 **불필요한 복사본은 정리** 권장
