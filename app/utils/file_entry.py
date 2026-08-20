"""
########################################################
# Description
# 원격 파일 walk() 결과를 표현하는 공통 NamedTuple.
# - SMBClient / SFTPClient.walk() 가 동일한 구조로 반환하여
#   상위 색인 로직(process_smb_job)이 한 가지 형식만 다루도록 한다.
# - 위치 unpacking(`for rel, full in walk()`) 도 그대로 동작하도록
#   필드 순서를 (rel_path, full_path, size, mtime) 로 고정.
#   → 기존 호출자가 size/mtime 만 무시한 채 그대로 사용 가능.
#
# 설계 근거: docs/증분색인_설계_20260424_현승준.md §5.2
#
# Modified History
# 현승준 / 2026-04-27 / 최초생성 (Phase 3)
########################################################
"""
from __future__ import annotations

from datetime import datetime
from typing import NamedTuple


class FileEntry(NamedTuple):
    rel_path: str
    full_path: str
    size: int
    mtime: datetime | None
