########################################################
# Description
# OpenSearch 커스텀 이미지 빌드 명세
# - 기본 이미지: OpenSearch 2.11.0
# - 추가 플러그인: analysis-nori (한국어 형태소 분석기)
#
# Modified History
# 강광묵 / 2026-01-20 / 타이틀 주석 추가
########################################################

FROM opensearchproject/opensearch:2.11.0

# 플러그인 설치 (빌드 시점에 실행됨)
RUN /usr/share/opensearch/bin/opensearch-plugin install --batch analysis-nori