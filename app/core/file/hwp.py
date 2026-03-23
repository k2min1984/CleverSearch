"""
########################################################
# Description
# 한글(HWP/HWPX) 파일 파서
# 한글 문서에서 본문 텍스트를 추출
# - HWP: OLE 켨테이너 → BodyText 스트림 → zlib 압축 해제
# - HWPX: ZIP/XML 포맷 → Contents/section XML 파싱
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
import io
import zlib
import struct
import zipfile
import xml.etree.ElementTree as ET
import olefile
# import
from app.utils import string

# [한글파일] 추출
def _extract_text(content: bytes, ext: str) -> str:
    """
    파일 확장자나 헤더를 보고 HWP와 HWPX를 자동으로 분기하여 처리합니다.
    """
    print("한글파일추출["+ext+"]")
    # 1. 파일 확장자가 HWPX
    if ext == "hwpx":
        return _extract_text_hwpx(content)
    
    # 2. 그 외에는 HWP(OLE)로 간주하고 처리
    return _extract_text_hwp(content)

# [한글파일] HWP
def _extract_text_hwp(content: bytes) -> str:
    try:
        f = io.BytesIO(content)
        if not olefile.isOleFile(f):
            return "유효한 HWP 파일이 아닙니다."

        ole = olefile.OleFileIO(f)
        dirs = ole.listdir()
        
        body_sections = sorted(
            ["/".join(d) for d in dirs if d[0] == "BodyText" and d[1].startswith("Section")],
            key=lambda x: int(x.split("Section")[1])
        )
        
        text_result = []

        for section_path in body_sections:
            data = ole.openstream(section_path).read()
            
            # [1] 압축 해제 시도 (실패 시 바이너리 유출 방지)
            try:
                unpacked_data = zlib.decompress(data, -15)
            except:
                unpacked_data = data
            
            pos = 0
            size = len(unpacked_data)
            
            while pos < size:
                # [2] 안전장치: 헤더 읽을 공간 부족하면 중단
                if pos + 4 > size: break

                header = struct.unpack('<I', unpacked_data[pos:pos+4])[0]
                tag_id = header & 0x3FF
                rec_len = (header >> 20) & 0xFFF
                pos += 4
                
                # 4095바이트 초과 시 추가 길이 정보 읽기
                if rec_len == 0xFFF:
                    if pos + 4 > size: break
                    rec_len = struct.unpack('<I', unpacked_data[pos:pos+4])[0]
                    pos += 4
                
                # [3] ★핵심 안전장치★: 데이터 길이가 전체 사이즈를 넘어가면 즉시 탈출
                # (손상된 파일이 무한 루프 돌거나 에러 내는 것 방지)
                if pos + rec_len > size: break
                
                if tag_id == 67: # 문단 텍스트
                    rec_data = unpacked_data[pos:pos+rec_len]
                    if len(rec_data) % 2 != 0:
                        rec_data = rec_data[:-1]
                    
                    try:
                        raw_text = rec_data.decode('utf-16-le', errors='ignore')
                        clean_text = string.clean_text(raw_text)
                        
                        if clean_text.strip():
                            text_result.append(clean_text)
                            text_result.append("\n")
                    except:
                        pass
                
                pos += rec_len

        ole.close()
        return "".join(text_result).strip()

    except Exception as e:
        # HWP 파싱은 워낙 변수가 많으므로, 에러 시 빈 문자열 반환하여 서버 보호
        print(f"HWP 파싱 에러(무시됨): {e}")
        return ""

# [한글파일] 추출 HWPX 
def _extract_text_hwpx(content: bytes) -> str:
    try:
        f = io.BytesIO(content)
        # 여기서 ZIP이 아니면 바로 리턴 -> 메인 함수가 받아서 HWP로 재시도함
        if not zipfile.is_zipfile(f):
            return "유효한 HWPX 파일이 아닙니다."
            
        text_result = []
        
        with zipfile.ZipFile(f) as z:
            section_files = sorted(
                [n for n in z.namelist() if n.startswith("Contents/section") and n.endswith(".xml")]
            )
            
            for section in section_files:
                try:
                    xml_data = z.read(section)
                    root = ET.fromstring(xml_data)
                    
                    for elem in root.iter():
                        # 텍스트 태그 <hp:t>
                        if elem.tag.endswith('t') and elem.text:
                            clean_text = string.clean_text(elem.text)
                            if clean_text:
                                text_result.append(clean_text)
                        
                        # 문단 태그 <hp:p>
                        if elem.tag.endswith('p'):
                            text_result.append("\n")
                except:
                    continue

        return "".join(text_result).strip()

    except Exception as e:
        return f"HWPX 추출 중 오류: {str(e)}"

# [한글파일] 필터링
def _clean_text(text: str) -> str:
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