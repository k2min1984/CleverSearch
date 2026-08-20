"""
########################################################
# Description
# [M-7] PII 마스킹 유틸 — 국정원 「개인정보의 안전성 확보조치 기준」 준수
# 검색어/감사 로그/일반 텍스트에 들어갈 수 있는 식별 가능 정보를 마스킹.
########################################################
"""
import re
from typing import Pattern

from app.core.config import settings


# 주민등록번호: YYMMDD-CDDDDD (앞 6 + 뒤 7)
_RRN: Pattern[str] = re.compile(r"\b(\d{6})[-\s]?\d{7}\b")
# 외국인등록번호: 동일 형식
_FRN: Pattern[str] = _RRN
# 신용카드(13~19자리, 4자리 단위 구분 가능)
_CARD: Pattern[str] = re.compile(r"\b(?:\d[ -]?){13,19}\b")
# 휴대전화: 010-XXXX-XXXX 등
_PHONE: Pattern[str] = re.compile(r"\b(01[016789])[-\s]?(\d{3,4})[-\s]?(\d{4})\b")
# 이메일
_EMAIL: Pattern[str] = re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
# 사업자등록번호 10자리: 3-2-5
_BIZNO: Pattern[str] = re.compile(r"\b(\d{3})[-\s]?(\d{2})[-\s]?(\d{5})\b")


def _mask_card(m: re.Match) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    if 13 <= len(digits) <= 19:
        return f"{digits[:4]}-****-****-{digits[-4:]}"
    return m.group(0)


def mask_pii(text: str) -> str:
    """입력 텍스트의 한국 표준 PII 패턴을 마스킹.

    - 주민/외국인등록번호: 앞 6자리만 노출, 뒤 전체 *
    - 신용카드: 앞 4 + 뒤 4만 노출
    - 휴대전화: 가운데 4자리 *
    - 이메일: 로컬파트 첫 1자만 노출
    - 사업자등록번호: 가운데 2자리 *
    """
    if not text or not settings.PII_MASKING_ENABLED:
        return text or ""
    s = str(text)
    s = _RRN.sub(lambda m: f"{m.group(1)}-*******", s)
    s = _CARD.sub(_mask_card, s)
    s = _PHONE.sub(lambda m: f"{m.group(1)}-****-{m.group(3)}", s)
    s = _EMAIL.sub(lambda m: f"{m.group(1)[:1]}***@{m.group(2)}", s)
    s = _BIZNO.sub(lambda m: f"{m.group(1)}-**-{m.group(3)}", s)
    return s
