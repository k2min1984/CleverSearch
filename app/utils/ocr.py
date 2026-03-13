import os
import logging
import cv2
import numpy as np
import re
from typing import List, Dict, Any, Tuple
from PIL import Image
from paddleocr import PaddleOCR

# [시스템 환경변수 유지]
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

# -------------------------------------------------------------------
# [1] 엔진 초기화
# -------------------------------------------------------------------
logging.getLogger("ppocr").setLevel(logging.ERROR)
ocr_engine = PaddleOCR(
    use_angle_cls=True,         
    lang='korean',
    ocr_version='PP-OCRv4',
    det_db_box_thresh=0.3,       
    drop_score=0.1,
    show_log=False
)


def _ensure_rgb_array(pil_image: Image.Image) -> np.ndarray:
    img_array = np.array(pil_image)
    if len(img_array.shape) == 2:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_GRAY2RGB)
    elif img_array.shape[2] == 4:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2RGB)
    return img_array


def _resize_for_ocr(image: np.ndarray, is_pdf_page: bool) -> np.ndarray:
    h, w = image.shape[:2]
    long_side = max(h, w)

    # 이미지 PDF는 작은 글자 비율이 높아 long side를 더 크게 맞춘다.
    target_long_side = 3000 if is_pdf_page else 2400
    if long_side >= target_long_side:
        return image

    scale = target_long_side / float(long_side)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

def _deskew(image: np.ndarray) -> np.ndarray:
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        gray = cv2.bitwise_not(gray)
        coords = np.column_stack(np.where(gray > 0))
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45: 
            angle = -(90 + angle)
        else: 
            angle = -angle
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    except Exception:
        return image


