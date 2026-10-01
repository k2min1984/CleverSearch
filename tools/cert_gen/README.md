# CleverSearchCertGen — 로컬 CA + 서버 인증서 발급기 (mkcert 흉내, 단일 exe)

mkcert 와 동일한 운영 모델:
1. **로컬 Root CA** 를 한 번 생성하고
2. **PC 신뢰 저장소에 등록** 한 다음
3. 그 CA 가 서명한 **서버 인증서** 를 필요할 때마다 발급

→ 이후 서버 인증서를 새로 발급해도 **브라우저 경고 없이 자물쇠 표시**.

> ⚠ 개발/사내 데모 용도 전용. 외부 공개 서비스에는 공인 CA 인증서 사용.

---

## 1. 사용 흐름 (최초 1회)

`CleverSearchCertGen.exe` 더블클릭 (이때만 **관리자 권한으로 실행** 권장 — 신뢰 저장소 등록 단계가 권한 필요)

### 탭 ① Root CA
1. **Root CA 생성** 버튼 클릭
   - 기본 저장 폴더: `%LOCALAPPDATA%\CleverSearchCertGen\`
   - 결과: `rootCA.crt`, `rootCA.key`
2. **PC 신뢰 저장소에 등록** 버튼 클릭 (관리자 권한 필요)
   - 내부적으로 `certutil -addstore Root rootCA.crt` 실행
   - 성공하면 브라우저 재시작 후 이 CA 가 신뢰됨

### 탭 ② 서버 인증서 발급
1. CN(예: `DESKTOP-XXXX`), DNS/IP SAN, 유효기간, 저장 폴더 입력
2. **서버 인증서 발급** 버튼 클릭
   - 결과: `<prefix>.crt`, `<prefix>.key`, `<prefix>.fullchain.pem`
   - 옵션: `<prefix>.pfx` 동시 생성 (CA 체인 포함)

### uvicorn 적용
```bat
uvicorn app.main:app --host 0.0.0.0 --port 8000 ^
    --ssl-certfile "C:\path\to\demo.crt" ^
    --ssl-keyfile  "C:\path\to\demo.key"
```
브라우저 재시작 → `https://localhost:8000` 또는 `https://<hostname>:8000` 또는 `https://<LAN-IP>:8000` 모두 자물쇠 정상 표시.

---

## 2. 발급된 서버 인증서 특성

| 속성 | 값 |
|---|---|
| Issuer | `CleverSearch Local Dev CA` (또는 사용자 지정) |
| Self-signed | **False** (CA 가 서명) |
| 키/서명 | RSA 2048~4096 / SHA-256 |
| basicConstraints | CA=False |
| keyUsage | digitalSignature + keyEncipherment |
| extendedKeyUsage | **serverAuth** |
| subjectKeyIdentifier / authorityKeyIdentifier | 자동 |
| SAN | DNS + IP 목록 그대로 반영 |

→ Chrome/Edge/Firefox/Safari/Java/Python requests 등 거의 모든 클라이언트가 정상 인식.

---

## 3. CA 제거 (정리할 때)

탭 ①의 **신뢰 저장소에서 제거** 버튼 클릭 → `certutil -delstore Root <thumbprint>` 실행.
파일 자체를 지우려면 CA 저장 폴더(`%LOCALAPPDATA%\CleverSearchCertGen\`)를 삭제.

---

## 4. 다른 PC 에서 사용

다른 PC 에서도 자물쇠로 표시되게 하려면 **그 PC 에도 rootCA.crt 를 신뢰 등록** 해야 합니다:

### 방법 A — 도구를 다른 PC 에 설치
1. `CleverSearchCertGen.exe` + `rootCA.crt`/`rootCA.key` 를 그 PC 에 복사 (CA 키 동봉 주의 — 사내망 한정)
2. 도구 실행 → CA 저장 폴더를 그 위치로 → "신뢰 저장소에 등록"
3. 같은 CA 로 서명된 서버 인증서가 그 PC 에서도 신뢰됨

### 방법 B — rootCA.crt 만 배포 + 수동 등록
1. `rootCA.crt` 만 다른 PC 로 전송 (키 안 보냄 = 안전)
2. 더블클릭 → 인증서 설치 마법사 → "로컬 컴퓨터" → "신뢰할 수 있는 루트 인증 기관"

---

## 5. 빌드 (개발자용)

### 자동
```bat
cd tools\cert_gen
build.bat
```

### 수동
```bat
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name CleverSearchCertGen ^
    --hidden-import cryptography ^
    --hidden-import cryptography.hazmat.bindings._rust ^
    main.py
```
산출물: `dist\CleverSearchCertGen.exe` (~13.9MB)

---

## 6. 주의

- **CA 개인키 보호**: `%LOCALAPPDATA%\CleverSearchCertGen\rootCA.key` 가 유출되면 누구나 이 CA 로 인증서를 위조할 수 있음. 외부 노출 금지.
- **관리자 권한**: 신뢰 등록/제거 단계만 관리자 권한 필요. 인증서 발급 자체는 일반 권한 가능.
- **SmartScreen / 백신**: 서명 안 된 PyInstaller exe 라 첫 실행 시 경고 가능. "추가 정보 → 실행".
- **외부 서비스에 사용 금지**: 자체 CA 기반이므로 공인 CA 신뢰 체인에 들어가지 않음. 내부망/개발 환경만.

---

## 7. mkcert 와의 차이

| 항목 | mkcert | CleverSearchCertGen |
|---|---|---|
| CA 생성 | 자동 (첫 호출 시) | 명시적 버튼 |
| 신뢰 등록 | `mkcert -install` | 명시적 버튼 (certutil) |
| Firefox NSS DB 자동 등록 | ✅ | ❌ (Windows 인증서 저장소만) |
| GUI | ❌ (CLI) | ✅ (Tkinter) |
| 단일 실행파일 | go 바이너리 | Python+PyInstaller exe |
| CA 폴더 | `%LOCALAPPDATA%\mkcert\` | `%LOCALAPPDATA%\CleverSearchCertGen\` |

Firefox 만 별도 신뢰 저장소를 사용하므로 Firefox 에서도 경고를 없애려면 **rootCA.crt 를 Firefox 의 인증서 관리자에서 직접 가져오기** 가 필요합니다. (`설정 → 개인정보 및 보안 → 인증서 → 인증서 보기 → 인증 기관 → 가져오기 → '이 CA 를 신뢰함' 체크`)
