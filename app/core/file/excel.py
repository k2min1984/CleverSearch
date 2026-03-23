"""
########################################################
# Description
# Excel 파일 파서
# 모든 시트를 순회하며 데이터 추출
# - 지원 포맷: XLSX, XLS
# - 엔진: openpyxl (pandas)
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""
import pandas as pd
import io

def parse_excel_all_sheets(content: bytes) -> list:
    """
    엑셀의 모든 시트를 순회하며 데이터를 추출
    """
    all_records = []
    # sheet_name=None 으로 설정하면 모든 시트를 Dict 형태로 가져옴
    excel_file = pd.read_excel(io.BytesIO(content), sheet_name=None, engine='openpyxl')

    for sheet_name, df in excel_file.items():
        # NaN 처리 및 데이터 정제
        df = df.replace({float('nan'): None})
        df = df.where(pd.notnull(df), None)
        
        # 시트 명 정보 추가
        records = df.to_dict(orient='records')
        for rec in records:
            rec['sheet_name'] = sheet_name  # 어떤 시트에서 왔는지 저장
            all_records.append(rec)
            
    return all_records