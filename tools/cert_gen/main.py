"""
########################################################
# Description
# CleverSearch — 로컬 인증서 발급기 (mkcert 흉내, GUI)
# - 로컬 루트 CA 1회 생성 + Windows 신뢰 저장소 자동 등록 (certutil)
# - 그 CA 가 서명한 서버 인증서를 발급 (CN/SAN/유효기간 자유)
# - PEM (key + crt) + PKCS#12 (.pfx) 옵션
# - 외부 OpenSSL 불필요 (cryptography 만 사용)
# - PyInstaller --onefile --windowed 로 단일 exe
#
# 탭 구성
#   1) Root CA       — 생성 / 신뢰 등록 / 신뢰 해제 / 위치 확인
#   2) Server Cert   — CA 로 서명된 서버 인증서 발급
########################################################
"""
from __future__ import annotations

import datetime as _dt
import ipaddress
import os
import socket
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


APP_TITLE = "CleverSearch — 로컬 인증서 발급기 (mkcert 흉내)"
DEFAULT_CA_DAYS = 3650          # 10년
DEFAULT_SERVER_DAYS = 365       # 1년
DEFAULT_KEY_BITS = 2048
KEY_BIT_OPTIONS = (2048, 3072, 4096)
CA_FRIENDLY_NAME = "CleverSearch Local Dev CA"


# ──────────────────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────────────────
def default_ca_dir() -> Path:
    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home())
    return Path(base) / "CleverSearchCertGen"


def default_server_outdir() -> Path:
    """서버 인증서 기본 저장 위치 = 사용자 Documents 하위.
    exe cwd(Path.cwd()) 를 쓰면 dist 폴더 등 엉뚱한 곳에 생기는 함정이 있어
    명시적으로 안정된 위치로 고정.
    """
    docs = os.getenv("USERPROFILE")
    if docs:
        d = Path(docs) / "Documents" / "CleverSearchCerts"
    else:
        d = Path.home() / "CleverSearchCerts"
    return d


def detect_local_ips() -> list[str]:
    ips: set[str] = {"127.0.0.1"}
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None):
            ip = info[4][0]
            if ":" in ip:
                continue
            ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


def write_pem(path: Path, data: bytes, secret: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if secret:
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass


def load_ca(crt_path: Path, key_path: Path) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    cert = x509.load_pem_x509_certificate(crt_path.read_bytes())
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("CA 키는 RSA 형식이어야 합니다")
    return cert, key


def run_silent(cmd: list[str]) -> tuple[int, str, str]:
    """콘솔창 안 띄우고 외부 명령 실행."""
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, check=False,
        creationflags=creationflags,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


# ──────────────────────────────────────────────────────────────────────
# 인증서 빌더
# ──────────────────────────────────────────────────────────────────────
def build_root_ca(*, common_name: str, organization: str, country: str,
                  days: int, key_bits: int) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    pkey = rsa.generate_private_key(public_exponent=65537, key_size=key_bits)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, country[:2] or "KR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization or "CleverSearch Local"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name or "CleverSearch Local Dev CA"),
    ])
    now = _dt.datetime.now(_dt.timezone.utc)
    skid = x509.SubjectKeyIdentifier.from_public_key(pkey.public_key())
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(pkey.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                key_cert_sign=True, crl_sign=True,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(skid, critical=False)
        .sign(pkey, hashes.SHA256())
    )
    return cert, pkey


