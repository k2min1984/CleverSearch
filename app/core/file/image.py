import io
from PIL import Image
import pytesseract

def extract_text(content: bytes) -> str:
    try:
        image = Image.open(io.BytesIO(content))
        # 한글+영어 OCR
        return pytesseract.image_to_string(image, lang='kor+eng')
    except Exception as e:
        return f"OCR 에러 (Tesseract 설치 확인 필요): {str(e)}"