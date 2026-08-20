"""
########################################################
# Description
# CleverSearch Agent - API HTTP 클라이언트
# - 감지된 파일을 multipart/form-data 로 색인 API 에 전송
# - 전송 전 SHA-256 사전 질의(/agent-check) 로 서버에 이미 있는 파일은 본문 전송 자체를 생략
# - 본문 전송 시 X-File-SHA256 / X-File-Size 헤더를 동봉하여
#   서버측 무결성 검증 + 디버깅 추적성을 강화
########################################################
"""
import hashlib
import os
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx


def calc_sha256(file_path: str, chunk_size: int = 1024 * 1024) -> str:
    """파일 전체 SHA-256 해시 (1MB 청크 스트리밍 - 대용량도 메모리 안전)."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


class CleverSearchClient:
    # 큰 PDF 임베딩은 수십초 걸릴 수 있어 connect/read 분리해서 느슨하게 잡는다.
    DEFAULT_TIMEOUT = httpx.Timeout(connect=15.0, read=600.0, write=120.0, pool=5.0)
    # 사전 질의는 가벼운 GET 이라 짧게.
    CHECK_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)

    def __init__(self, base_url: str, api_key: str, verify_ssl: bool = False):
        self.base_url = base_url.strip().rstrip("/")
        self.api_key = api_key.strip()
        self.verify_ssl = bool(verify_ssl)
        self.check_url = self._derive_check_url(self.base_url)

    @staticmethod
    def _derive_check_url(notify_url: str) -> str:
        """notify URL 의 마지막 path 만 agent-check 로 치환.

        예) https://host/api/v1/index/agent-notify
            → https://host/api/v1/index/agent-check
        """
        try:
            parts = urlsplit(notify_url)
            path = parts.path or ""
            if path.endswith("/agent-notify"):
                new_path = path[: -len("/agent-notify")] + "/agent-check"
            else:
                # 비표준 URL 이면 같은 디렉토리에 agent-check 를 붙인다.
                new_path = path.rstrip("/") + "/../agent-check"
            return urlunsplit((parts.scheme, parts.netloc, new_path, "", ""))
        except Exception:
            return notify_url.rstrip("/") + "/../agent-check"

    # ------------------------------------------------------------------
    # 사전 질의: 서버에 이미 동일 SHA 가 있으면 본문 전송을 생략
    # ------------------------------------------------------------------
    def check_exists(self, sha256: str) -> dict:
        """서버 SHA 사전 질의. 네트워크 실패 시 {"unknown": True} 반환(폴백 → 풀업로드)."""
        if not sha256:
            return {"unknown": True, "reason": "empty sha"}
        try:
            headers = {"X-Agent-Key": self.api_key}
            with httpx.Client(verify=self.verify_ssl, timeout=self.CHECK_TIMEOUT) as cli:
                resp = cli.get(self.check_url, params={"sha256": sha256}, headers=headers)
            if resp.status_code == 200:
                try:
                    return resp.json()
                except Exception:
                    return {"unknown": True, "reason": "json parse"}
            if resp.status_code == 404:
                # 구버전 서버: 사전 질의 미지원 → 폴백
                return {"unknown": True, "reason": "endpoint not found"}
            # 401/503 등은 본문 업로드도 어차피 실패하므로 그대로 폴백
            return {"unknown": True, "reason": f"http {resp.status_code}"}
        except httpx.RequestError as e:
            return {"unknown": True, "reason": f"network: {e}"}
        except Exception as e:
            return {"unknown": True, "reason": f"error: {e}"}

    # ------------------------------------------------------------------
    # 파일 전송 (사전 질의 → 본문 업로드)
    # ------------------------------------------------------------------
    def send_file(
        self,
        file_path: str,
        timeout: httpx.Timeout | float | None = None,
        precomputed_sha256: str | None = None,
    ) -> dict:
        p = Path(file_path)
        if not p.exists() or not p.is_file():
            return {"status": "fail", "message": "파일이 존재하지 않음", "file": file_path}

        try:
            file_size = os.path.getsize(p)
        except OSError as e:
            return {"status": "fail", "message": f"파일 크기 읽기 실패: {e}", "file": p.name}

        # SHA-256 계산 (호출자가 미리 준 게 있으면 재사용)
        try:
            sha256_hex = precomputed_sha256 or calc_sha256(str(p))
        except Exception as e:
            return {"status": "fail", "message": f"SHA 계산 실패: {e}", "file": p.name}

        # 1) 사전 질의 - 서버에 이미 있으면 풀업로드 스킵
        check = self.check_exists(sha256_hex)
        if check.get("exists") is True:
            return {
                "status": "skipped",
                "message": f"DB 중복(사전 질의): {check.get('origin_file', '')}",
                "file": p.name,
                "sha256": sha256_hex,
                "size": file_size,
                "precheck": True,
            }

        effective_timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT

        # 2) 본문 업로드 (sha/size 헤더 동봉)
        # 일시적 disconnect/네트워크 흔들림 방어용 1회 재시도. (서버는 SHA-256 으로 동일파일 차단 보장)
        last_error: str = ""
        for attempt in (1, 2):
            try:
                with open(p, "rb") as f:
                    files = {"file": (p.name, f, "application/octet-stream")}
                    data = {"source_path": str(p.resolve())}
                    headers = {
                        "X-Agent-Key": self.api_key,
                        "X-File-SHA256": sha256_hex,
                        "X-File-Size": str(file_size),
                    }
                    with httpx.Client(verify=self.verify_ssl, timeout=effective_timeout) as cli:
                        resp = cli.post(self.base_url, files=files, data=data, headers=headers)

                if resp.status_code == 200:
                    try:
                        out = resp.json()
                    except Exception:
                        out = {"status": "success", "message": resp.text[:200], "file": p.name}
                    out.setdefault("sha256", sha256_hex)
                    out.setdefault("size", file_size)
                    return out

                # 4xx 는 재시도 의미 없음 - 즉시 반환
                if 400 <= resp.status_code < 500:
                    try:
                        detail = resp.json().get("detail", resp.text)
                    except Exception:
                        detail = resp.text
                    return {
                        "status": "fail",
                        "message": f"HTTP {resp.status_code}: {str(detail)[:200]}",
                        "file": p.name,
                        "sha256": sha256_hex,
                        "size": file_size,
                    }

                # 5xx: 재시도
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except httpx.RequestError as e:
                last_error = f"네트워크 오류: {e}"
            except Exception as e:
                return {
                    "status": "fail",
                    "message": f"전송 실패: {e}",
                    "file": p.name,
                    "sha256": sha256_hex,
                    "size": file_size,
                }

            if attempt == 1:
                time.sleep(1.5)

        return {
            "status": "fail",
            "message": last_error,
            "file": p.name,
            "sha256": sha256_hex,
            "size": file_size,
        }
