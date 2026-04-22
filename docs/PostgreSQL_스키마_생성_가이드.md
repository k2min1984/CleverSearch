# PostgreSQL 데이터베이스/스키마 생성 가이드 (초보자용)

작성일: 2026-04-22
대상: PostgreSQL 서버에 직접 접속할 수 없는 개발자/운영자
목표: postgres 계정으로 접속해 DB, 사용자, 스키마를 만들고 CleverSearch 앱과 연결까지 확인

---

## 0. 시작 전에 꼭 확인

아래 3가지를 먼저 준비합니다.

1. 서버 접속 정보

- SSH 계정: SERVER_USER
- SSH 호스트: SERVER_HOST
- SSH 포트: 기본 22 (다르면 별도 전달)

2. PostgreSQL 관리자 정보

- 관리자 계정: postgres
- postgres 비밀번호 (또는 sudo 전환 권한)

3. 앱에서 사용할 값

- DB 이름: cleversearch
- DB 사용자: cleversearch
- DB 비밀번호: 강한 비밀번호로 변경 권장
- 스키마 이름: custom_schema

---

## 1. 종료 목표(완료 기준)

아래 4가지가 되면 작업 완료입니다.

1. PostgreSQL에 cleversearch DB가 존재
2. custom_schema 스키마가 생성됨
3. cleversearch 계정이 DB/스키마 권한을 가짐
4. 프로젝트에서 alembic upgrade head 실행 시 오류 없음

---

## 2. 경로 A: 리눅스 DB 서버에 직접 접속해서 생성

### 2-1. 서버 접속

```bash
ssh SERVER_USER@SERVER_HOST
```

### 2-2. postgres 계정으로 전환 후 psql 접속

방법 1: sudo 권한이 있는 경우

```bash
sudo -i -u postgres
psql
```

방법 2: postgres 비밀번호로 접속하는 경우

```bash
psql -U postgres -h 127.0.0.1 -p 5432
```

정상 접속되면 프롬프트가 postgres=# 형태로 보입니다.

### 2-3. DB/사용자/스키마 생성 (순서대로 실행)

```sql
-- 1) 앱 사용자 생성
CREATE USER cleversearch WITH PASSWORD 'CHANGE_ME_STRONG_PASSWORD';

-- 2) 앱 DB 생성
CREATE DATABASE cleversearch OWNER cleversearch;

-- 3) 생성한 DB로 이동
\c cleversearch

-- 4) 스키마 생성 (소유자 지정)
CREATE SCHEMA IF NOT EXISTS custom_schema AUTHORIZATION cleversearch;

-- 5) 권한 보강
GRANT ALL ON SCHEMA custom_schema TO cleversearch;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA custom_schema TO cleversearch;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA custom_schema TO cleversearch;

-- 6) 앞으로 생성될 테이블/시퀀스 기본 권한
ALTER DEFAULT PRIVILEGES IN SCHEMA custom_schema
GRANT ALL PRIVILEGES ON TABLES TO cleversearch;

ALTER DEFAULT PRIVILEGES IN SCHEMA custom_schema
GRANT ALL PRIVILEGES ON SEQUENCES TO cleversearch;
```

### 2-4. 생성 확인

```sql
-- DB 목록
\l

-- 스키마 목록
\dn

-- 현재 DB 확인
SELECT current_database();

-- 종료
\q
```

---

## 3. 경로 B: Docker PostgreSQL 컨테이너에서 생성

프로젝트 기본 컨테이너명은 cleversearch-postgres 입니다.

### 3-1. 컨테이너 실행 확인

```bash
docker ps | grep cleversearch-postgres
```

### 3-2. postgres 관리자 접속

```bash
docker exec -it cleversearch-postgres psql -U postgres -d postgres
```

### 3-3. 생성 SQL 실행

경로 A의 2-3 SQL을 그대로 실행합니다.

---

## 4. CleverSearch 앱 연결 (가장 중요)

프로젝트는 DATABASE_URL을 기준으로 DB에 연결합니다.

예시:

```text
postgresql+psycopg2://cleversearch:CHANGE_ME_STRONG_PASSWORD@DB_HOST:5432/cleversearch
```

참고 파일:

- alembic.ini
- docker-compose.yml
- alembic/env.py

