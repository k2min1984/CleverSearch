"""
########################################################
# Description
# Office 파일 파서 (Word / PowerPoint)
# DOCX, PPTX 문서에서 본문 텍스트 추출
# - Word: python-docx → 문단(paragraph) 추출
# - PowerPoint: python-pptx → 슬라이드/셀 텍스트 추출
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""
import io
from docx import Document
from pptx import Presentation

def parse_word(content: bytes) -> str:
    try:
        doc = Document(io.BytesIO(content))
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        return f"Word 파싱 에러: {str(e)}"

def parse_pptx(content: bytes) -> str:
    try:
        prs = Presentation(io.BytesIO(content))
        text = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text.append(shape.text)
        return "\n".join(text)
    except Exception as e:
        return f"PPT 파싱 에러: {str(e)}"