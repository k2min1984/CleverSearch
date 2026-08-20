"""
########################################################
# Description
# CleverSearch Agent - 폴더 감시기
# watchdog 으로 신규/이동 파일 이벤트를 감지하여 워커 스레드에서
# 안정 상태(쓰기 완료) 검증 후 콜백을 호출한다.
########################################################
"""
import os
import threading
import time
from pathlib import Path
from queue import Empty, Queue
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class _Handler(FileSystemEventHandler):
    def __init__(self, queue: "Queue[str]", exts: set[str]):
        super().__init__()
        self.queue = queue
        self.exts = exts

    def _accept(self, path: str) -> bool:
        if not self.exts:
            return True
        ext = Path(path).suffix.lower().lstrip(".")
        return ext in self.exts

    def on_created(self, event):
        if event.is_directory:
            return
        if self._accept(event.src_path):
            self.queue.put(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        # 임시파일 → 최종 이름 rename 케이스(예: Word 저장)
        dest = getattr(event, "dest_path", "") or ""
        if dest and self._accept(dest):
            self.queue.put(dest)


class FolderWatcher:
    """여러 폴더를 동시에 감시. on_new_file(path) 을 워커 스레드에서 호출한다."""

    def __init__(
        self,
        folders: list[str],
        extensions: list[str],
        on_new_file: Callable[[str], None],
        on_log: Callable[[str], None],
        stable_wait_seconds: int = 2,
    ):
        self.folders = [f for f in folders if Path(f).exists()]
        self.exts = {e.lower().lstrip(".") for e in extensions if e}
        self.on_new_file = on_new_file
        self.on_log = on_log
        self.stable_wait = max(0, int(stable_wait_seconds))

        self._observer: Observer | None = None
        self._queue: "Queue[str]" = Queue()
        self._worker: threading.Thread | None = None
        self._stop_evt = threading.Event()

    def start(self) -> None:
        if self._observer is not None:
            return
        self._stop_evt.clear()
        self._observer = Observer()
        handler = _Handler(self._queue, self.exts)
        for folder in self.folders:
            try:
                self._observer.schedule(handler, folder, recursive=True)
                self.on_log(f"감시 시작: {folder}")
            except Exception as e:
                self.on_log(f"감시 등록 실패 ({folder}): {e}")
        self._observer.start()
        self._worker = threading.Thread(target=self._consume, name="agent-worker", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=5)
            except Exception:
                pass
            self._observer = None
        if self._worker is not None:
            self._worker.join(timeout=5)
            self._worker = None

    def scan_existing(self) -> None:
        """시작 시 폴더 내 기존 파일을 큐에 투입한다(미등록 파일만 색인 처리됨)."""
        for folder in self.folders:
            for root, _dirs, files in os.walk(folder):
                for name in files:
                    full = os.path.join(root, name)
                    if not self.exts or Path(name).suffix.lower().lstrip(".") in self.exts:
                        self._queue.put(full)

    def _consume(self) -> None:
        while not self._stop_evt.is_set():
            try:
                path = self._queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                if not self._wait_stable(path):
                    self.on_log(f"파일 안정화 실패(스킵): {path}")
                    continue
                self.on_new_file(path)
            except Exception as e:
                self.on_log(f"처리 오류({path}): {e}")

    def _wait_stable(self, path: str, max_wait: int = 60) -> bool:
        """파일 크기가 stable_wait 초 동안 변하지 않으면 안정 상태로 본다."""
        if self.stable_wait <= 0:
            return Path(path).exists()
        prev_size = -1
        stable_count = 0
        elapsed = 0
        while elapsed < max_wait and not self._stop_evt.is_set():
            if not Path(path).exists():
                return False
            try:
                size = os.path.getsize(path)
            except OSError:
                return False
            if size == prev_size and size > 0:
                stable_count += 1
                if stable_count >= self.stable_wait:
                    return True
            else:
                stable_count = 0
                prev_size = size
            time.sleep(1)
            elapsed += 1
        return False
