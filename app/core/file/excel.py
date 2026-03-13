import io
from datetime import date, datetime

import pandas as pd

def _normalize_cell_value(value) -> str:
    """엑셀 셀 값을 검색용 텍스트로 안정적으로 변환."""
    # Pandas의 NA/NaN 체크 (None, NaN, pd.NA, pd.NaT 모두 포함)
    if value is None or pd.isna(value):
        return ""

    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")

    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")

    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value).strip()


def _extract_text(content: bytes, ext: str = "xlsx") -> str:
    """
    엑셀 파일에서 검색용 텍스트를 추출합니다.
    - 헤더 자동 감지 및 '헤더: 값' 형태의 시멘틱 텍스트 변환
    """
    try:
        # header=None으로 읽어서 데이터 구조를 직접 파싱 (메타데이터가 상단에 있는 경우 대응)
        excel_data = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
        sheet_texts = []

        for i, (sheet_name, df) in enumerate(excel_data.items(), 1):
            if df.empty:
                continue

            lines = [f"[[Page {i}]] ## Sheet: {sheet_name}"]
            
            # DataFrame을 리스트로 변환하여 순회
            rows = df.values.tolist()
            
            # 1. 헤더 찾기 (값이 존재하는 첫 번째 행을 헤더로 간주)
            header_row = []
            header_idx = -1
            
            for idx, row in enumerate(rows):
                # 행의 값들을 정규화
                normalized_row = [_normalize_cell_value(v) for v in row]
                
                # 유효한 값이 하나라도 있으면 헤더로 선정
                if any(normalized_row):
                    header_row = normalized_row
                    header_idx = idx
                    break
            
            # 데이터가 없는 시트인 경우
            if header_idx == -1:
                continue

            # 2. 데이터 행 처리
            for row in rows[header_idx + 1:]:
                normalized_vals = [_normalize_cell_value(v) for v in row]
                
                # 빈 행 스킵
                if not any(normalized_vals):
                    continue

                parts = []
                for col_idx, val in enumerate(normalized_vals):
                    if not val:
                        continue
                    
                    # 헤더 매핑
                    if col_idx < len(header_row) and header_row[col_idx]:
                        key = header_row[col_idx]
                        parts.append(f"{key}: {val}")
                    else:
                        # 헤더가 없는 컬럼은 위치 정보 표시
                        parts.append(f"COL{col_idx + 1}: {val}")

                if parts:
                    lines.append(" | ".join(parts))

            if len(lines) > 1:
                sheet_texts.append("\n".join(lines))

        return "\n\n".join(sheet_texts)

    except Exception as e:
        return f"Excel 파싱 에러: {str(e)}"