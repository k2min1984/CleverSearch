"""
########################################################
# Description
# 이미지 텍스트 추출 파서
# Tesseract OCR로 이미지 파일에서 텍스트 추출
# - 지원 포맷: JPG, JPEG, PNG
# - OCR 엔진: pytesseract + Pillow
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""
import io
import os
import platform
from PIL import Image, ImageOps, ImageStat, ImageFilter, UnidentifiedImageError
import pytesseract
# import
from app.utils import string

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
    
    정규식(Regex) 필터 대신 Tesseract의 신뢰도(Confidence) 점수를 활용,
    배경 노이즈는 제거하고 의미 있는 짧은 단어('a', '1' 등)는 보존.
    """
    try:
        # 1. 이미지 로드 및 그레이스케일 변환
        image = Image.open(io.BytesIO(content)).convert('L')

        # 2. 다크 모드(Dark Mode) 자동 감지 및 대응
        # 평균 밝기가 127 미만(어두운 배경)인 경우 색상을 반전시켜 인식률 향상
        if ImageStat.Stat(image).mean[0] < 127:
            image = ImageOps.invert(image)       

        # 3. 이미지 전처리 (대비, 해상도, 이진화, 여백)
        image = ImageOps.autocontrast(image) # 대비 강조
        
        # 해상도가 너무 낮으면 인식률이 떨어지므로 2배 확대 (기준: 너비 1500px 미만)
        if image.width < 1500:
            ratio = 2
            image = image.resize((image.width * ratio, image.height * ratio), Image.Resampling.LANCZOS)        
        
        # 이진화 (Threshold 135): 글자는 검게(0), 배경은 희게(255) 변환
        image = image.point(lambda x: 0 if x < 135 else 255, '1')
        
        # 여백 추가: 글자가 테두리에 붙어있으면 인식이 안 되므로 흰색 여백(50px) 추가
        image = ImageOps.expand(image, border=50, fill='white')

        # 4. 데이터 추출 (OCR 실행)
        # --psm 3: 자동으로 페이지 분할 (일반적인 문서)
        # --psm 6: 단일 텍스트 블록 (표나 복잡한 레이아웃이 없을 때 좋음)
        data = pytesseract.image_to_data(image, config=r'--oem 3 --psm 6 -l kor+eng', output_type=pytesseract.Output.DICT)
        
        filtered_text = []
        n_boxes = len(data['text'])     
        
        # 5. 신뢰도(Confidence) 기반 텍스트 필터링
        for i in range(n_boxes):
            conf_val = data['conf'][i]

            # '-1'은 텍스트가 아니라 레이아웃/블록 정보를 의미하므로 건너뜀
            if conf_val == '-1':
                continue

            # 신뢰도 60점 이상인 확실한 단어만 채택 (배경 노이즈 제거)
            if int(conf_val) > 60:
                word = data['text'][i].strip()
                if word:
                    filtered_text.append(word)
        
        # 추출된 단어 결합
        raw_result = " ".join(filtered_text)
        print("[ORC 텍스트 추출]\n",raw_result)
        # 6. 최종 문자열 정제 (특수문자 및 제어문자 정리)
        return string.clean_text(raw_result)

    except UnidentifiedImageError:
        return "에러: 지원하지 않는 이미지 형식이거나 파일이 손상되었습니다."
    except Exception as e:
        return f"OCR 처리 중 오류 발생: {str(e)}"

# [이미지] OCR
def _extract_text_old(content: bytes) -> str:
    try:
        # 1. 이미지 로드
        image = Image.open(io.BytesIO(content))
        
        # 2-1. [전처리] 그레이스케일 변환
        image = image.convert('L')
        
        # 2-2. [전처리] 이미지의 평균 밝기를 구해서 127(중간값)보다 어두우면 반전시킴
        stat = ImageStat.Stat(image)
        avg_brightness = stat.mean[0]
        if avg_brightness < 127:
            # 검은 배경(0) -> 흰 배경(255) / 흰 글씨(255) -> 검은 글씨(0)
            image = ImageOps.invert(image)

        # 2-3. [전처리] 해상도 확대 및 대비 강조
        # 텍스트가 선명해지도록 명암 대비를 최대로 올림
        image = ImageOps.autocontrast(image)

        # 2-4. [전처리] 이미지 크기 조정 (너무 작으면 인식 불가 -> 2배 확대)
        # 텍스트 높이가 최소 30px 이상이어야 인식이 잘 됨
        if image.width < 1500:
            ratio = 2
            image = image.resize((image.width * ratio, image.height * ratio), Image.Resampling.LANCZOS)
        
        # 2-5. [전처리] 노이즈 제거 (약간의 블러로 배경 결을 뭉갬)
        image = image.filter(ImageFilter.SMOOTH_MORE)

        # 2-6. [전처리] 이진화 (Binarization) - 글자는 검게, 배경은 희게
        # 문턱값(Threshold) 128 기준으로 흑/백 분리
        image = image.point(lambda x: 0 if x < 140 else 255, '1')
        
        # 2-7. [전처리] 글자가 테두리에 붙으면 인식이 안 되므로, 사방에 50픽셀 흰색 여백을 줌
        image = ImageOps.expand(image, border=50, fill='white')

        # 3. Tesseract 설정 최적화
        # --psm 3: 자동으로 페이지 분할 (일반적인 문서)
        # --psm 6: 단일 텍스트 블록 (표나 복잡한 레이아웃이 없을 때 좋음)
        # preserve_interword_spaces=1: 단어 간격 유지
        custom_config = r'--oem 3 --psm 6 -l kor+eng'
        
        raw_text = pytesseract.image_to_string(image, config=custom_config)
        print("[ORC 텍스트 추출]\n",raw_text)
        # 4. [후처리] 필터링
        return string.clean_text(raw_text)

    except UnidentifiedImageError:
        return "에러: 지원하지 않는 이미지 형식이거나 파일이 손상되었습니다."
    except Exception as e:
        return f"OCR 처리 중 오류 발생: {str(e)}"

def extract_text(content: bytes) -> str:
    try:
        image = Image.open(io.BytesIO(content))
        # 한글+영어 OCR
        return pytesseract.iㄴmage_to_string(image, lang='kor+eng')
    except Exception as e:
        return f"OCR 에러 (Tesseract 설치 확인 필요): {str(e)}"