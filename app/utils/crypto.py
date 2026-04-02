"""
########################################################
# Description
# 민감 정보(DB 접속 비밀번호, 커넥션 URL 등) 대칭키 암호화 유틸
# AES-256-GCM 방식으로 암·복호화하며, Base64 문자열로 DB에 저장합니다.
#
# Modified History
# 강광민 / 2026-04-02 / 최초생성
########################################################
"""
import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

# 환경변수 CREDENTIAL_SECRET 을 SHA-256 해싱하여 256-bit 키로 사용
_RAW_KEY = (settings.CREDENTIAL_SECRET or "").encode("utf-8")
_AES_KEY = hashlib.sha256(_RAW_KEY).digest()  # 32 bytes = AES-256

_PREFIX = "enc::"  # 암호화된 값 식별용 접두어


def encrypt(plain_text: str) -> str:
    """평문 → 'enc::<base64(nonce+ciphertext)>' 형태의 암호화 문자열 반환"""
    if not plain_text:
        return plain_text
    nonce = os.urandom(12)  # GCM 권장 96-bit nonce
    aesgcm = AESGCM(_AES_KEY)
    ct = aesgcm.encrypt(nonce, plain_text.encode("utf-8"), None)
    encoded = base64.urlsafe_b64encode(nonce + ct).decode("ascii")
    return f"{_PREFIX}{encoded}"


def decrypt(cipher_text: str) -> str:
    """'enc::...' 암호화 문자열 → 평문 복호화. 접두어 없으면 그대로 반환(하위 호환)"""
    if not cipher_text or not cipher_text.startswith(_PREFIX):
        return cipher_text  # 평문 그대로 반환 (마이그레이션 전 데이터 호환)
    raw = base64.urlsafe_b64decode(cipher_text[len(_PREFIX):])
    nonce, ct = raw[:12], raw[12:]
    aesgcm = AESGCM(_AES_KEY)
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")