def _pdf_enhance_base(image: np.ndarray) -> np.ndarray:
    enhanced = cv2.copyMakeBorder(image, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    enhanced = _deskew(enhanced)

    img_yuv = cv2.cvtColor(enhanced, cv2.COLOR_RGB2YUV)
    img_yuv[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(img_yuv[:, :, 0])
    enhanced = cv2.cvtColor(img_yuv, cv2.COLOR_YUV2RGB)
    return enhanced


def _preprocess_variants(image: np.ndarray, is_pdf_page: bool) -> List[np.ndarray]:
    base = _resize_for_ocr(image, is_pdf_page)
    if is_pdf_page:
        base = _pdf_enhance_base(base)

    variants: List[np.ndarray] = [base]

    gray = cv2.cvtColor(base, cv2.COLOR_RGB2GRAY)

    # Variant 1: 약한 adaptive threshold (저대비 문서 대응)
    adp = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        35,
        11,
    )
    variants.append(cv2.cvtColor(adp, cv2.COLOR_GRAY2RGB))

    # Variant 2: OTSU + median blur (잡음 많은 스캔 대응)
    blur = cv2.medianBlur(gray, 3)
    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(cv2.cvtColor(otsu, cv2.COLOR_GRAY2RGB))

    # Variant 3: 선명화 (흐린 스캔본 대응)
    sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    sharpen = cv2.filter2D(base, -1, sharpen_kernel)
    variants.append(sharpen)

    return variants


def _extract_boxes(image: np.ndarray, use_cls: bool) -> List[Any]:
    result = ocr_engine.ocr(image, cls=use_cls)
    if not result or not result[0]:
        return []

    boxes = result[0]
    boxes.sort(key=lambda x: (int(x[0][0][1] / 15), x[0][0][0]))
    return boxes


def _boxes_to_text(boxes: List[Any], cut_off_score: float) -> Tuple[str, float, int]:
    lines: List[str] = []
    current_line: List[str] = []
    last_y_group = -1

    conf_sum = 0.0
    kept_count = 0

    for box in boxes:
        text = box[1][0].strip()
        conf = float(box[1][1])
        if not text:
            continue
        if conf < cut_off_score:
            continue

        y_group = int(box[0][0][1] / 15)
        if last_y_group == -1 or y_group == last_y_group:
            current_line.append(text)
        else:
            lines.append(" ".join(current_line))
            current_line = [text]

        last_y_group = y_group
        conf_sum += conf
        kept_count += 1

    if current_line:
        lines.append(" ".join(current_line))

    text_out = "\n".join(lines)
    avg_conf = conf_sum / kept_count if kept_count > 0 else 0.0
    return text_out, avg_conf, kept_count


def _select_best_text_basic(candidates: List[Dict[str, Any]]) -> str:
    """
    [기본 선택기]
    OCR 후보들 중 길이/신뢰도/박스 수를 기준으로 최적 텍스트를 선택합니다.
    (일반 이미지 경로에서 사용)
    """
    if not candidates:
        return ""

    # 길이 중심 + 신뢰도 보정으로 최적 결과 선택
    best = max(
        candidates,
        key=lambda c: (len(c["text"]) * 1.0) + (c["avg_conf"] * 80.0) + (c["kept_count"] * 0.5),
    )
    return best["text"]


def _compute_text_quality_metrics(text: str) -> Dict[str, float]:
    """
    [품질 지표 계산]
    텍스트의 기호 과다/문자 비율을 계산해 OCR 노이즈 가능성을 추정합니다.
    """
    if not text:
        return {
            "printable_ratio": 0.0,
            "hangul_alnum_ratio": 0.0,
            "symbol_ratio": 1.0,
        }

    printable_chars = len(re.findall(r"[\u0020-\u007E가-힣ㄱ-ㅎㅏ-ㅣ]", text))
    hangul_alnum_chars = len(re.findall(r"[가-힣ㄱ-ㅎㅏ-ㅣa-zA-Z0-9]", text))
    symbol_chars = len(re.findall(r"[^가-힣ㄱ-ㅎㅏ-ㅣa-zA-Z0-9\s]", text))
    total = max(1, len(text))

    return {
        "printable_ratio": printable_chars / total,
        "hangul_alnum_ratio": hangul_alnum_chars / total,
        "symbol_ratio": symbol_chars / total,
    }


def _score_ocr_candidate(candidate: Dict[str, Any], is_pdf_page: bool) -> float:
    """
    [후보 점수화]
    - 공통: 텍스트 길이 + 평균 신뢰도 + 유효 박스 수
    - PDF 전용: 문자 품질 보정(기호 비율 페널티)
    """
    quality = _compute_text_quality_metrics(candidate["text"])
    base = (len(candidate["text"]) * 1.0) + (candidate["avg_conf"] * 80.0) + (candidate["kept_count"] * 0.5)

    if not is_pdf_page:
        return base

    quality_bonus = (
        (quality["printable_ratio"] * 50.0)
        + (quality["hangul_alnum_ratio"] * 90.0)
        - (quality["symbol_ratio"] * 120.0)
    )
    return base + quality_bonus


def _select_best_candidate(candidates: List[Dict[str, Any]], is_pdf_page: bool) -> Dict[str, Any]:
    """
    [최고 후보 선택]
    점수 함수(_score_ocr_candidate)를 사용해 가장 우수한 OCR 결과를 고릅니다.
    """
    if not candidates:
        return {"text": "", "avg_conf": 0.0, "kept_count": 0}

    return max(candidates, key=lambda c: _score_ocr_candidate(c, is_pdf_page=is_pdf_page))


def _select_pdf_hybrid_output(baseline: Dict[str, Any], best_variant: Dict[str, Any]) -> str:
    """
    [PDF 전용 하이브리드 선택]
    1) 전처리 후보(best_variant)와 원본 1패스(baseline)를 비교
    2) 전처리 결과가 노이즈로 점수 열세면 baseline으로 폴백
    """
    if not best_variant["text"]:
        return baseline["text"]
    if not baseline["text"]:
        return best_variant["text"]

    baseline_score = _score_ocr_candidate(baseline, is_pdf_page=True)
    best_score = _score_ocr_candidate(best_variant, is_pdf_page=True)

    if best_score + 8.0 < baseline_score:
        return baseline["text"]

    return best_variant["text"]

def _extract_text(pil_image: Image.Image, page_no: int, is_pdf_page: bool = False) -> str:
    try:
        img_array = _ensure_rgb_array(pil_image)

        # 이미지 PDF는 저신뢰 박스가 섞여도 유효 텍스트가 많아 컷오프를 조금 낮춘다.
        cut_off_score = 0.50 if is_pdf_page else 0.60

        raw_boxes = _extract_boxes(img_array, use_cls=is_pdf_page)
        raw_text, raw_avg_conf, raw_kept_count = _boxes_to_text(raw_boxes, cut_off_score=cut_off_score)
        baseline_candidate = {
            "text": raw_text,
            "avg_conf": raw_avg_conf,
            "kept_count": raw_kept_count,
        }

        variants = _preprocess_variants(img_array, is_pdf_page=is_pdf_page)
        candidates: List[Dict[str, Any]] = []

        for variant in variants:
            boxes = _extract_boxes(variant, use_cls=is_pdf_page)
            if not boxes:
                continue

            text, avg_conf, kept_count = _boxes_to_text(boxes, cut_off_score=cut_off_score)
            if not text.strip():
                continue

            candidates.append({
                "text": text,
                "avg_conf": avg_conf,
                "kept_count": kept_count,
            })

        if is_pdf_page:
            # PDF는 전처리 결과가 오히려 노이즈를 키울 수 있어 원본 결과와 비교 후 선택
            best_variant = _select_best_candidate(candidates, is_pdf_page=True)
            output = _select_pdf_hybrid_output(baseline_candidate, best_variant)
        else:
            # 일반 이미지 경로는 기존 선택 방식 유지
            output = _select_best_text_basic(candidates)

        print(f"[PaddleOCR RESULT - Page {page_no}]\n{output}")
        
        return output

    except Exception as e:
        print(f"[PaddleOCR Error - Page {page_no}] {e}")
        return ""