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
    if ext == "hwpx":
        return _extract_text_hwpx(content)
    else:
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
            ["/".join(d) for d in dirs if len(d) >= 2 and d[0] == "BodyText" and d[1].startswith("Section")],
            key=lambda x: int(x.split("Section")[1])
        )
        
        text_result = []

        for i, section_path in enumerate(body_sections):
            # 섹션 시작 부분에 페이지 마커 삽입 (검색 위치 추적용)
            text_result.append(f"[[Page {i+1}]]\n")
            
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
                        raw_text = raw_text.replace('\x00', '')  # NULL 문자 제거
                        clean_text = string._clean_text(raw_text)
                        
                        if clean_text.strip():
                            text_result.append(clean_text)
                            text_result.append("\n")
                    except:
                        pass
                
                pos += rec_len

            # 섹션 간 구분감 추가
            text_result.append("\n\n")

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
            
            for i, section in enumerate(section_files):
                # 섹션 시작 부분에 페이지 마커 삽입
                text_result.append(f"[[Page {i+1}]]\n")
                
                try:
                    xml_data = z.read(section)
                    root = ET.fromstring(xml_data)
                    
                    # 문단(p) 단위로 순회하여 텍스트(t)를 합침 (구조 보존 강화)
                    for elem in root.iter():
                        if elem.tag.endswith('p'):
                            para_text = []
                            for child in elem.iter():
                                if child.tag.endswith('t') and child.text:
                                    para_text.append(child.text)
                            
                            if para_text:
                                line = "".join(para_text)
                                clean_line = string._clean_text(line)
                                if clean_line:
                                    text_result.append(clean_line)
                                    text_result.append("\n")
                    
                    # 섹션 간 구분감 추가
                    text_result.append("\n")
                except:
                    continue

        return "".join(text_result).strip()

    except Exception as e:
        return f"HWPX 추출 중 오류: {str(e)}"
