########################################################
# Description
# Python FastAPI 애플리케이션 이미지 빌드 명세
#
# Modified History
# 강광묵 / 2026-01-20 / 타이틀 주석 추가
########################################################

FROM python:3.11-slim

WORKDIR /app

# 의존성 설치 (캐시 활용을 위해 먼저 복사)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 전체 복사
COPY . .

# 앱 실행
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]