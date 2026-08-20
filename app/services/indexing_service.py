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
import json
import logging

from app.common.embedding import embedder
from app.common.utils import DocumentUtils
from app.core.config import settings
from app.core.file import excel, hwp, image, office, pdf
from app.core.opensearch import get_client
from app.services.db_service import DBService

_logger = logging.getLogger(__name__)
EMBED_BATCH_SIZE = 32
BULK_CHUNK_SIZE = 500


ALLOWED_EXTENSIONS = {"xlsx", "xls", "hwp", "hwpx", "pdf", "docx", "pptx", "jpg", "jpeg", "png", "txt"}


class IndexingService:
    @staticmethod
    def _decode_text_with_fallback(content: bytes) -> str:
        """txt 파일 인코딩 추정 디코딩 (Windows 로컬/레거시 파일 대응)"""
        for enc in ("utf-8-sig", "utf-16", "cp949", "euc-kr"):
            try:
                text = content.decode(enc)
                if text.strip():
                    return text
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="ignore")

    @staticmethod
    def ensure_index(index_name: str | None = None) -> str:
        target_index = (index_name or settings.OPENSEARCH_INDEX).strip() or settings.OPENSEARCH_INDEX
        client = get_client()
        if client.indices.exists(index=target_index):
            return target_index

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
        client.indices.create(index=target_index, body=index_body)
        return target_index

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
            text_content = IndexingService._decode_text_with_fallback(content)

        return text_content, ext

    @staticmethod
    def index_bytes(filename: str, content: bytes, source_label: str = "upload", index_name: str | None = None) -> dict:
        target_index = IndexingService.ensure_index(index_name=index_name)
        client = get_client()

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

        is_dup, existing_file = DocumentUtils.check_duplicate_content(client, target_index, content_digest)
        if (not is_dup) and (legacy_text_digest != content_digest):
            is_dup, existing_file = DocumentUtils.check_duplicate_content(client, target_index, legacy_text_digest)
        if is_dup:
            return {
                "status": "skipped",
                "message": f"내용 중복: {existing_file}",
                "file": safe_filename,
                "content_hash": content_digest,
                "index": target_index,
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
        # 내용 해시를 문서 ID로 고정하여 동일 문서 재색인 시 신규 생성 대신 덮어쓰기합니다.
        index_res = client.index(index=target_index, id=str(content_digest), body=safe_doc, refresh=True)
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
            "index": target_index,
        }

    @staticmethod
    def _build_doc_from_item(item: dict) -> tuple[dict | None, str]:
        """index_bulk 입력 1건을 OpenSearch 문서 dict로 변환합니다.

        item 필수 키: filename, text
        선택 키: doc_id, ext, source_label, content_hash, indexed_at
        반환: (doc_dict, content_hash)  - 본문 비어있으면 (None, "")
        """
        raw_filename = item.get("filename") or ""
        raw_text = item.get("text") or ""
        safe_filename = DocumentUtils.sanitize_text(raw_filename)
        clean_body_text = DocumentUtils.sanitize_text(raw_text)
        if not clean_body_text.strip():
            return None, ""

        ext = item.get("ext")
        if not ext:
            ext = safe_filename.split(".")[-1].lower() if "." in safe_filename else "txt"

        # bulk 경로에서는 호출자가 이미 변경된 항목만 넘긴다는 전제이므로
        # 해시는 식별용으로만 채워둔다 (중복 체크는 PK upsert가 대신 처리).
        content_hash = item.get("content_hash") or hashlib.sha256(clean_body_text.encode("utf-8", errors="ignore")).hexdigest()
        category = DocumentUtils.map_category(safe_filename)
        safe_source_label = DocumentUtils.sanitize_text(item.get("source_label") or "")
        indexed_at = item.get("indexed_at") or datetime.now(timezone.utc).isoformat()
        chosung = DocumentUtils.convert_to_chosung(clean_body_text)

        doc_source = {
            "origin_file": safe_filename,
            "all_text": clean_body_text,
            "doc_category": category,
            "chosung_text": chosung,
            "chosung_text_ngram": chosung.replace(" ", ""),
            "content_hash": str(content_hash),
            "Title": safe_filename,
            "file_ext": ext,
            "indexed_at": indexed_at,
            "source_label": safe_source_label,
            # text_vector 는 임베딩 배치 후 채움
        }
        return DocumentUtils.sanitize_for_opensearch(doc_source), str(content_hash)

    @staticmethod
    def index_bulk(
        items: list[dict],
        index_name: str | None = None,
        refresh: bool = False,
    ) -> dict:
        """문서 다건을 임베딩 배치 + OpenSearch _bulk 로 일괄 색인합니다.

        설계 원칙(증분색인_설계_20260424):
        - 호출자가 이미 "변경/신규" 판별을 끝낸 항목만 전달 (중복 체크 생략)
        - PK 기반 _id 사용 시 같은 _id 재색인은 자동 덮어쓰기
        - refresh=False 가 기본, Job 완료 시점에만 1회 refresh 권장

        items[i] 키 규약:
          filename(str, 필수), text(str, 필수)
          doc_id(str), ext(str), source_label(str), content_hash(str), indexed_at(iso)

        반환: {indexed, skipped, failed, errors, index}
        """
        target_index = IndexingService.ensure_index(index_name=index_name)
        client = get_client()

        if not items:
            return {"indexed": 0, "skipped": 0, "failed": 0, "errors": [], "index": target_index}

        # 1) 문서 dict 빌드 + 본문 비어있는 항목 skip 분리
        prepared: list[tuple[dict, str | None, dict]] = []  # (doc_source, doc_id, original_item)
        skipped = 0
        for item in items:
            doc_source, _hash = IndexingService._build_doc_from_item(item)
            if doc_source is None:
                skipped += 1
                continue
            doc_id = item.get("doc_id")
            prepared.append((doc_source, doc_id, item))

        if not prepared:
            return {"indexed": 0, "skipped": skipped, "failed": 0, "errors": [], "index": target_index}

        # 2) 임베딩 배치 (메모리 절약 위해 EMBED_BATCH_SIZE 단위로 잘라 호출)
        texts = [doc["all_text"][:2000] for doc, _id, _it in prepared]
        try:
            vectors = IndexingService._embed_batch(texts)
        except Exception as exc:
            _logger.exception("[index_bulk] 임베딩 배치 실패: %s", exc)
            return {
                "indexed": 0,
                "skipped": skipped,
                "failed": len(prepared),
                "errors": [str(exc)],
                "index": target_index,
            }

        for (doc, _id, _it), vec in zip(prepared, vectors):
            doc["text_vector"] = vec

        # 3) OpenSearch _bulk 페이로드 구성 + chunk 단위 호출
        indexed = 0
        failed = 0
        errors: list[str] = []
        for chunk_start in range(0, len(prepared), BULK_CHUNK_SIZE):
            chunk = prepared[chunk_start:chunk_start + BULK_CHUNK_SIZE]
            payload_lines: list[str] = []
            for doc, doc_id, _it in chunk:
                action: dict = {"index": {"_index": target_index}}
                if doc_id:
                    action["index"]["_id"] = doc_id
                payload_lines.append(json.dumps(action, ensure_ascii=False))
                payload_lines.append(json.dumps(doc, ensure_ascii=False))
            body = "\n".join(payload_lines) + "\n"

            try:
                resp = client.bulk(body=body, refresh=False)
            except Exception as exc:
                _logger.exception("[index_bulk] bulk 호출 실패: %s", exc)
                failed += len(chunk)
                errors.append(str(exc))
                continue

            if not resp.get("errors"):
                indexed += len(chunk)
                continue

            # 부분 실패: 항목별 결과 검사
            for entry in resp.get("items", []):
                op = entry.get("index") or entry.get("create") or entry.get("update") or {}
                if op.get("error"):
                    failed += 1
                    err = op.get("error", {})
                    errors.append(f"{op.get('_id', '?')}: {err.get('type', '')} {err.get('reason', '')}".strip())
                else:
                    indexed += 1

        # 4) Job 완료 시점에만 1회 refresh 권장 → 호출자가 refresh=True 로 마무리
        if refresh and indexed > 0:
            try:
                client.indices.refresh(index=target_index)
            except Exception as exc:
                _logger.warning("[index_bulk] refresh 실패(무시): %s", exc)

        return {
            "indexed": indexed,
            "skipped": skipped,
            "failed": failed,
            "errors": errors,
            "index": target_index,
        }

    @staticmethod
    def _embed_batch(texts: list[str]) -> list[list[float]]:
        """임베딩을 EMBED_BATCH_SIZE 단위로 호출해 메모리 사용량을 제어합니다."""
        if not texts:
            return []
        # SentenceTransformer.encode 는 list 입력 시 내부에서 배치 처리하지만,
        # 거대 입력 한방에 넘기지 않도록 안전장치 적용.
        out: list[list[float]] = []
        model = embedder.model
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            chunk = texts[i:i + EMBED_BATCH_SIZE]
            vecs = model.encode(chunk, batch_size=min(EMBED_BATCH_SIZE, len(chunk)), show_progress_bar=False)
            for v in vecs:
                out.append(v.tolist() if hasattr(v, "tolist") else list(v))
        return out
