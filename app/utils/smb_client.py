"""
########################################################
# Description
# 크로스플랫폼 SMB/CIFS 클라이언트 래퍼
# smbprotocol 기반으로 Windows/Linux/macOS 모두 지원
# - SMB 세션 등록/해제 (context manager)
# - 공유 폴더 재귀 탐색 (확장자 필터)
# - 파일 바이너리 읽기
#
# Modified History
# 현승준 / 2026-04-03 / 최초생성
########################################################
"""
from __future__ import annotations

import logging
from typing import Generator

import smbclient
from smbprotocol.exceptions import SMBConnectionClosed, SMBException

from app.core.config import settings

logger = logging.getLogger(__name__)


class SMBClient:
    """
    SMB 공유 폴더 접근 클라이언트
    - smbprotocol 기반 순수 Python 구현 (OS 무관)
    - 자동 세션 등록/해제
    - 파일 목록 조회 및 바이너리 읽기
    """

    def __init__(
        self,
        share_path: str,
        username: str | None = None,
        password: str | None = None,
        domain: str | None = None,
        port: int = 445,
    ):
        raw = (share_path or "").strip().strip('"').strip("'")
        if raw.lower().startswith("smb://"):
            raw = raw[6:]
        normalized = raw.replace("/", "\\").lstrip("\\")
        parts = [p for p in normalized.split("\\") if p]
        if len(parts) < 2:
            raise ValueError("SMB path must include server and share (e.g. \\\\server\\share)")

        self.server = parts[0]
        self.share = parts[1]
        self.sub_path = "\\".join(parts[2:]) if len(parts) > 2 else ""
        self.username = username
        self.password = password
        self.domain = domain or ""
        self.port = port
        self._registered = False

    @property
    def share_root(self) -> str:
        return f"\\\\{self.server}\\{self.share}"

    @property
    def base_path(self) -> str:
        if self.sub_path:
            return f"{self.share_root}\\{self.sub_path}"
        return self.share_root

    def connect(self) -> None:
        """SMB 세션 등록 (인증 포함)"""
        smbclient.register_session(
            server=self.server,
            username=self.username,
            password=self.password,
            port=self.port,
            connection_timeout=settings.SMB_CONNECT_TIMEOUT,
        )
        self._registered = True
        logger.info("SMB session registered: %s@%s:%d", self.username or "(anonymous)", self.server, self.port)

    def disconnect(self) -> None:
        """SMB 세션 해제"""
        if self._registered:
            try:
                smbclient.delete_session(server=self.server, port=self.port)
            except Exception:
                pass
            self._registered = False

    def test_connection(self) -> bool:
        """연결 테스트 — share_root 접근 가능 여부 확인"""
        try:
            smbclient.listdir(self.share_root)
            return True
        except (SMBException, OSError, ValueError):
            return False

    def walk(self, allowed_extensions: set[str] | None = None) -> Generator[tuple[str, str], None, None]:
        """
        공유 폴더 재귀 탐색
        Yields: (relative_path, full_smb_path)
        """
        stack = [self.base_path]
        while stack:
            current = stack.pop()
            try:
                entries = list(smbclient.scandir(current))
            except (SMBException, OSError, ValueError) as exc:
                logger.warning("SMB scandir failed: %s — %s", current, exc)
                continue

            for entry in entries:
                if entry.is_dir():
                    stack.append(entry.path)
                elif entry.is_file():
                    ext = entry.name.rsplit(".", 1)[-1].lower() if "." in entry.name else ""
                    if allowed_extensions and ext not in allowed_extensions:
                        continue
                    rel = entry.path.replace(self.base_path, "").lstrip("\\").lstrip("/")
                    yield rel, entry.path

    def read_bytes(self, smb_path: str) -> bytes:
        """SMB 경로의 파일을 바이너리로 읽기"""
        # share_access='rwd'로 요청해 다른 프로세스가 파일을 열어둔 경우에도 읽기 시도
        with smbclient.open_file(smb_path, mode="rb", share_access="rwd") as f:
            return f.read()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.disconnect()