def build_server_cert(*, ca_cert: x509.Certificate, ca_key: rsa.RSAPrivateKey,
                      common_name: str, organization: str, country: str,
                      dns_names: list[str], ip_objs: list,
                      days: int, key_bits: int) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    pkey = rsa.generate_private_key(public_exponent=65537, key_size=key_bits)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, country[:2] or "KR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization or "CleverSearch Demo"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    sans: list[x509.GeneralName] = [x509.DNSName(d) for d in dns_names]
    sans += [x509.IPAddress(ip) for ip in ip_objs]
    if not sans:
        raise ValueError("DNS 또는 IP 중 최소 하나는 SAN 으로 입력해야 합니다")

    now = _dt.datetime.now(_dt.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(pkey.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=True,
                data_encipherment=False, key_agreement=False,
                key_cert_sign=False, crl_sign=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(pkey.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
            critical=False,
        )
    )
    cert = builder.sign(ca_key, hashes.SHA256())
    return cert, pkey


# ──────────────────────────────────────────────────────────────────────
# Windows 신뢰 저장소 작업
# ──────────────────────────────────────────────────────────────────────
def trust_install_windows(crt_path: Path) -> tuple[bool, str]:
    """certutil 로 LocalMachine Root 에 설치 (관리자 권한 필요)."""
    code, out, err = run_silent(["certutil", "-addstore", "Root", str(crt_path)])
    msg = (out + "\n" + err).strip()
    return code == 0, msg


def trust_uninstall_windows(thumbprint: str) -> tuple[bool, str]:
    code, out, err = run_silent(["certutil", "-delstore", "Root", thumbprint])
    msg = (out + "\n" + err).strip()
    return code == 0, msg


def cert_thumbprint_sha1(cert: x509.Certificate) -> str:
    return cert.fingerprint(hashes.SHA1()).hex().upper()


# ──────────────────────────────────────────────────────────────────────
# GUI
# ──────────────────────────────────────────────────────────────────────
class CertGenApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("960x780")
        self.root.minsize(900, 720)

        style = ttk.Style()
        for theme in ("vista", "winnative", "clam"):
            try:
                style.theme_use(theme)
                break
            except Exception:
                continue

        # 공용 변수
        self.var_ca_dir = tk.StringVar(value=str(default_ca_dir()))
        self.var_status = tk.StringVar(value="대기 중")

        # CA 탭 변수
        self.var_ca_cn = tk.StringVar(value="CleverSearch Local Dev CA")
        self.var_ca_org = tk.StringVar(value="CleverSearch Local")
        self.var_ca_country = tk.StringVar(value="KR")
        self.var_ca_days = tk.IntVar(value=DEFAULT_CA_DAYS)
        self.var_ca_bits = tk.IntVar(value=DEFAULT_KEY_BITS)

        # 서버 탭 변수
        host = socket.gethostname() or "localhost"
        ips = detect_local_ips()
        self.var_srv_cn = tk.StringVar(value=host)
        self.var_srv_org = tk.StringVar(value="CleverSearch Demo")
        self.var_srv_country = tk.StringVar(value="KR")
        self.var_srv_dns = tk.StringVar(value=", ".join(sorted({host, "localhost"})))
        self.var_srv_ips = tk.StringVar(value=", ".join(ips))
        self.var_srv_days = tk.IntVar(value=DEFAULT_SERVER_DAYS)
        self.var_srv_bits = tk.IntVar(value=DEFAULT_KEY_BITS)
        self.var_srv_outdir = tk.StringVar(value=str(default_server_outdir()))
        self.var_srv_basename = tk.StringVar(value="demo")
        self.var_srv_pfx = tk.BooleanVar(value=False)
        self.var_srv_pfx_pw = tk.StringVar(value="")

        self._build_ui()
        # 시작 시 사용 안내를 로그에 자동 표시
        self.root.after(50, self._print_welcome)

    def _print_welcome(self) -> None:
        is_admin = self._is_admin()
        admin_msg = "✅ 관리자 권한" if is_admin else "⚠ 일반 권한 — exe 우클릭 → '관리자 권한으로 실행' 권장"
        srv_dir = self.var_srv_outdir.get()
        prefix = self.var_srv_basename.get()
        lines = [
            "═" * 80,
            "  CleverSearchCertGen — 로컬 CA + 서버 인증서 발급기",
            "═" * 80,
            f"[권한] {admin_msg}",
            "",
            "[사용법] 위 [🚀 원클릭 실행] 버튼 1번 → 끝.",
            "         ① Root CA 생성 → ② PC 신뢰 등록 → ③ 서버 인증서 발급",
            "",
            "[기본 폴더]",
            f"  · CA   : {self.var_ca_dir.get()}",
            f"  · 서버 : {srv_dir}",
            "",
            "[주의] rootCA.* 는 uvicorn 에 사용 금지. 서버용은 demo.crt/demo.key 만.",
            "       발급 후 uvicorn 재시작 + 브라우저 완전 종료 후 재실행 필요.",
            "═" * 80,
            "",
        ]
        for line in lines:
            self._log(line)

    @staticmethod
    def _is_admin() -> bool:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────
    @property
    def ca_crt_path(self) -> Path:
        return Path(self.var_ca_dir.get()) / "rootCA.crt"

    @property
    def ca_key_path(self) -> Path:
        return Path(self.var_ca_dir.get()) / "rootCA.key"

    # ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        # 루트를 grid 로: row 0(고정), row 1(고정), row 2(탭 — 일부 expand), row 3(상태), row 4(로그 — 모든 잔여 expand)
        self.root.rowconfigure(2, weight=0)
        self.root.rowconfigure(4, weight=1)  # 로그가 모든 잔여 공간 차지
        self.root.columnconfigure(0, weight=1)

        # ── CA 폴더 ─────────────────────────────────────────
        top = ttk.LabelFrame(self.root, text="CA 보관 폴더 (rootCA.* 전용)", padding=8)
        top.grid(row=0, column=0, sticky="we", padx=12, pady=(10, 4))
        ttk.Label(top, text="CA 폴더").grid(row=0, column=0, sticky="w", padx=4)
        ttk.Entry(top, textvariable=self.var_ca_dir).grid(row=0, column=1, sticky="we", padx=4)
        ttk.Button(top, text="...", width=4, command=self._pick_ca_dir).grid(row=0, column=2, padx=2)
        ttk.Label(
            top,
            text="⚠ rootCA.* 는 uvicorn 에 절대 사용하지 마세요. 서버는 탭 ②의 demo.crt/demo.key 만 사용.",
            foreground="#9f1239",
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=4, pady=(2, 0))
        top.columnconfigure(1, weight=1)

        # ── 원클릭 ──────────────────────────────────────────
        oneclick = ttk.LabelFrame(self.root, text="원클릭 (관리자 권한 필요)", padding=8)
        oneclick.grid(row=1, column=0, sticky="we", padx=12, pady=(0, 4))
        ttk.Button(oneclick, text="🚀  원클릭 실행", command=self._on_oneclick).pack(side="left", padx=(0, 6))
        ttk.Button(oneclick, text="서버 폴더 열기", command=self._open_srv_outdir).pack(side="left", padx=2)
        ttk.Button(oneclick, text="CA 폴더 열기", command=self._open_ca_dir).pack(side="left", padx=2)
        ttk.Button(oneclick, text="로그 지우기", command=self._clear_log).pack(side="left", padx=2)

        # ── 탭 ─────────────────────────────────────────────
        nb = ttk.Notebook(self.root)
        nb.grid(row=2, column=0, sticky="we", padx=12, pady=(0, 4))
        self._build_tab_ca(nb)
        self._build_tab_server(nb)

        # ── 상태 표시 ──────────────────────────────────────
        ttk.Label(self.root, textvariable=self.var_status, foreground="#444").grid(
            row=3, column=0, sticky="w", padx=14, pady=(0, 2)
        )

        # ── 로그 (잔여 공간 모두 차지) ─────────────────────
        logf = ttk.LabelFrame(self.root, text="진행 로그 / 사용 명령", padding=6)
        logf.grid(row=4, column=0, sticky="nsew", padx=12, pady=(0, 10))
        logf.rowconfigure(0, weight=1)
        logf.columnconfigure(0, weight=1)
        self.txt = tk.Text(
            logf, wrap="none", state="normal",
            font=("Consolas", 10), background="#fafafa", relief="flat", borderwidth=1,
        )
        self.txt.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(logf, command=self.txt.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.txt.config(yscrollcommand=sb.set)
        self.txt.bind("<Key>", lambda e: "break" if e.keysym not in ("c", "C") and not (e.state & 0x4) else None)
        self.txt.bind("<Control-c>", lambda e: None)
        self.txt.bind("<Control-C>", lambda e: None)

    # ──────────────────────────────────────────────────────────
    def _build_tab_ca(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=8)
        nb.add(f, text="① Root CA")

        # 한 행에 CN/O/C, 두 번째 행에 유효기간/키
        ttk.Label(f, text="CN").grid(row=0, column=0, sticky="w", padx=2)
        ttk.Entry(f, textvariable=self.var_ca_cn, width=30).grid(row=0, column=1, sticky="we", padx=2)
        ttk.Label(f, text="O").grid(row=0, column=2, sticky="w", padx=(8, 2))
        ttk.Entry(f, textvariable=self.var_ca_org, width=22).grid(row=0, column=3, sticky="we", padx=2)
        ttk.Label(f, text="C").grid(row=0, column=4, sticky="w", padx=(8, 2))
        ttk.Entry(f, textvariable=self.var_ca_country, width=4).grid(row=0, column=5, sticky="w", padx=2)

        ttk.Label(f, text="유효기간(일)").grid(row=1, column=0, sticky="w", padx=2, pady=(6, 0))
        ttk.Spinbox(f, from_=30, to=7300, textvariable=self.var_ca_days, width=8).grid(row=1, column=1, sticky="w", padx=2, pady=(6, 0))
        ttk.Label(f, text="키 길이(bit)").grid(row=1, column=2, sticky="w", padx=(8, 2), pady=(6, 0))
        ttk.Combobox(f, values=list(KEY_BIT_OPTIONS), textvariable=self.var_ca_bits, width=8, state="readonly").grid(
            row=1, column=3, sticky="w", padx=2, pady=(6, 0)
        )
        f.columnconfigure(1, weight=1)
        f.columnconfigure(3, weight=1)

    # ──────────────────────────────────────────────────────────
    def _build_tab_server(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=8)
        nb.add(f, text="② 서버 인증서")

        # 1행 — CN/O/C
        ttk.Label(f, text="CN").grid(row=0, column=0, sticky="w", padx=2)
        ttk.Entry(f, textvariable=self.var_srv_cn, width=24).grid(row=0, column=1, sticky="we", padx=2)
        ttk.Label(f, text="O").grid(row=0, column=2, sticky="w", padx=(8, 2))
        ttk.Entry(f, textvariable=self.var_srv_org, width=22).grid(row=0, column=3, sticky="we", padx=2)
        ttk.Label(f, text="C").grid(row=0, column=4, sticky="w", padx=(8, 2))
        ttk.Entry(f, textvariable=self.var_srv_country, width=4).grid(row=0, column=5, sticky="w", padx=2)

        # 2행 — DNS SAN + 자동 버튼
        ttk.Label(f, text="DNS").grid(row=1, column=0, sticky="w", padx=2, pady=(6, 0))
        ttk.Entry(f, textvariable=self.var_srv_dns).grid(row=1, column=1, columnspan=4, sticky="we", padx=2, pady=(6, 0))
        ttk.Button(f, text="hostname", width=10, command=self._fill_default_dns).grid(row=1, column=5, sticky="w", padx=2, pady=(6, 0))

        # 3행 — IP SAN + 자동 버튼
        ttk.Label(f, text="IP").grid(row=2, column=0, sticky="w", padx=2, pady=(4, 0))
        ttk.Entry(f, textvariable=self.var_srv_ips).grid(row=2, column=1, columnspan=4, sticky="we", padx=2, pady=(4, 0))
        ttk.Button(f, text="로컬IP", width=10, command=self._fill_default_ips).grid(row=2, column=5, sticky="w", padx=2, pady=(4, 0))

        # 4행 — 유효기간/키/prefix
        ttk.Label(f, text="유효기간(일)").grid(row=3, column=0, sticky="w", padx=2, pady=(6, 0))
        ttk.Spinbox(f, from_=1, to=3650, textvariable=self.var_srv_days, width=8).grid(row=3, column=1, sticky="w", padx=2, pady=(6, 0))
        ttk.Label(f, text="키(bit)").grid(row=3, column=2, sticky="w", padx=(8, 2), pady=(6, 0))
        ttk.Combobox(f, values=list(KEY_BIT_OPTIONS), textvariable=self.var_srv_bits, width=8, state="readonly").grid(
            row=3, column=3, sticky="w", padx=2, pady=(6, 0)
        )
        ttk.Label(f, text="prefix").grid(row=3, column=4, sticky="w", padx=(8, 2), pady=(6, 0))
        ttk.Entry(f, textvariable=self.var_srv_basename, width=14).grid(row=3, column=5, sticky="w", padx=2, pady=(6, 0))

        # 5행 — 저장 위치
        ttk.Label(f, text="저장 폴더").grid(row=4, column=0, sticky="w", padx=2, pady=(6, 0))
        ttk.Entry(f, textvariable=self.var_srv_outdir).grid(row=4, column=1, columnspan=4, sticky="we", padx=2, pady=(6, 0))
        ttk.Button(f, text="...", width=4, command=self._pick_srv_outdir).grid(row=4, column=5, sticky="w", padx=2, pady=(6, 0))

        # 6행 — PFX 옵션
        ttk.Checkbutton(f, text="PKCS#12(.pfx) 함께 발급", variable=self.var_srv_pfx, command=self._toggle_pfx).grid(
            row=5, column=0, columnspan=2, sticky="w", padx=2, pady=(6, 0)
        )
        self.lbl_pfx_pw = ttk.Label(f, text="PFX 비밀번호")
        self.lbl_pfx_pw.grid(row=5, column=2, sticky="w", padx=(8, 2), pady=(6, 0))
        self.ent_pfx_pw = ttk.Entry(f, textvariable=self.var_srv_pfx_pw, show="*", width=18)
        self.ent_pfx_pw.grid(row=5, column=3, columnspan=3, sticky="we", padx=2, pady=(6, 0))
        self._toggle_pfx()

        f.columnconfigure(1, weight=1)
        f.columnconfigure(3, weight=1)

    # ──────────────────────────────────────────────────────────
    # 공통 핸들러
    # ──────────────────────────────────────────────────────────
    def _pick_ca_dir(self) -> None:
        d = filedialog.askdirectory(title="CA 저장 폴더 선택", initialdir=self.var_ca_dir.get())
        if d:
            self.var_ca_dir.set(d)

    def _open_ca_dir(self) -> None:
        try:
            Path(self.var_ca_dir.get()).mkdir(parents=True, exist_ok=True)
            os.startfile(self.var_ca_dir.get())  # type: ignore[attr-defined]
        except Exception as e:
            messagebox.showwarning("열기 실패", str(e))

    def _pick_srv_outdir(self) -> None:
        d = filedialog.askdirectory(title="서버 인증서 저장 폴더 선택", initialdir=self.var_srv_outdir.get())
        if d:
            self.var_srv_outdir.set(d)

    def _open_srv_outdir(self) -> None:
        try:
            os.startfile(self.var_srv_outdir.get())  # type: ignore[attr-defined]
        except Exception as e:
            messagebox.showwarning("열기 실패", str(e))

    def _fill_default_dns(self) -> None:
        h = socket.gethostname() or "localhost"
        cur = {x.strip() for x in self.var_srv_dns.get().split(",") if x.strip()}
        cur.update({h, "localhost"})
        self.var_srv_dns.set(", ".join(sorted(cur)))

    def _fill_default_ips(self) -> None:
        cur = {x.strip() for x in self.var_srv_ips.get().split(",") if x.strip()}
        cur.update(detect_local_ips())
        self.var_srv_ips.set(", ".join(sorted(cur)))

    def _toggle_pfx(self) -> None:
        state = "normal" if self.var_srv_pfx.get() else "disabled"
        self.lbl_pfx_pw.configure(state=state)
        self.ent_pfx_pw.configure(state=state)

    def _log(self, msg: str) -> None:
        self.txt.insert("end", msg + "\n")
        self.txt.see("end")

    def _clear_log(self) -> None:
        self.txt.delete("1.0", "end")
        self._print_welcome()

    def _set_status(self, text: str) -> None:
        self.var_status.set(text)

    def _bg(self, fn) -> None:
        threading.Thread(target=fn, daemon=True).start()

    # ──────────────────────────────────────────────────────────
    # 원클릭 — 전 과정 자동
    # ──────────────────────────────────────────────────────────
    def _on_oneclick(self) -> None:
        # CA 폴더와 서버 인증서 폴더가 같으면 절대 진행하지 않음 (rootCA 와 demo 가 섞이는 사고 차단)
        try:
            ca_dir = Path(self.var_ca_dir.get()).expanduser().resolve()
            srv_dir = Path(self.var_srv_outdir.get()).expanduser().resolve()
        except Exception as e:
            messagebox.showerror("실패", f"폴더 경로 오류: {e}")
            return
        if ca_dir == srv_dir:
            messagebox.showerror(
                "폴더 충돌",
                f"CA 폴더와 서버 인증서 폴더가 동일합니다:\n{ca_dir}\n\n"
                "CA(rootCA.*) 와 서버 인증서(demo.*) 는 서로 다른 폴더에 두세요.\n"
                "권장:\n"
                f"  - CA 폴더 : {default_ca_dir()}\n"
                f"  - 서버 폴더: {default_server_outdir()}"
            )
            return
        self._set_status("원클릭 실행 중...")
        self._bg(self._run_oneclick)

    def _run_oneclick(self) -> None:
        try:
            # 1) CA 준비 — 없으면 생성, 있으면 재사용
            if self.ca_crt_path.exists() and self.ca_key_path.exists():
                self._log(f"[1/3] 기존 CA 재사용: {self.ca_crt_path}")
            else:
                self._log("[1/3] Root CA 생성")
                cert, key = build_root_ca(
                    common_name=self.var_ca_cn.get().strip() or "CleverSearch Local Dev CA",
                    organization=self.var_ca_org.get().strip() or "CleverSearch Local",
                    country=self.var_ca_country.get().strip(),
                    days=int(self.var_ca_days.get()),
                    key_bits=int(self.var_ca_bits.get()),
                )
                write_pem(self.ca_crt_path, cert.public_bytes(serialization.Encoding.PEM))
                write_pem(
                    self.ca_key_path,
                    key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    ),
                    secret=True,
                )
                self._log(f"      CA 저장: {self.ca_crt_path}")

            # 2) 신뢰 등록 — 멱등 (이미 등록된 경우 certutil 이 success 처리)
            self._log("[2/3] PC 신뢰 저장소 등록 (certutil)")
            ok, msg = trust_install_windows(self.ca_crt_path)
            if ok:
                self._log("      OK")
            else:
                self._log("      [WARN] 등록 실패 — 관리자 권한이 아닐 수 있습니다. 다음 단계는 계속 진행.")
                self._log(f"      {msg[:300]}")

            # 3) 서버 인증서 발급
            self._log("[3/3] 서버 인증서 발급")
            cn = self.var_srv_cn.get().strip()
            if not cn:
                raise ValueError("CN 이 비어 있습니다 (탭 ②에서 확인)")
            outdir = Path(self.var_srv_outdir.get() or ".").expanduser().resolve()
            outdir.mkdir(parents=True, exist_ok=True)
            prefix = (self.var_srv_basename.get() or "demo").strip() or "demo"

            dns_names = [d.strip() for d in self.var_srv_dns.get().split(",") if d.strip()]
            ip_strs = [i.strip() for i in self.var_srv_ips.get().split(",") if i.strip()]
            ip_objs: list = []
            for ip in ip_strs:
                try:
                    ip_objs.append(ipaddress.ip_address(ip))
                except ValueError:
                    raise ValueError(f"잘못된 IP: {ip!r}")

            ca_cert, ca_key = load_ca(self.ca_crt_path, self.ca_key_path)
            cert, pkey = build_server_cert(
                ca_cert=ca_cert,
                ca_key=ca_key,
                common_name=cn,
                organization=self.var_srv_org.get().strip() or "CleverSearch Demo",
                country=self.var_srv_country.get().strip() or "KR",
                dns_names=dns_names,
                ip_objs=ip_objs,
                days=int(self.var_srv_days.get()),
                key_bits=int(self.var_srv_bits.get()),
            )

            crt_path = outdir / f"{prefix}.crt"
            key_path = outdir / f"{prefix}.key"
            full_path = outdir / f"{prefix}.fullchain.pem"
            crt_bytes = cert.public_bytes(serialization.Encoding.PEM)
            ca_bytes = ca_cert.public_bytes(serialization.Encoding.PEM)
            key_bytes = pkey.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            write_pem(crt_path, crt_bytes)
            write_pem(key_path, key_bytes, secret=True)
            write_pem(full_path, crt_bytes + ca_bytes)
            self._log(f"      [OK] {crt_path}")
            self._log(f"      [OK] {key_path}")
            self._log(f"      [OK] {full_path}")

            if self.var_srv_pfx.get():
                pw = (self.var_srv_pfx_pw.get() or "").encode("utf-8")
                algo = serialization.BestAvailableEncryption(pw) if pw else serialization.NoEncryption()
                pfx_bytes = pkcs12.serialize_key_and_certificates(
                    name=cn.encode("utf-8"),
                    key=pkey, cert=cert, cas=[ca_cert],
                    encryption_algorithm=algo,
                )
                pfx_path = outdir / f"{prefix}.pfx"
                pfx_path.write_bytes(pfx_bytes)
                self._log(f"      [OK] {pfx_path} (PFX)")

            self._log("")
            self._log("=" * 70)
            self._log("  ✅ 발급 완료 — 아래 두 줄을 그대로 복사해서 uvicorn 명령에 붙이세요")
            self._log("=" * 70)
            self._log("")
            self._log(f'  --ssl-certfile="{crt_path}"')
            self._log(f'  --ssl-keyfile="{key_path}"')
            self._log("")
            self._log("[전체 예시]")
            self._log(
                f'  python -m uvicorn app.main:app --reload '
                f'--ssl-certfile="{crt_path}" --ssl-keyfile="{key_path}"'
            )
            self._log("")
            self._log("[다음 할 일]")
            self._log("  1) 위 명령으로 uvicorn 재시작 (기존 서버는 종료 후)")
            self._log("  2) 크롬 완전 종료 → 재실행 → https://localhost:8000 접속")
            self._log("  3) 자물쇠 정상 표시 확인")
            self._log("=" * 70)
            self._set_status("원클릭 완료")
            messagebox.showinfo(
                "완료",
                "전체 자동 실행이 끝났습니다.\n"
                f"- CA: {self.ca_crt_path}\n"
                f"- 서버 인증서: {crt_path}\n"
                "브라우저 재시작 후 자물쇠 정상 표시됩니다.\n"
                "(신뢰 등록 단계가 실패했다면 관리자 권한으로 다시 실행하세요.)"
            )
        except Exception as exc:
            self._log(f"[ERROR] {exc}")
            self._log(traceback.format_exc())
            self._set_status("실패")
            messagebox.showerror("실패", str(exc))

    # ──────────────────────────────────────────────────────────
    # CA 핸들러
    # ──────────────────────────────────────────────────────────
    def _on_create_ca(self) -> None:
        if self.ca_crt_path.exists():
            if not messagebox.askyesno("확인", f"이미 CA 가 존재합니다:\n{self.ca_crt_path}\n덮어쓰시겠습니까?\n(이미 신뢰 등록된 기존 CA 가 있다면 먼저 '제거' 권장)"):
                return
        self._set_status("CA 생성 중...")
        self._bg(self._create_ca)

    def _create_ca(self) -> None:
        try:
            cert, key = build_root_ca(
                common_name=self.var_ca_cn.get().strip() or "CleverSearch Local Dev CA",
                organization=self.var_ca_org.get().strip() or "CleverSearch Local",
                country=self.var_ca_country.get().strip(),
                days=int(self.var_ca_days.get()),
                key_bits=int(self.var_ca_bits.get()),
            )
            write_pem(self.ca_crt_path, cert.public_bytes(serialization.Encoding.PEM))
            write_pem(
                self.ca_key_path,
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                ),
                secret=True,
            )
            self._log(f"[OK] Root CA 생성: {self.ca_crt_path}")
            self._log(f"[OK]                {self.ca_key_path}")
            self._log(f"[INFO] Thumbprint(SHA1): {cert_thumbprint_sha1(cert)}")
            self._log("→ 이제 ②번 '신뢰 저장소에 등록' 을 눌러 CA 를 PC 에 신뢰 등록하세요. (관리자 권한 필요)")
            self._set_status("CA 생성 완료")
        except Exception as exc:
            self._log(f"[ERROR] {exc}")
            self._log(traceback.format_exc())
            self._set_status("실패")
            messagebox.showerror("실패", str(exc))

    def _on_install_ca(self) -> None:
        if not self.ca_crt_path.exists():
            messagebox.showwarning("CA 없음", "먼저 ①번 'Root CA 생성' 을 실행하세요.")
            return
        self._set_status("CA 신뢰 등록 중...")
        self._bg(self._install_ca)

    def _install_ca(self) -> None:
        ok, msg = trust_install_windows(self.ca_crt_path)
        if ok:
            self._log("[OK] PC 신뢰 저장소(Root)에 CA 등록됨")
            self._log(msg)
            self._set_status("신뢰 등록 완료")
            messagebox.showinfo(
                "완료",
                "PC 신뢰 저장소에 CA 가 등록되었습니다.\n"
                "이 CA 가 발급한 서버 인증서는 이제 브라우저 경고 없이 신뢰됩니다.\n"
                "브라우저는 재시작해야 인식합니다."
            )
        else:
            self._log("[FAIL] CA 등록 실패")
            self._log(msg)
            self._set_status("등록 실패")
            messagebox.showerror(
                "실패",
                "관리자 권한이 필요합니다.\n"
                "이 프로그램을 '관리자 권한으로 실행' 한 뒤 다시 시도하세요.\n\n"
                f"세부:\n{msg[:600]}"
            )

    def _on_uninstall_ca(self) -> None:
        if not self.ca_crt_path.exists():
            messagebox.showwarning("CA 없음", "현재 폴더에 rootCA.crt 가 없습니다.")
            return
        try:
            cert = x509.load_pem_x509_certificate(self.ca_crt_path.read_bytes())
            tp = cert_thumbprint_sha1(cert)
        except Exception as e:
            messagebox.showerror("실패", f"CA 로드 실패: {e}")
            return
        if not messagebox.askyesno("확인", f"PC 신뢰 저장소에서 다음 thumbprint 의 CA 를 제거합니다:\n{tp}\n계속할까요?"):
            return
        self._set_status("CA 제거 중...")
        self._bg(lambda: self._uninstall_ca(tp))

    def _uninstall_ca(self, thumbprint: str) -> None:
        ok, msg = trust_uninstall_windows(thumbprint)
        if ok:
            self._log("[OK] PC 신뢰 저장소에서 CA 제거됨")
            self._log(msg)
            self._set_status("제거 완료")
        else:
            self._log("[FAIL] 제거 실패")
            self._log(msg)
            self._set_status("실패")
            messagebox.showerror("실패", f"관리자 권한 필요.\n\n{msg[:600]}")

    def _on_show_ca_info(self) -> None:
        if not self.ca_crt_path.exists():
            self._log("[INFO] CA 없음 — 먼저 생성하세요.")
            return
        try:
            cert = x509.load_pem_x509_certificate(self.ca_crt_path.read_bytes())
        except Exception as e:
            self._log(f"[ERROR] CA 로드 실패: {e}")
            return
        self._log("=== Root CA 정보 ===")
        self._log(f"  Path     : {self.ca_crt_path}")
        self._log(f"  Subject  : {cert.subject.rfc4514_string()}")
        self._log(f"  NotBefore: {cert.not_valid_before_utc}")
        self._log(f"  NotAfter : {cert.not_valid_after_utc}")
        self._log(f"  SHA1     : {cert_thumbprint_sha1(cert)}")

    # ──────────────────────────────────────────────────────────
    # 서버 인증서 핸들러
    # ──────────────────────────────────────────────────────────
    def _on_issue_server(self) -> None:
        if not (self.ca_crt_path.exists() and self.ca_key_path.exists()):
            messagebox.showwarning("CA 없음", "먼저 ①번 탭에서 Root CA 를 생성하세요.")
            return
        # 폴더 충돌 차단
        try:
            ca_dir = Path(self.var_ca_dir.get()).expanduser().resolve()
            srv_dir = Path(self.var_srv_outdir.get()).expanduser().resolve()
        except Exception as e:
            messagebox.showerror("실패", f"폴더 경로 오류: {e}")
            return
        if ca_dir == srv_dir:
            messagebox.showerror(
                "폴더 충돌",
                f"CA 폴더와 서버 인증서 폴더가 동일합니다:\n{ca_dir}\n\n"
                "CA(rootCA.*) 와 서버 인증서(demo.*) 는 서로 다른 폴더에 두세요."
            )
            return
        self._set_status("서버 인증서 발급 중...")
        self._bg(self._issue_server)

    def _issue_server(self) -> None:
        try:
            cn = self.var_srv_cn.get().strip()
            if not cn:
                raise ValueError("CN 은 필수입니다")
            outdir = Path(self.var_srv_outdir.get() or ".").expanduser().resolve()
            outdir.mkdir(parents=True, exist_ok=True)
            prefix = (self.var_srv_basename.get() or "demo").strip() or "demo"

            dns_names = [d.strip() for d in self.var_srv_dns.get().split(",") if d.strip()]
            ip_strs = [i.strip() for i in self.var_srv_ips.get().split(",") if i.strip()]
            ip_objs: list = []
            for ip in ip_strs:
                try:
                    ip_objs.append(ipaddress.ip_address(ip))
                except ValueError:
                    raise ValueError(f"잘못된 IP: {ip!r}")

            ca_cert, ca_key = load_ca(self.ca_crt_path, self.ca_key_path)
            self._log(f"[INFO] CA Issuer: {ca_cert.subject.rfc4514_string()}")

            cert, pkey = build_server_cert(
                ca_cert=ca_cert,
                ca_key=ca_key,
                common_name=cn,
                organization=self.var_srv_org.get().strip() or "CleverSearch Demo",
                country=self.var_srv_country.get().strip() or "KR",
                dns_names=dns_names,
                ip_objs=ip_objs,
                days=int(self.var_srv_days.get()),
                key_bits=int(self.var_srv_bits.get()),
            )

            crt_path = outdir / f"{prefix}.crt"
            key_path = outdir / f"{prefix}.key"
            full_path = outdir / f"{prefix}.fullchain.pem"

            crt_bytes = cert.public_bytes(serialization.Encoding.PEM)
            ca_bytes = ca_cert.public_bytes(serialization.Encoding.PEM)
            key_bytes = pkey.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            write_pem(crt_path, crt_bytes)
            write_pem(key_path, key_bytes, secret=True)
            write_pem(full_path, crt_bytes + ca_bytes)

            self._log(f"[OK] {crt_path}")
            self._log(f"[OK] {key_path}")
            self._log(f"[OK] {full_path}  (서버 + CA 체인)")

            if self.var_srv_pfx.get():
                pw = (self.var_srv_pfx_pw.get() or "").encode("utf-8")
                algo = serialization.BestAvailableEncryption(pw) if pw else serialization.NoEncryption()
                pfx_bytes = pkcs12.serialize_key_and_certificates(
                    name=cn.encode("utf-8"),
                    key=pkey, cert=cert, cas=[ca_cert],
                    encryption_algorithm=algo,
                )
                pfx_path = outdir / f"{prefix}.pfx"
                pfx_path.write_bytes(pfx_bytes)
                self._log(f"[OK] {pfx_path} (PFX, CA 포함)")

            self._log("")
            self._log("== uvicorn 사용 예시 ==")
            self._log(f'  uvicorn ... --ssl-certfile "{crt_path}" --ssl-keyfile "{key_path}"')
            self._log("CA 가 PC 신뢰 저장소에 등록되어 있다면 브라우저 경고 없이 자물쇠 표시.")

            self._set_status("발급 완료")
            messagebox.showinfo("완료", f"서버 인증서가 발급되었습니다:\n{outdir}")
        except Exception as exc:
            self._log(f"[ERROR] {exc}")
            self._log(traceback.format_exc())
            self._set_status("실패")
            messagebox.showerror("실패", str(exc))


def main() -> None:
    root = tk.Tk()
    CertGenApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