스키마를 custom_schema로 강제하려면 search_path 옵션을 사용합니다.

```text
postgresql+psycopg2://cleversearch:CHANGE_ME_STRONG_PASSWORD@DB_HOST:5432/cleversearch?options=-csearch_path%3Dcustom_schema
```

---

## 5. 테이블 생성은 Alembic으로 진행

DB/스키마만 수동 생성하고, 실제 테이블은 마이그레이션으로 생성합니다.

프로젝트 루트에서 실행:

```bash
alembic upgrade head
```

성공 확인:

```bash
alembic current
```

---

## 6. 접속 테스트 (초보자 점검용)

### 6-1. psql로 앱 계정 로그인 테스트

```bash
psql "host=DB_HOST port=5432 dbname=cleversearch user=cleversearch password=CHANGE_ME_STRONG_PASSWORD"
```

### 6-2. 스키마와 테이블 확인

```sql
SHOW search_path;
\dn
\dt custom_schema.*
```

---

## 7. 자주 나는 오류와 해결

오류: FATAL: password authentication failed

- 원인: 비밀번호 불일치
- 해결: ALTER USER cleversearch WITH PASSWORD '새비밀번호'; 후 재시도

오류: permission denied for schema custom_schema

- 원인: 스키마 권한 누락
- 해결: GRANT ALL ON SCHEMA custom_schema TO cleversearch;

오류: relation does not exist

- 원인: 마이그레이션 미실행 또는 search_path 미설정
- 해결: alembic upgrade head 실행 + DATABASE_URL의 search_path 확인

---

## 8. 빠른 실행 요약 (복붙용)

```sql
CREATE USER cleversearch WITH PASSWORD 'CHANGE_ME_STRONG_PASSWORD';
CREATE DATABASE cleversearch OWNER cleversearch;
\c cleversearch
CREATE SCHEMA IF NOT EXISTS custom_schema AUTHORIZATION cleversearch;
GRANT ALL ON SCHEMA custom_schema TO cleversearch;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA custom_schema TO cleversearch;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA custom_schema TO cleversearch;
ALTER DEFAULT PRIVILEGES IN SCHEMA custom_schema GRANT ALL PRIVILEGES ON TABLES TO cleversearch;
ALTER DEFAULT PRIVILEGES IN SCHEMA custom_schema GRANT ALL PRIVILEGES ON SEQUENCES TO cleversearch;
```

작업 끝.

---

## 9. 로컬 데이터 이관 (회의 기준: 전체 이관 필수)

"DB를 새로 만들면 로컬 데이터를 옮겨야 하나요?"에 대한 답은 "예"입니다.
회의 기준으로는 로컬에서 사용 중인 PostgreSQL 테이블을 전체 이관하는 것을 기본으로 합니다.

운영 시작 전 최소 2가지는 이관해야 합니다.

1. PostgreSQL 데이터 (테이블/행)
2. 앱 파일 데이터(예: uploads 폴더를 쓰는 경우)

아래는 초보자 기준으로 가장 안전한 절차입니다.

### 9-0. 무엇을 옮길지 먼저 결정 (중요)

기본 원칙 (운영 전환): 전체 DB 이관

- 로컬 PostgreSQL의 앱 테이블/행 데이터를 전체 이관
- 이관 후 alembic upgrade head로 최신 리비전 동기화

예외 원칙 (임시/POC): 관리자 데이터만 이관

- 일정이 급한 임시 전환 시에만 선택
- 정식 운영 전환에서는 비권장

관리자 데이터만 이관할 때 대상 테이블:

- auth_roles
- auth_users
- smb_sources
- db_sources
- dictionary_entries
- certificate_status

상황별 선택 이관:

- recent_searches: 사용자 최근검색 기록까지 유지하려는 경우
- search_logs: 과거 검색로그 분석을 이어가려는 경우
- indexed_documents: 기존 인덱싱 메타를 유지하려는 경우 (보통은 재색인 권장)

보통 이관하지 않아도 되는 데이터:

- revoked_access_tokens
- revoked_refresh_tokens

위 두 테이블은 토큰 블랙리스트(일시 데이터) 성격이므로 신규 환경에서는 비워 시작해도 무방합니다.

