"""
########################################################
# Description
# Excel 파일 파서
# 모든 시트를 순회하며 텍스트 추출
# - 지원 포맷: XLSX (openpyxl), XLS (xlrd 폴백)
# - 셀 값을 공백 구분 텍스트로 병합하여 반환
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
# 강광민 / 2026-04-02 / 고도화 (str 반환, XLS 지원, 에러 처리)
########################################################
"""
import io
import pandas as pd


def extract_text(content: bytes) -> str:
    """
    엑셀 파일의 모든 시트에서 텍스트를 추출하여 str로 반환합니다.
    XLSX를 우선 시도하고 실패 시 XLS(xlrd)로 폴백합니다.
    """
    try:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, engine='openpyxl')
    except Exception:
        try:
            sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, engine='xlrd')
        except Exception:
            return ""

    lines: list[str] = []
    for sheet_name, df in sheets.items():
        lines.append(f"[{sheet_name}]")
        for _, row in df.iterrows():
            cells = [str(v) for v in row.values if pd.notna(v)]
            if cells:
                lines.append(" ".join(cells))
    return "\n".join(lines)


def parse_excel_all_sheets(content: bytes) -> list:
    """
    엑셀의 모든 시트를 순회하며 dict 리스트로 반환 (레거시 호환용).
    """
    all_records = []
    try:
        excel_file = pd.read_excel(io.BytesIO(content), sheet_name=None, engine='openpyxl')
    except Exception:
        try:
            excel_file = pd.read_excel(io.BytesIO(content), sheet_name=None, engine='xlrd')
        except Exception:
            return []

    for sheet_name, df in excel_file.items():
        df = df.where(pd.notnull(df), None)
        records = df.to_dict(orient='records')
        for rec in records:
            rec['sheet_name'] = sheet_name
            all_records.append(rec)
    return all_records