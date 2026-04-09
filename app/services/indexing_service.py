"""
########################################################
# Description
# 색인 서비스 (IndexingService)
# 파일 파싱 → 텍스트 추출 → 청크 분할 → AI 임베딩 → OpenSearch 색인
# - PDF/HWP/HWPX/DOCX/PPTX/XLSX/이미지 파싱 통합
# - 텍스트 청크 분할 (chunk_size 단위)
# - 초성 텍스트 변환 (chosung_text 필드 생성)
# - 768차원 벡터 임베딩 (ko-sroberta-multitask)
# - OpenSearch 벨크 색인
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
# 강광민 / 2026-02-13 / 파서 통합 및 임베딩 고도화
########################################################
"""
from datetime import datetime, timezone
import hashlib

from app.common.embedding import embedder
from app.common.utils import DocumentUtils
from app.core.config import settings
from app.core.file import excel, hwp, image, office, pdf
from app.core.opensearch import get_client
from app.services.db_service import DBService


ALLOWED_EXTENSIONS = {"xlsx", "xls", "hwp", "hwpx", "pdf", "docx", "pptx", "jpg", "jpeg", "png", "txt"}


class IndexingService:
    @staticmethod
    def ensure_index() -> None:
        client = get_client()
        index_name = settings.OPENSEARCH_INDEX
        if client.indices.exists(index=index_name):
            return

        index_body = {
            "settings": {
                "index": {
                    "knn": True,
                    "max_ngram_diff": 18,
                    "analysis": {
                        "analyzer": {
                            "korean_analyzer": {
                                "type": "custom",
                                "tokenizer": "nori_tokenizer",
                                "filter": ["lowercase", "nori_readingform", "my_stop_filter"],
                            },
                            "chosung_ngram_analyzer": {
                                "type": "custom",
                                "tokenizer": "keyword",
                                "filter": ["lowercase", "chosung_ngram_filter"],
                            },
                        },
                        "filter": {
                            "my_stop_filter": {
                                "type": "stop",
                                "stopwords": ["에", "대해서", "해주세요", "알려주세요", "의", "를", "은", "는"],
                            },
                            "chosung_ngram_filter": {
                                "type": "ngram",
                                "min_gram": 2,
                                "max_gram": 20,
                            },
                        },
                    },
                }
            },
            "mappings": {
                "properties": {
                    "Title": {"type": "text", "analyzer": "korean_analyzer"},
                    "all_text": {"type": "text", "analyzer": "korean_analyzer"},
                    "doc_category": {"type": "keyword"},
                    "chosung_text": {"type": "text", "analyzer": "whitespace"},
                    "chosung_text_ngram": {
                        "type": "text",
                        "analyzer": "chosung_ngram_analyzer",
                        "search_analyzer": "chosung_ngram_analyzer",
                    },
                    "origin_file": {"type": "keyword"},
                    "file_ext": {"type": "keyword"},
                    "content_hash": {"type": "keyword"},
                    "indexed_at": {"type": "date"},
                    "text_vector": {"type": "knn_vector", "dimension": 768},
                }
            },
        }
        client.indices.create(index=index_name, body=index_body)

    @staticmethod
    def _extract_text(filename: str, content: bytes) -> tuple[str, str]:
        ext = filename.split(".")[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            return "", ext

        text_content = ""
        if ext in ["hwp", "hwpx"]:
            text_content = hwp.extract_text(content, ext)
        elif ext == "pdf":
            text_content = pdf.extract_text(content)
        elif ext in ["docx", "pptx"]:
            text_content = office.extract_text(content, ext)
        elif ext in ["xlsx", "xls"]:
            text_content = excel.extract_text(content)
        elif ext in ["jpg", "jpeg", "png"]:
            text_content = image.extract_text(content)
        elif ext == "txt":
            text_content = content.decode("utf-8", errors="ignore")

        return text_content, ext

    @staticmethod
    def index_bytes(filename: str, content: bytes, source_label: str = "upload") -> dict:
        IndexingService.ensure_index()
        client = get_client()
        index_name = settings.OPENSEARCH_INDEX

        safe_filename = DocumentUtils.sanitize_text(filename)
        text_content, ext = IndexingService._extract_text(safe_filename, content)

        if ext not in ALLOWED_EXTENSIONS:
            return {"status": "fail", "message": f"지원하지 않는 확장자: {ext}", "file": safe_filename}

        clean_body_text = DocumentUtils.sanitize_text(text_content)
        if not clean_body_text.strip():
            return {"status": "fail", "message": "추출된 텍스트 없음", "file": safe_filename}

        # 동일 파일 재업로드를 강하게 차단하기 위해 파일 바이트 해시를 기본 지문으로 사용합니다.
        binary_digest = hashlib.sha256(content).hexdigest()
        legacy_text_digest = DocumentUtils.generate_content_digest(clean_body_text, safe_filename)
        content_digest = binary_digest

        db_dup = DBService.find_duplicate_indexed_document(
            title=safe_filename,
            all_text=clean_body_text,
            content_hash=str(content_digest),
        )
        if (not db_dup.get("is_duplicate")) and (legacy_text_digest != content_digest):
            db_dup = DBService.find_duplicate_indexed_document(
                title=safe_filename,
                all_text=clean_body_text,
                content_hash=str(legacy_text_digest),
            )
        if db_dup.get("is_duplicate"):
            reason = db_dup.get("reason")
            origin_file = db_dup.get("origin_file") or safe_filename
            if reason == "title_and_content":
                message = f"DB 중복(제목+내용 동일): {origin_file}"
            else:
                message = f"DB 중복(내용 해시 동일): {origin_file}"
            return {
                "status": "skipped",
                "message": message,
                "file": safe_filename,
                "content_hash": content_digest,
            }

        is_dup, existing_file = DocumentUtils.check_duplicate_content(client, index_name, content_digest)
        if (not is_dup) and (legacy_text_digest != content_digest):
            is_dup, existing_file = DocumentUtils.check_duplicate_content(client, index_name, legacy_text_digest)
        if is_dup:
            return {
                "status": "skipped",
                "message": f"내용 중복: {existing_file}",
                "file": safe_filename,
                "content_hash": content_digest,
            }

        category = DocumentUtils.map_category(safe_filename)
        vector_data = embedder.get_embedding(clean_body_text[:2000])
        if hasattr(vector_data, "tolist"):
            vector_data = vector_data.tolist()
        safe_source_label = DocumentUtils.sanitize_text(source_label)

        doc_source = {
            "origin_file": safe_filename,
            "all_text": clean_body_text,
            "doc_category": category,
            "chosung_text": DocumentUtils.convert_to_chosung(clean_body_text),
            "chosung_text_ngram": DocumentUtils.convert_to_chosung(clean_body_text).replace(" ", ""),
            "content_hash": str(content_digest),
            "Title": safe_filename,
            "file_ext": ext,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "text_vector": vector_data,
            "source_label": safe_source_label,
        }

        safe_doc = DocumentUtils.sanitize_for_opensearch(doc_source)
        index_res = client.index(index=index_name, body=safe_doc, refresh=True)
        DBService.save_indexed_document(
            os_doc_id=index_res.get("_id", ""),
            origin_file=safe_filename,
            file_ext=ext,
            doc_category=category,
            content_hash=str(content_digest),
            title=safe_filename,
            all_text=clean_body_text,
        )

        return {
            "status": "success",
            "message": "색인 완료",
            "file": safe_filename,
            "content_hash": content_digest,
            "category": category,
            "doc_id": index_res.get("_id"),
        }
