import unicodedata

# [텍스트] 필터링
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

# [텍스트] 필터링 + 유니코드 정규화
def _clean_text(text: str) -> str:
    """
    1. 유니코드 정규화 (특수 기호 -> 기본 문자로 변환)
    2. 화이트리스트 필터링 (한글, 영어, 숫자, 기본 기호 외 제거)
    """
    if not text:
        return ""

    # [Step 1] 특수문자 치환 (Normalization)
    # NFKC 정규화를 사용하면 '℃'->'C', '①'->'1', '—'->'-' 등으로 자동 변환됩니다.
    # 이렇게 하면 아래 화이트리스트에서 걸러지지 않고 살아남습니다.
    text = unicodedata.normalize('NFKC', text)

    # [Step 2] 화이트리스트 필터링 (기존 로직 유지)
    clean_chars = []
    for char in text:
        code = ord(char)
        
        # 1. 한글 (완성형 + 자모)
        if (0xAC00 <= code <= 0xD7A3) or (0x3131 <= code <= 0x318E):
            clean_chars.append(char)
        
        # 2. 영어, 숫자, 기본 특수문자 (ASCII 32~126)
        # NFKC 덕분에 스마트 따옴표(“), 불렛(•) 등이 이미 기본 문자(", -)로 바뀌어 있어서 여기서 통과됨
        elif 32 <= code <= 126:
            clean_chars.append(char)
        
        # 3. 필수 제어 문자 (탭, 줄바꿈)
        elif code in [9, 10, 13]:
            clean_chars.append(char)

    return "".join(clean_chars)

# [텍스트] 정제
def _refine_text(text: str) -> str:
    """
    [RAG 품질 최적화]
    LLM이 문맥을 잘 이해할 수 있도록 불필요한 공백을 줄이고 
    끊긴 문장을 이어 붙이는 등 텍스트 품질을 다듬습니다.
    """
    if not text:
        return ""

    # 1. 과도한 줄바꿈 정리 (3번 이상 연달아 나오면 2번으로 축소)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 2. 중복 공백/탭 정리 (스페이스 2개 이상 -> 1개)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    # 3. (옵션) 문장 중간에 애매하게 끊긴 단어 연결 (OCR 보정용)
    # 예: "안녕하- \n세요" -> "안녕하세요"
    text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)

    return text.strip()