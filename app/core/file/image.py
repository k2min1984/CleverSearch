"""
########################################################
# Description
# 이미지 텍스트 추출 파서
# PaddleOCR로 이미지 파일에서 텍스트 추출
# - 지원 포맷: JPG, JPEG, PNG
# - OCR 엔진: PaddleOCR (한국어)
# - 폴백: Tesseract (PaddleOCR 사용 불가 시)
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
# 강광민 / 2026-04-02 / PaddleOCR 전환, Tesseract 폴백 유지
########################################################
"""
import io
import importlib
import logging
import numpy as np
from PIL import Image, UnidentifiedImageError

from app.utils import string

logger = logging.getLogger(__name__)

# ── PaddleOCR 싱글턴 (첫 호출 시 1회만 로드) ──
_paddle_ocr = None


def _get_paddle_ocr():
    global _paddle_ocr
    if _paddle_ocr is None:
        try:
            paddle_module = importlib.import_module("paddleocr")
            PaddleOCR = getattr(paddle_module, "PaddleOCR")
            _paddle_ocr = PaddleOCR(
                use_angle_cls=True,
                lang="korean",
                use_gpu=False,
                show_log=False,
            )
        except Exception:
            _paddle_ocr = False  # 설치 안 됨 → 재시도 방지
    return _paddle_ocr


def _extract_with_paddle(img: Image.Image) -> str:
    """PaddleOCR로 텍스트 추출."""
    ocr = _get_paddle_ocr()
    if not ocr:
        return ""

    img_array = np.array(img.convert("RGB"))
    result = ocr.ocr(img_array, cls=True)

    lines: list[str] = []
    if result and result[0]:
        for line in result[0]:
            text = line[1][0].strip()
            confidence = line[1][1]
            if text and confidence > 0.6:
                lines.append(text)
    return " ".join(lines)


def _extract_with_tesseract(img: Image.Image) -> str:
    """Tesseract OCR 폴백."""
    try:
        import os
        import platform
        import pytesseract
        from PIL import ImageOps, ImageStat

        if platform.system() == "Windows":
            exe = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if os.path.exists(exe):
                pytesseract.pytesseract.tesseract_cmd = exe

        gray = img.convert("L")
        if ImageStat.Stat(gray).mean[0] < 127:
            gray = ImageOps.invert(gray)
        gray = ImageOps.autocontrast(gray)
        if gray.width < 1500:
            gray = gray.resize(
                (gray.width * 2, gray.height * 2), Image.Resampling.LANCZOS
            )
        gray = gray.point(lambda x: 0 if x < 135 else 255, "1")
        gray = ImageOps.expand(gray, border=50, fill="white")

        data = pytesseract.image_to_data(
            gray,
            config=r"--oem 3 --psm 6 -l kor+eng",
            output_type=pytesseract.Output.DICT,
        )
        words = []
        for i in range(len(data["text"])):
            conf = data["conf"][i]
            if conf == "-1":
                continue
            if int(conf) > 60:
                w = data["text"][i].strip()
                if w:
                    words.append(w)
        return " ".join(words)
    except Exception:
        return ""


def extract_text(content: bytes) -> str:
    """
    이미지에서 텍스트 추출.
    PaddleOCR → 결과 없으면 Tesseract 폴백.
    """
    try:
        img = Image.open(io.BytesIO(content))
    except (UnidentifiedImageError, Exception):
        return ""

    # 1차: PaddleOCR
    text = _extract_with_paddle(img)
    if text.strip():
        return string.clean_text(text)

    # 2차: Tesseract 폴백
    text = _extract_with_tesseract(img)
    return string.clean_text(text) if text.strip() else ""