"""
########################################################
# Description
# PDF 파일 파서
# PDF 페이지별 텍스트 추출
# - 1차: pdfplumber 텍스트 추출
# - 2차: PyMuPDF(fitz) → Tesseract OCR 폴백 (스캔 PDF 대응)
# - 페이지 단위 [[Page N]] 마커 포함
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
# 강광민 / 2026-04-02 / pdfplumber 통합, fitz OCR 폴백, 에러 반환값 개선
########################################################
"""
import io
import pdfplumber


def _ocr_fallback(content: bytes) -> str:
    """PyMuPDF 로 PDF 페이지를 이미지 변환 후 OCR (PaddleOCR → Tesseract 폴백)."""
    try:
        import fitz
        from app.core.file.image import extract_text as ocr_extract

        pdf_doc = fitz.open(stream=content, filetype="pdf")
        pages: list[str] = []
        for page_num, page in enumerate(pdf_doc):
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            page_text = ocr_extract(img_bytes)
            if page_text and page_text.strip():
                pages.append(f"[[Page {page_num + 1}]]\n{page_text}")
        return "\n\n".join(pages)
    except Exception:
        return ""


def extract_text(content: bytes) -> str:
    """
    PDF 텍스트 추출.
    pdfplumber → 텍스트 없으면 fitz OCR 폴백.
    페이지별 [[Page N]] 마커를 포함하여 반환.
    """
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf_file:
            pages = [
                f"[[Page {i + 1}]]\n{p.extract_text()}"
                for i, p in enumerate(pdf_file.pages)
                if p.extract_text()
            ]
            text = "\n\n".join(pages)

        if not text.strip():
            return _ocr_fallback(content)

        return text
    except Exception:
        return ""