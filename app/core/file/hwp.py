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
########################################################
"""
import io
import re
import zlib
import struct
import zipfile
import xml.etree.ElementTree as ET
import olefile
# import
from app.utils import string

# [한글파일] 추출
def extract_text(content: bytes, ext: str) -> str:
    """
    파일 확장자나 헤더를 보고 HWP와 HWPX를 자동으로 분기하여 처리합니다.
    결과에서 제어문자를 제거하고 [[Page 1]] 마커를 포함하여 반환합니다.
    """
    # 1. 파일 확장자가 HWPX
    if ext == "hwpx":
        raw = _extract_text_hwpx(content)
    else:
        # 2. 그 외에는 HWP(OLE)로 간주하고 처리
        raw = _extract_text_hwp(content)

    # 제어문자 정리 (폼 피드, 수직탭 등)
    clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", raw)
    return f"[[Page 1]]\n{clean}" if clean.strip() else ""

# [한글파일] HWP
def _extract_text_hwp(content: bytes) -> str:
    """
    HWP(OLE 형식) 문서에서 텍스트 추출
    - OLE 파일의 BodyText/SectionN 스트림을 순서대로 읽음
    - zlib 압축 해제 후 바이너리 레코드 파싱 (tag_id=67: 문단 텍스트)
    - 손상된 파일에 대한 안전장치 (헤더 부족/길이 초과 시 중단)
    - 제어문자 정제 후 텍스트 반환
    """
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
            except Exception:
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
                    except Exception:
                        pass
                
                pos += rec_len

        ole.close()
        return "".join(text_result).strip()

    except Exception as e:
        # HWP 파싱은 워낙 변수가 많으므로, 에러 시 빈 문자열 반환하여 서버 보호
        return ""

# [한글파일] 추출 HWPX 
def _extract_text_hwpx(content: bytes) -> str:
    """
    HWPX(ZIP+XML 형식) 문서에서 텍스트 추출
    - ZIP 내부 Contents/sectionN.xml 파일을 순서대로 읽음
    - XML 태그 내 텍스트 노드를 재귀적으로 추출
    - 제어문자 정제 후 텍스트 반환
    """
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
                except Exception:
                    continue

        return "".join(text_result).strip()

    except Exception:
        return ""

# _clean_text 제거 — string.clean_text() 와 동일 기능이므로 통합 사용