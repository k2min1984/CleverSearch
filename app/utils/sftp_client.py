"""
########################################################
# Description
# SSH/SFTP 클라이언트 래퍼
# paramiko 기반으로 SSH 연결을 통한 원격 파일 수집 지원
# - SFTP 세션 관리
# - 원격 디렉토리 재귀 탐색 (확장자 필터)
# - 파일 바이너리 읽기
#
# Modified History
# 현승준 / 2026-04-15 / 최초생성
########################################################
"""
from __future__ import annotations

import logging
import os
import stat
from typing import Generator

import paramiko

from app.core.config import settings

logger = logging.getLogger(__name__)


class SFTPClient:
    """
    SSH/SFTP 원격 파일 접근 클라이언트
    - paramiko 기반 순수 Python 구현
    - 패스워드 / 키 파일 인증
    - 원격 디렉토리 재귀 탐색 및 바이너리 읽기
    """

    def __init__(
        self,
        host: str,
        remote_path: str,
        username: str | None = None,
        password: str | None = None,
        port: int = 22,
        key_path: str | None = None,
    ):
        if not host:
            raise ValueError("SSH host는 필수 입력입니다.")
        self.host = host
        self.remote_path = (remote_path or "/").strip()
        self.username = username
        self.password = password
        self.port = port
        self.key_path = key_path
        self._transport: paramiko.Transport | None = None
        self._sftp: paramiko.SFTPClient | None = None

    def connect(self) -> None:
        """SSH 연결 및 SFTP 세션 열기"""
        self._transport = paramiko.Transport((self.host, self.port))
        self._transport.connect(
            username=self.username,
            password=self.password,
            pkey=self._load_key() if self.key_path else None,
        )
        self._sftp = paramiko.SFTPClient.from_transport(self._transport)
        logger.info("SFTP session opened: %s@%s:%d", self.username or "(anonymous)", self.host, self.port)

    def _load_key(self) -> paramiko.PKey | None:
        """SSH 개인키 파일 로드 (RSA/Ed25519/ECDSA 자동 탐지)"""
        if not self.key_path or not os.path.isfile(self.key_path):
            return None
        for key_cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                return key_cls.from_private_key_file(self.key_path, password=self.password)
            except (paramiko.SSHException, ValueError):
                continue
        raise ValueError(f"SSH 키 파일을 로드할 수 없습니다: {self.key_path}")

    def disconnect(self) -> None:
        """SFTP/SSH 세션 종료"""
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None

    def test_connection(self) -> bool:
        """연결 테스트 — 원격 경로 접근 가능 여부 확인"""
        try:
            if self._sftp is None:
                return False
            self._sftp.listdir(self.remote_path)
            return True
        except (IOError, OSError, paramiko.SSHException):
            return False

    def walk(self, allowed_extensions: set[str] | None = None) -> Generator[tuple[str, str], None, None]:
        """
        원격 디렉토리 재귀 탐색
        Yields: (relative_path, full_remote_path)
        """
        if self._sftp is None:
            return
        base = self.remote_path.rstrip("/")
        stack = [base]
        while stack:
            current = stack.pop()
            try:
                entries = self._sftp.listdir_attr(current)
            except (IOError, OSError, paramiko.SSHException) as exc:
                logger.warning("SFTP listdir failed: %s — %s", current, exc)
                continue

            for entry in entries:
                full_path = f"{current}/{entry.filename}"
                if stat.S_ISDIR(entry.st_mode or 0):
                    stack.append(full_path)
                elif stat.S_ISREG(entry.st_mode or 0):
                    ext = entry.filename.rsplit(".", 1)[-1].lower() if "." in entry.filename else ""
                    if allowed_extensions and ext not in allowed_extensions:
                        continue
                    rel = full_path[len(base):].lstrip("/")
                    yield rel, full_path

    def read_bytes(self, remote_path: str) -> bytes:
        """원격 파일을 바이너리로 읽기"""
        if self._sftp is None:
            raise RuntimeError("SFTP 세션이 열려있지 않습니다.")
        with self._sftp.open(remote_path, "rb") as f:
            return f.read()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.disconnect()
