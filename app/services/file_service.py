"""
########################################################
# Description
# 파일 처리 비즈니스 로직 서비스
# - PDF 텍스트 추출 (PyMuPDF 활용)
# - 추후 OCR 및 이미지 처리 확장 공간
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""

import fitz  # PyMuPDF 라이브러리

class FileService:
    """
    파일 파싱 및 데이터 추출을 담당하는 서비스 클래스입니다.
    """
    
    @staticmethod
    async def extract_text_from_pdf(file_content: bytes) -> str:
        """
        PDF 바이너리 데이터에서 순수 텍스트만 추출합니다.
        
        Args:
            file_content (bytes): 업로드된 PDF 파일의 바이너리 데이터
            
        Returns:
            str: 추출된 전체 텍스트
        """
        # 메모리 상의 바이트 스트림을 PDF 문서 객체로 로드
        doc = fitz.open(stream=file_content, filetype="pdf")
        
        text = ""
        # 페이지별로 순회하며 텍스트 추출
        for page in doc:
            text += page.get_text()
            
        return text