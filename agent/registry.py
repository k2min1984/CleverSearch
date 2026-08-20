"""
########################################################
# Description
# CleverSearch Agent - 등록 파일 텍스트DB
# 이미 색인 요청을 보낸 파일을 텍스트 파일에 한 줄씩 적재하여
# 동일 파일의 중복 전송을 차단한다.
#
# 한 줄 포맷:
#   {abs_path}|{size}|{mtime_int}|{sha1_short}
########################################################
"""
import hashlib
import threading
from pathlib import Path


class FileRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._keys: set[str] = set()
        self._load()

    @staticmethod
    def make_key(file_path: str, size: int, mtime: int, sha1_short: str) -> str:
        return f"{file_path}|{size}|{mtime}|{sha1_short}"

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self._keys.add(line)
        except Exception:
            pass

    def is_registered(self, key: str) -> bool:
        return key in self._keys

    def add(self, key: str) -> None:
        with self._lock:
            if key in self._keys:
                return
            self._keys.add(key)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(key + "\n")

    def count(self) -> int:
        return len(self._keys)

    def clear(self) -> None:
        with self._lock:
            self._keys.clear()
            if self.path.exists():
                self.path.unlink()


def quick_sha1(file_path: str, sample_bytes: int = 65536) -> str:
    """파일의 처음 64KB만 해시. 큰 파일도 가볍게 식별 가능한 보조 지문."""
    h = hashlib.sha1()
    try:
        with open(file_path, "rb") as f:
            h.update(f.read(sample_bytes))
        return h.hexdigest()[:16]
    except Exception:
        return "0" * 16
