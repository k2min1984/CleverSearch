import io
import os
import uuid
import zipfile

import olefile
from fastapi import HTTPException, UploadFile


try:
    import magic  # type: ignore
except Exception:  # pragma: no cover
    magic = None


MAX_UPLOAD_SIZE = 30 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024

ZIP_EXPECTED_PREFIX = {
    "docx": "word/",
    "pptx": "ppt/",
    "xlsx": "xl/",
    "hwpx": "Contents/",
}


def build_safe_filenames(raw_filename: str | None) -> tuple[str, str, str]:
    name = (raw_filename or "").replace("\x00", "")
    base = os.path.basename(name).strip()
    if not base:
        raise HTTPException(status_code=400, detail="유효하지 않은 파일명입니다")

    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
    if not ext:
        raise HTTPException(status_code=400, detail="파일 확장자를 확인할 수 없습니다")

    # 저장 경로 키는 사용자 입력과 분리하여 난수 기반으로 생성
    storage_filename = f"{uuid.uuid4().hex}.{ext}"
    return base, storage_filename, ext


async def read_upload_limited(file: UploadFile, max_size: int = MAX_UPLOAD_SIZE) -> bytes:
    total = 0
    chunks: list[bytes] = []

    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"파일 크기 초과: 최대 {max_size // 1024 // 1024}MB 허용",
            )
        chunks.append(chunk)

    return b"".join(chunks)


def _mime_looks_dangerous(content: bytes) -> bool:
    if magic is None:
        return False
    try:
        detected = (magic.from_buffer(content, mime=True) or "").lower()
    except Exception:
        return False

    blocked = (
        "application/x-dosexec",
        "application/x-msdownload",
        "application/x-executable",
        "application/x-elf",
        "application/x-mach-binary",
    )
    return any(detected.startswith(prefix) for prefix in blocked)


def _is_valid_zip_family(ext: str, content: bytes) -> bool:
    if not zipfile.is_zipfile(io.BytesIO(content)):
        return False

    expected_prefix = ZIP_EXPECTED_PREFIX.get(ext, "")
    if not expected_prefix:
        return False

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            return any(name.startswith(expected_prefix) for name in names)
    except Exception:
        return False


def _is_valid_ole_hwp(content: bytes) -> bool:
    bio = io.BytesIO(content)
    if not olefile.isOleFile(bio):
        return False
    try:
        ole = olefile.OleFileIO(io.BytesIO(content))
        streams = {"/".join(path) for path in ole.listdir()}
        ole.close()
        has_file_header = "FileHeader" in streams
        has_body = any(s.startswith("BodyText/Section") for s in streams)
        return has_file_header and has_body
    except Exception:
        return False


def _is_valid_ole_xls(content: bytes) -> bool:
    bio = io.BytesIO(content)
    if not olefile.isOleFile(bio):
        return False
    try:
        ole = olefile.OleFileIO(io.BytesIO(content))
        streams = {"/".join(path) for path in ole.listdir()}
        ole.close()
        return "Workbook" in streams or "Book" in streams
    except Exception:
        return False


def validate_signature(ext: str, content: bytes) -> None:
    ext = (ext or "").lower()

    if _mime_looks_dangerous(content):
        raise HTTPException(status_code=400, detail="허용되지 않는 파일 형식입니다")

    if ext == "pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="파일 시그니처 불일치: PDF가 아닙니다")
        return

    if ext in {"jpg", "jpeg"}:
        if not content.startswith(b"\xff\xd8\xff"):
            raise HTTPException(status_code=400, detail="파일 시그니처 불일치: JPEG가 아닙니다")
        return

    if ext == "png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(status_code=400, detail="파일 시그니처 불일치: PNG가 아닙니다")
        return

    if ext in {"docx", "pptx", "xlsx", "hwpx"}:
        if not _is_valid_zip_family(ext, content):
            raise HTTPException(status_code=400, detail=f"파일 시그니처 불일치: {ext.upper()}가 아닙니다")
        return

    if ext == "hwp":
        if not _is_valid_ole_hwp(content):
            raise HTTPException(status_code=400, detail="파일 시그니처 불일치: HWP가 아닙니다")
        return

    if ext == "xls":
        if not _is_valid_ole_xls(content):
            raise HTTPException(status_code=400, detail="파일 시그니처 불일치: XLS가 아닙니다")
        return

    raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다")
