"""
########################################################
# Description
# 문자열 정제 유틸리티
# 화이트리스트 기반 한글/영문/숫자만 남기는 필터
# - 깨진 문자 / 제어문자 제거
# - 파일명 정제용 clean_text 함수
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""

# [한글파일] 필터링
def clean_text(text: str) -> str:
    """
    [화이트리스트 필터링]
    한글, 영어, 숫자, 기본 문장부호만 남기고 나머지는 제거합니다.
    제어 문자(Code 31 이하) 및 깨진 문자(Mojibake), 한자 등을 제거하여 
    검색 엔진(OpenSearch) 인덱싱 오류를 원천 차단합니다.
    """
    clean_chars = []
    for char in text:
        code = ord(char)
        
        # 1. 한글 완성형 (가~힣)
        if 0xAC00 <= code <= 0xD7A3:
            clean_chars.append(char)
        
        # 2. 한글 자모 (ㄱ~ㅎ, ㅏ~ㅣ)
        elif 0x3131 <= code <= 0x318E:
            clean_chars.append(char)
        
        # 3. 영어, 숫자, 기본 특수문자 (ASCII 32~126)
        elif 32 <= code <= 126:
            clean_chars.append(char)
        
        # 4. 필수 제어 문자 (탭, 줄바꿈, 캐리지리턴)
        elif code in [9, 10, 13]:
            clean_chars.append(char)
            
        # [참고] 한자(大韓民國)를 살려야 한다면 아래 주석 해제
        # 해당 주석 해제 시 서식 정보(글자 색, 폰트 정보 등)나 제어 코드가 텍스트로 잘못 해석되어 글자 깨짐
        # elif 0x4E00 <= code <= 0x9FFF:
        #     clean_chars.append(char)

    return "".join(clean_chars)