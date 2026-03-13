import io
import fitz
from PIL import Image
from app.utils import ocr, string

# [PDF] 추출
def _extract_text(content: bytes) -> str:
    """
    [PDF 핸들러 메인 함수]
    1. 텍스트/이미지 PDF 판별
    2. 추출 (Text Direct or OCR)
    3. 페이지별 마커([[Page N]]) 삽입 및 RAG 전처리
    """
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        extracted_text_list = []
        
        # 1. 스캔본 여부 확인
        is_scanned = _is_scanned_pdf(doc)
        
        if is_scanned:
            print("[PDF] 스캔본 감지 -> OCR 모드 실행")
            images = _pdf_to_images(doc)
            
            for i, img in enumerate(images):
                # 페이지 마커 추가 (검색 시 위치 추적용)
                page_header = f"[[Page {i+1}]]"
                # ocr.py 호출
                page_text = ocr._extract_text(img, i, is_pdf_page=True)
                extracted_text_list.append(f"{page_header}\n{page_text}")
        else:
            print("[PDF] 텍스트형 PDF 감지 -> 고속 추출 실행")
            for i, page in enumerate(doc):
                page_header = f"[[Page {i+1}]]"
                # sort=True: 다단 편집 문서 등에서 사람이 읽는 순서대로 텍스트 정렬
                text = page.get_text(sort=True)
                if text.strip():
                    extracted_text_list.append(f"{page_header}\n{text}")
                elif len(page.get_images()) > 0:
                    # 혼합 PDF에서 텍스트 레이어 없는 페이지는 OCR로 보완
                    ocr_img = _page_to_image(page)
                    page_text = ocr._extract_text(ocr_img, i, is_pdf_page=True)
                    extracted_text_list.append(f"{page_header}\n{page_text}")

        full_text = "\n\n".join(extracted_text_list)

        
        # 1차: 시스템 안전 정제
        full_text = string._clean_text(full_text)
        
        return full_text

    except Exception as e:
        return f"[PDF Process Error] {str(e)}"

# [PDF] 스캔본 여부 체크
def _is_scanned_pdf(doc: fitz.Document, check_pages: int = 3) -> bool:
    """
    [판단 로직]
    처음 몇 페이지만 검사하여 스캔본(이미지)인지 텍스트형 PDF인지 판단.
    텍스트 양이 거의 없고 이미지가 있다면 스캔본으로 간주.
    """
    text_count  = 0
    image_count = 0
    
    # 전체 페이지가 check_pages보다 적으면 전체 검사
    pages_to_check = min(len(doc), check_pages)
    if pages_to_check == 0:
        return False
    
    for i in range(pages_to_check):
        page = doc.load_page(i)
        text_count  += len(page.get_text().strip())
        image_count += len(page.get_images())

    # 기준: 페이지당 평균 글자수가 10자 미만이고 이미지가 존재하면 스캔본
    if text_count / pages_to_check < 10 and image_count > 0:
        return True
        
    return False

# [PDF] PDF > 이미지 리스트 변환
def _pdf_to_images(doc: fitz.Document) -> list[Image.Image]:
    images = []
    for page in doc:
        images.append(_page_to_image(page))
    
    return images


def _page_to_image(page: fitz.Page) -> Image.Image:
    # A4 기준 300~330 DPI 수준으로 페이지 long side를 맞춰 OCR 품질을 높인다.
    rect = page.rect
    long_side_pt = max(rect.width, rect.height)
    target_long_side_px = 3600
    zoom = target_long_side_px / long_side_pt if long_side_pt > 0 else (300 / 72)
    zoom = min(max(zoom, 3.5), 5.0)

    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)