### 9-1. 이관 방식 선택

- 기본(회의 기준): pg_dump + pg_restore (전체 DB)
- 부분 이관(옵션): 특정 스키마만 덤프(-n custom_schema)

### 9-1-1. 서버 사전 셋팅 (원격 접속 사용 시)

서버에서 원격 복원/접속이 필요하면 아래를 먼저 확인합니다.

1. postgresql.conf

```conf
listen_addresses = '*'
port = 5432
```

2. pg_hba.conf (예: 사내망만 허용)

```conf
host    all    all    10.10.0.0/16    md5
```

3. 설정 반영

```bash
sudo systemctl restart postgresql
sudo systemctl status postgresql
```

보안 주의:

- 0.0.0.0/0 전체 허용 금지
- 운영망 CIDR만 허용
- 방화벽도 5432를 운영망에만 개방

### 9-2. 로컬에서 덤프 생성 (Docker PostgreSQL 기준)

PowerShell(윈도우)에서 프로젝트 루트 기준:

```powershell
# 1) 컨테이너 안에 덤프 파일 생성
docker exec cleversearch-postgres pg_dump -U cleversearch -d cleversearch -Fc -f /tmp/cleversearch_full.dump

# 2) 컨테이너 -> 로컬 복사
docker cp cleversearch-postgres:/tmp/cleversearch_full.dump .\cleversearch_full.dump
```

관리자 데이터만 이관(옵션) 덤프:

```powershell
docker exec cleversearch-postgres pg_dump -U cleversearch -d cleversearch -Fc \
	-t auth_roles \
	-t auth_users \
	-t smb_sources \
	-t db_sources \
	-t dictionary_entries \
	-t certificate_status \
	-f /tmp/cleversearch_admin_only.dump

docker cp cleversearch-postgres:/tmp/cleversearch_admin_only.dump .\cleversearch_admin_only.dump
```

특정 스키마만 이관하고 싶다면:

```powershell
docker exec cleversearch-postgres pg_dump -U cleversearch -d cleversearch -n custom_schema -Fc -f /tmp/cleversearch_schema.dump
docker cp cleversearch-postgres:/tmp/cleversearch_schema.dump .\cleversearch_schema.dump
```

### 9-3. 덤프 파일을 서버로 전송

```powershell
scp .\cleversearch_full.dump SERVER_USER@SERVER_HOST:/tmp/
```

관리자 데이터만 이관 시:

```powershell
scp .\cleversearch_admin_only.dump SERVER_USER@SERVER_HOST:/tmp/
```

### 9-4. 서버에서 복원

서버 접속:

```bash
ssh SERVER_USER@SERVER_HOST
```

복원 명령:

```bash
# (선택) postgres 계정 전환
sudo -i -u postgres

# 1) 대상 DB가 비어있어야 가장 안전
#    필요 시 기존 데이터 정리 후 진행

# 2) 복원 실행
pg_restore -U cleversearch -d cleversearch --no-owner --no-privileges /tmp/cleversearch_full.dump
```

관리자 데이터만 이관 시:

```bash
pg_restore -U cleversearch -d cleversearch --no-owner --no-privileges /tmp/cleversearch_admin_only.dump
```

스키마만 복원 시:

```bash
pg_restore -U cleversearch -d cleversearch --no-owner --no-privileges /tmp/cleversearch_schema.dump
```

### 9-5. 복원 확인

```bash
psql -U cleversearch -d cleversearch -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='custom_schema';"
psql -U cleversearch -d cleversearch -c "SELECT version_num FROM alembic_version;"
```

관리자 데이터만 이관 검증 쿼리:

```bash
psql -U cleversearch -d cleversearch -c "SELECT 'auth_users' AS table_name, count(*) FROM auth_users;"
psql -U cleversearch -d cleversearch -c "SELECT 'smb_sources' AS table_name, count(*) FROM smb_sources;"
psql -U cleversearch -d cleversearch -c "SELECT 'db_sources' AS table_name, count(*) FROM db_sources;"
psql -U cleversearch -d cleversearch -c "SELECT 'dictionary_entries' AS table_name, count(*) FROM dictionary_entries;"
```

### 9-6. 앱 마이그레이션 동기화

