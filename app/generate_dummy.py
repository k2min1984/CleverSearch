"""
########################################################
# Description
# 테스트용 더미 데이터 생성
# 7만 건 규모의 랜덤 CSV/JSON 데이터를 생성하여
# OpenSearch 색인 성능 및 검색 품질 검증에 활용
#
# Modified History
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
import pandas as pd
import random
from datetime import datetime

# 7만 건 데이터 생성
data = []
categories = ["IT", "HR", "Finance", "Marketing", "Legal"]
print("데이터 생성 중... (약 10초 소요)")

for i in range(1, 70001):
    data.append({
        "No": i,
        "Title": f"테스트 데이터 제목_{i}",
        "Category": random.choice(categories),
        "Content": f"이것은 {i}번째 테스트 데이터입니다. OpenSearch 대용량 색인 성능을 검증합니다.",
        "Created_At": datetime.now().strftime("%Y-%m-%d"),
        "Author": f"작성자_{random.randint(1, 100)}"
    })

# 엑셀로 저장
df = pd.DataFrame(data)
filename = "대용량_테스트_데이터_7만건.xlsx"
df.to_excel(filename, index=False)
print(f"완료! '{filename}' 파일이 생성되었습니다.")