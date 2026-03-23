"""
########################################################
# Description
# PDF 파일 파서
# PDF 페이지별 텍스트 추출
# - 엔진: pypdf
# - 페이지 단위 텍스트 병합 출력
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""
import io
import pypdf

def extract_text(content: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
    except Exception as e:
        return f"PDF 파싱 에러: {str(e)}"