복원 후에도 코드 기준 최신 스키마와 맞춰야 하므로 프로젝트에서 1회 실행:

```bash
alembic upgrade head
```

### 9-7. 전체 이관 원샷 순서 (복붙용)

아래 순서대로 실행하면 됩니다.

```powershell
# [로컬] 1) 전체 덤프 생성
docker exec cleversearch-postgres pg_dump -U cleversearch -d cleversearch -Fc -f /tmp/cleversearch_full.dump

# [로컬] 2) 컨테이너 -> 로컬 복사
docker cp cleversearch-postgres:/tmp/cleversearch_full.dump .\cleversearch_full.dump

# [로컬] 3) 서버 전송
scp .\cleversearch_full.dump SERVER_USER@SERVER_HOST:/tmp/
```

```bash
# [서버] 4) 복원
pg_restore -U cleversearch -d cleversearch --no-owner --no-privileges /tmp/cleversearch_full.dump

# [서버] 5) 기본 검증
psql -U cleversearch -d cleversearch -c "SELECT count(*) FROM information_schema.tables;"

# [앱 서버/프로젝트 루트] 6) 최신 리비전 반영
alembic upgrade head
```

---

## 10. 파일 데이터(uploads) 이관

DB만 옮기고 파일을 안 옮기면 문서 원본 경로가 깨질 수 있습니다.

로컬 -> 서버 전송 예시:

```powershell
# 프로젝트 루트에서 실행
scp -r .\uploads SERVER_USER@SERVER_HOST:/opt/cleversearch/
```

서버에서 권한 정리 예시:

```bash
sudo chown -R APP_USER:APP_GROUP /opt/cleversearch/uploads
sudo chmod -R 755 /opt/cleversearch/uploads
```

---

## 11. 최종 점검 체크리스트

- [ ] DB 연결 성공 (앱 기동 시 DB 에러 없음)
- [ ] alembic upgrade head 성공
- [ ] 관리자 화면에서 기존 데이터 조회 가능
- [ ] 문서 상세/다운로드 시 파일 경로 오류 없음
- [ ] 스케줄러 1회 실행 성공

---

## 12. 지령 반영: 야탑 신규 개발서버 즉시 실행 절차

지령 정보:

- 호스트: dev.c2r.co.kr
- 포트: 45432
- DB 계정: postgres
- 비밀번호: dudflgks12!@

목표:

- postgres 계정으로 접속
- 신규 스키마 생성

### 12-1. PowerShell에서 접속 (권장: 비밀번호 프롬프트 방식)

```powershell
psql -h dev.c2r.co.kr -p 45432 -U postgres -d postgres
```

명령 실행 후 비밀번호 입력 창이 뜨면 아래 비밀번호를 그대로 입력합니다.

```text
dudflgks12!@
```

### 12-2. 스키마 생성 SQL

psql 접속 후 아래를 순서대로 실행합니다.

```sql
-- 1) 신규 스키마 생성 (이름은 필요 시 변경)
CREATE SCHEMA IF NOT EXISTS cleversearch_dev AUTHORIZATION postgres;

-- 2) 생성 확인
\dn

-- 3) 현재 DB 확인
SELECT current_database();
```

### 12-3. (선택) 앱 계정 생성 + 권한 부여

운영 시 postgres 계정 직결 대신 앱 전용 계정 권장:

```sql
CREATE USER cleversearch WITH PASSWORD 'CHANGE_ME_STRONG_PASSWORD';
GRANT ALL ON SCHEMA cleversearch_dev TO cleversearch;
ALTER ROLE cleversearch IN DATABASE postgres SET search_path TO cleversearch_dev, public;
```

### 12-4. 전체 이관 시 복원 명령 (해당 서버 기준)

```bash
pg_restore -h dev.c2r.co.kr -p 45432 -U postgres -d postgres --no-owner --no-privileges /tmp/cleversearch_full.dump
```

### 12-5. 접속 오류 시 체크

- `Connection timed out`: 서버 방화벽/보안그룹에서 45432 포트 차단 여부 확인
- `password authentication failed`: 비밀번호 오탈자 확인 (특수문자 포함)
- `psql not found`: PostgreSQL client 설치 필요 (`psql` 명령 제공 패키지)
