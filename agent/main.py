"""
########################################################
# Description
# CleverSearch Agent - GUI 진입점 (Tkinter)
# 특정 폴더의 신규 파일을 감지하여 색인 API 로 전송한다.
# - registered_files.txt 로 이미 보낸 파일 필터링
# - 단일 exe 배포(PyInstaller) 를 전제로 sibling import 사용
########################################################
"""
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# PyInstaller / 직접 실행(어느 cwd 든) 양쪽에서 sibling import 가 동작하도록 처리
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from client import CleverSearchClient, calc_sha256
from config import REGISTRY_PATH, load_config, save_config
from registry import FileRegistry, quick_sha1
from watcher import FolderWatcher


class AgentApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("CleverSearch Agent")
        self.root.geometry("780x580")
        self.root.minsize(700, 500)

        self.cfg = load_config()
        self.registry = FileRegistry(REGISTRY_PATH)
        self.watcher: FolderWatcher | None = None
        self.client: CleverSearchClient | None = None
        self.running = False

        # 워커 스레드 → 메인(Tk) 스레드 작업 마샬링 큐
        # Tcl/Tk 는 스레드 안전하지 않아 위젯/StringVar 직접 접근 시 크래시 발생.
        # 워커는 큐에 람다를 넣고, _ui_pump 가 메인 스레드에서 실행한다.
        self._ui_queue: "queue.Queue" = queue.Queue()

        self._build_ui()
        self._refresh_folder_list()
        self._refresh_status()
        self.root.after(50, self._ui_pump)

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        style = ttk.Style()
        for theme in ("vista", "winnative", "clam"):
            try:
                style.theme_use(theme)
                break
            except Exception:
                continue
        style.configure("Status.TLabel", foreground="#555")

        # API 설정
        top = ttk.LabelFrame(self.root, text="API 설정", padding=10)
        top.pack(fill="x", padx=10, pady=(10, 4))

        ttk.Label(top, text="API URL").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        self.var_url = tk.StringVar(value=self.cfg.get("api_url", ""))
        ttk.Entry(top, textvariable=self.var_url).grid(row=0, column=1, sticky="we", padx=4)

        ttk.Label(top, text="API Key").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        self.var_key = tk.StringVar(value=self.cfg.get("api_key", ""))
        ttk.Entry(top, textvariable=self.var_key, show="*").grid(row=1, column=1, sticky="we", padx=4)

        self.var_verify = tk.BooleanVar(value=bool(self.cfg.get("verify_ssl", False)))
        ttk.Checkbutton(top, text="SSL 인증서 검증", variable=self.var_verify).grid(
            row=2, column=1, sticky="w", padx=4, pady=2
        )
        top.columnconfigure(1, weight=1)

        # 감시 폴더
        mid = ttk.LabelFrame(self.root, text="감시 폴더", padding=10)
        mid.pack(fill="x", padx=10, pady=4)

        list_frame = ttk.Frame(mid)
        list_frame.pack(fill="x")
        self.lst_folders = tk.Listbox(list_frame, height=4, activestyle="dotbox")
        self.lst_folders.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.lst_folders.yview)
        sb.pack(side="right", fill="y")
        self.lst_folders.config(yscrollcommand=sb.set)

        btn_row = ttk.Frame(mid)
        btn_row.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_row, text="폴더 추가", command=self._add_folder).pack(side="left")
        ttk.Button(btn_row, text="선택 삭제", command=self._remove_folder).pack(side="left", padx=4)
        ttk.Label(btn_row, text="확장자:").pack(side="left", padx=(20, 4))
        self.var_exts = tk.StringVar(value=", ".join(self.cfg.get("extensions", [])))
        ttk.Entry(btn_row, textvariable=self.var_exts).pack(side="left", fill="x", expand=True)

        # 컨트롤
        ctrl = ttk.Frame(self.root, padding=(10, 4))
        ctrl.pack(fill="x")
        self.btn_start = ttk.Button(ctrl, text="감시 시작", command=self._toggle)
        self.btn_start.pack(side="left")
        ttk.Button(ctrl, text="설정 저장", command=self._save).pack(side="left", padx=4)
        ttk.Button(ctrl, text="등록 기록 초기화", command=self._reset_registry).pack(side="left", padx=4)
        self.var_status = tk.StringVar(value="대기 중")
        ttk.Label(ctrl, textvariable=self.var_status, style="Status.TLabel").pack(side="right")

        # 로그
        log_frame = ttk.LabelFrame(self.root, text="로그", padding=6)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.txt_log = tk.Text(
            log_frame, height=12, wrap="none", state="disabled",
            font=("Consolas", 9), background="#fafafa", relief="flat", borderwidth=1,
        )
        self.txt_log.pack(side="left", fill="both", expand=True)
        sb2 = ttk.Scrollbar(log_frame, command=self.txt_log.yview)
        sb2.pack(side="right", fill="y")
        self.txt_log.config(yscrollcommand=sb2.set)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- 폴더 목록
    def _refresh_folder_list(self) -> None:
        self.lst_folders.delete(0, tk.END)
        for f in self.cfg.get("folders", []):
            self.lst_folders.insert(tk.END, f)

    def _add_folder(self) -> None:
        d = filedialog.askdirectory(title="감시 폴더 선택")
        if not d:
            return
        d = os.path.normpath(d)
        folders = list(self.cfg.get("folders", []))
        if d in folders:
            return
        folders.append(d)
        self.cfg["folders"] = folders
        self._refresh_folder_list()

    def _remove_folder(self) -> None:
        sel = self.lst_folders.curselection()
        if not sel:
            return
        folders = list(self.cfg.get("folders", []))
        for i in reversed(sel):
            del folders[i]
        self.cfg["folders"] = folders
        self._refresh_folder_list()

    # ---------------------------------------------------------------- 설정
    def _collect_cfg(self) -> dict:
        exts = [e.strip().lower().lstrip(".") for e in self.var_exts.get().split(",") if e.strip()]
        cfg = dict(self.cfg)
        cfg.update(
            {
                "api_url": self.var_url.get().strip(),
                "api_key": self.var_key.get().strip(),
                "verify_ssl": bool(self.var_verify.get()),
                "extensions": exts,
            }
        )
        return cfg

    def _save(self) -> None:
        self.cfg = self._collect_cfg()
        save_config(self.cfg)
        self._log("설정 저장됨")
        self._refresh_status()

    def _reset_registry(self) -> None:
        if not messagebox.askyesno(
            "확인",
            "등록 기록을 모두 삭제하시겠습니까?\n다음 시작 시 폴더 내 모든 파일이 다시 색인 요청됩니다.",
        ):
            return
        self.registry.clear()
        self._log("등록 기록 초기화됨")
        self._refresh_status()

    # ---------------------------------------------------------------- 시작/중지
    def _toggle(self) -> None:
        if self.running:
            self._stop_watch()
        else:
            self._start_watch()

    def _start_watch(self) -> None:
        self.cfg = self._collect_cfg()
        save_config(self.cfg)
        if not self.cfg["api_url"] or not self.cfg["api_key"]:
            messagebox.showwarning("설정 필요", "API URL 과 API Key 를 입력하세요.")
            return
        if not self.cfg["folders"]:
            messagebox.showwarning("설정 필요", "감시할 폴더를 1개 이상 추가하세요.")
            return

        self.client = CleverSearchClient(
            self.cfg["api_url"], self.cfg["api_key"], verify_ssl=self.cfg["verify_ssl"]
        )
        self.watcher = FolderWatcher(
            folders=self.cfg["folders"],
            extensions=self.cfg["extensions"],
            on_new_file=self._handle_new_file,
            on_log=self._log,
            stable_wait_seconds=int(self.cfg.get("stable_wait_seconds", 2)),
        )
        self.watcher.start()
        if self.cfg.get("scan_on_start", True):
            threading.Thread(target=self.watcher.scan_existing, name="agent-scan", daemon=True).start()
        self.running = True
        self.btn_start.config(text="감시 중지")
        self._refresh_status()
        self._log("감시 시작")

    def _stop_watch(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None
        self.running = False
        self.btn_start.config(text="감시 시작")
        self._refresh_status()
        self._log("감시 중지")

    # ---------------------------------------------------------------- 신규 파일 처리
    def _handle_new_file(self, file_path: str) -> None:
        """워커 스레드에서 호출됨. Tk 접근은 절대 직접 하지 말 것.

        흐름:
          1) 1차 차단: 로컬 registry (경로|크기|mtime|앞64KB sha1) 으로 빠르게 컷
          2) 통과 시 전체 SHA-256 계산 → 서버 사전 질의 (/agent-check)
             - 적중: 본문 전송 없이 registry 에 등록만 하고 종료
             - 미적중/장애: 본문 업로드 (X-File-SHA256 헤더 동봉)
        """
        try:
            size = os.path.getsize(file_path)
            mtime = int(os.path.getmtime(file_path))
        except OSError:
            return
        sha_short = quick_sha1(file_path)
        key = FileRegistry.make_key(file_path, size, mtime, sha_short)
        if self.registry.is_registered(key):
            return  # 이미 등록됨 - 조용히 스킵

        name = Path(file_path).name
        self._log(f"감지 -> {name} ({size / 1024:.1f} KB)")

        if self.client is None:
            return

        # 전체 SHA-256 계산 → send_file 에 재사용
        try:
            full_sha = calc_sha256(file_path)
        except Exception as e:
            self._log(f"  [FAIL] SHA 계산 실패: {e}")
            return

        result = self.client.send_file(file_path, precomputed_sha256=full_sha)
        status = str(result.get("status", "?"))
        msg = str(result.get("message", ""))
        precheck_hit = bool(result.get("precheck"))

        if status in ("success", "skipped"):
            self.registry.add(key)
            tag = "OK/precheck" if precheck_hit else "OK"
            self._log(f"  [{tag}] {status}: {msg}")
        else:
            self._log(f"  [FAIL] {status}: {msg}")
        # Tk 접근은 메인 스레드로 마샬링
        self._ui_queue.put(self._refresh_status)

    # ---------------------------------------------------------------- UI 펌프 / 로그 / 상태
    def _ui_pump(self) -> None:
        """메인 스레드에서 50ms 마다 큐에 쌓인 콜백을 꺼내 실행."""
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except queue.Empty:
            pass
        # 윈도우가 살아있는 동안만 재예약
        try:
            self.root.after(50, self._ui_pump)
        except Exception:
            pass

    def _log(self, message: str) -> None:
        # 어떤 스레드에서 호출되든 큐를 통해 안전하게 메인 스레드로 전달
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n"
        self._ui_queue.put(lambda: self._append_log(line))

    def _append_log(self, line: str) -> None:
        self.txt_log.config(state="normal")
        self.txt_log.insert(tk.END, line)
        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")

    def _refresh_status(self) -> None:
        state = "감시 중" if self.running else "대기 중"
        self.var_status.set(f"{state}  |  등록 파일: {self.registry.count()}")

    # ---------------------------------------------------------------- 종료
    def _on_close(self) -> None:
        if self.running and self.watcher is not None:
            self.watcher.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    AgentApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
