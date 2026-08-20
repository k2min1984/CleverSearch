"""
########################################################
# Description
# 민감 정보(DB 접속 비밀번호, 커넥션 URL 등) 대칭키 암호화 유틸
# - AES-256-GCM 방식
# - 키는 CREDENTIAL_SECRET + 고정 salt 로 scrypt KDF 적용
# - "enc:v2::<base64(nonce+ciphertext)>" 형태로 저장하여 키 회전 시 점진적 마이그레이션 가능
# - 하위 호환: 구버전 prefix("enc::") 는 기존 SHA-256 키로 복호화 시도(법적/운영 데이터 보존)
########################################################
"""
import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_RAW_KEY_BYTES = (settings.CREDENTIAL_SECRET or "").encode("utf-8")

# v1: SHA-256(secret) — 하위 호환 복호화 전용
_AES_KEY_V1 = hashlib.sha256(_RAW_KEY_BYTES).digest()

# v2: scrypt(secret, salt) — 신규 암호화 표준. salt 는 secret 으로부터 결정적으로 도출 (외부 노출 ↓).
_KDF_SALT = hashlib.sha256(b"cleversearch-credential-kdf-salt-v2|" + _RAW_KEY_BYTES).digest()
_AES_KEY_V2 = hashlib.scrypt(_RAW_KEY_BYTES, salt=_KDF_SALT, n=2 ** 14, r=8, p=1, dklen=32)

_PREFIX_V1 = "enc::"
_PREFIX_V2 = "enc:v2::"


def encrypt(plain_text: str) -> str:
    """평문 → 'enc:v2::<base64(nonce+ciphertext)>' 형태."""
    if not plain_text:
        return plain_text
    nonce = os.urandom(12)  # GCM 권장 96-bit nonce
    aesgcm = AESGCM(_AES_KEY_V2)
    ct = aesgcm.encrypt(nonce, plain_text.encode("utf-8"), None)
    encoded = base64.urlsafe_b64encode(nonce + ct).decode("ascii")
    return f"{_PREFIX_V2}{encoded}"


def decrypt(cipher_text: str) -> str:
    """버전 prefix 자동 인식. 알 수 없는 형식은 평문 그대로 반환(마이그레이션 호환)."""
    if not cipher_text:
        return cipher_text
    if cipher_text.startswith(_PREFIX_V2):
        raw = base64.urlsafe_b64decode(cipher_text[len(_PREFIX_V2):])
        nonce, ct = raw[:12], raw[12:]
        return AESGCM(_AES_KEY_V2).decrypt(nonce, ct, None).decode("utf-8")
    if cipher_text.startswith(_PREFIX_V1):
        raw = base64.urlsafe_b64decode(cipher_text[len(_PREFIX_V1):])
        nonce, ct = raw[:12], raw[12:]
        return AESGCM(_AES_KEY_V1).decrypt(nonce, ct, None).decode("utf-8")
    return cipher_text
