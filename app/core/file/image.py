import io
import os
import platform
from PIL import Image, ImageOps, ImageStat, ImageFilter, UnidentifiedImageError
import pytesseract
# import
from app.utils import string, ocr

# 운영체제별 Tesseract 경로 설정 (Windows 로컬 환경 대응)
if platform.system() == 'Windows':
    # 본인의 실제 설치 경로로 수정 필요
    tesseract_exe = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if os.path.exists(tesseract_exe):
        pytesseract.pytesseract.tesseract_cmd = tesseract_exe
    else:
        print("경고: Tesseract 엔진이 설치되지 않았거나 경로가 잘못되었습니다.")


# [이미지] OCR
def _extract_text(content: bytes) -> str:
    """
    이미지에서 텍스트를 추출. (Tesseract OCR 사용)
    
    [변경] app.utils.ocr 모듈의 고도화된 로직을 사용하여 
    PDF 스캔본과 일반 이미지 파일 모두 동일한 고품질 전처리를 적용합니다.
    """
    try:
        image = Image.open(io.BytesIO(content))
        # 개선된 OCR 모듈 호출 (page_no=0, is_pdf_page=False)
        return ocr._extract_text(image, 0, is_pdf_page=False)

    except UnidentifiedImageError:
        return "에러: 지원하지 않는 이미지 형식이거나 파일이 손상되었습니다."
    except Exception as e:
        return f"OCR 처리 중 오류 발생: {str(e)}"
