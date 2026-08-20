"""
########################################################
# Description
# OpenSearch 인덱스 조회 및 데이터 확인용 API
# 전체 데이터 검색(Match All) 로직 포함
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""

import hashlib
import json
import logging
import re
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile

from app.common.utils import DocumentUtils
from app.core.config import settings
from app.core.security import require_role
from app.core.database import IndexingHistory, get_db_session
from app.core.opensearch import get_client
from app.services.db_service import DBService
from app.services.indexing_service import IndexingService

_logger = logging.getLogger(__name__)

router = APIRouter()

# OpenSearch 클라이언트 객체 생성
client = get_client()

INDEX_NAME = settings.OPENSEARCH_INDEX

# 외부 에이전트 업로드 한도 (서버측 보호용)
AGENT_MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100MB

# X-File-SHA256 형식 검증 (소문자 16진수 64자)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _verify_agent_key(x_agent_key: str | None) -> None:
    """공통 에이전트 인증. 미설정 시 503, 불일치 시 401."""
    expected = (settings.AGENT_API_KEY or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="AGENT_API_KEY 미설정 - 서버 관리자에게 문의")
    if (x_agent_key or "").strip() != expected:
        raise HTTPException(status_code=401, detail="유효하지 않은 에이전트 키")

@router.get("/all-data", dependencies=[Depends(require_role("viewer"))], summary="색인된 전체 데이터 조회")
async def get_all_indexed_data():
    """
    OpenSearch 인덱스에 저장된 모든 데이터를 조회합니다.
    주로 데이터 적재 확인 및 디버깅 용도로 사용됩니다.
    """
    try:
        # 1. Match All 쿼리 실행
        # 조건 없이 모든 문서를 조회하며, 성능을 위해 최대 100개까지만 가져옵니다.
        response = client.search(
            index=INDEX_NAME,
            body={
                "query": {
                    "match_all": {} # 필터링 없는 전체 검색
                },
                "size": 100 # 프로토타입 UI 부하 방지를 위한 제한
            }
        )
        
        # 2. 검색 결과 파싱
        # OpenSearch 응답 구조에서 실제 데이터(_source)만 추출합니다.
        hits = response.get("hits", {}).get("hits", [])
        results = [hit["_source"] for hit in hits]
        
        return {
            "total": response["hits"]["total"]["value"],
            "data": results
        }
        
    except Exception as e:
        # 3. 예외 처리: 인덱스가 없는 경우 (최초 실행 시)
        # 500 에러 대신 빈 리스트를 반환하여 프론트엔드가 깨지지 않도록 처리
        if "index_not_found_exception" in str(e):
            return {
                "total": 0, 
                "data": [], 
                "message": "인덱스가 존재하지 않습니다. 먼저 엑셀 파일을 업로드하여 데이터를 생성해주세요."
            }
            
        # 그 외의 연결 오류 등은 500 에러로 처리
        raise HTTPException(status_code=500, detail=f"데이터 조회 중 오류 발생: {str(e)}")


def _record_agent_history(
    source_name: str,
    file_name: str,
    file_status: str,
    file_message: str,
    source_path: str,
    file_sha: str = "",
) -> None:
    """에이전트 색인 결과를 일자별·IP별 1행으로 누적 업데이트한다.
    SMB 의 sync_summary 와 동일하게 'agent_summary' 액션으로 묶어 이력 폭증을 방지한다.

    file_name 필드: "총 N건 (성공 S / 실패 F / 스킵 K)"
    message 필드  : JSON {"success","fail","skipped","total","last_file","last_at","last_path","last_status","last_sha"}
    status 필드   : 누적 상태 (success/partial/fail)
    """
    safe_ip = (source_name or "agent")[:120]
    file_status_norm = (file_status or "unknown").lower()

    today_start = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
    today_end = today_start + timedelta(days=1)

    try:
        with get_db_session() as db:
            row = (
                db.query(IndexingHistory)
                .filter(
                    IndexingHistory.source_type == "agent",
                    IndexingHistory.source_name == safe_ip,
                    IndexingHistory.action == "agent_summary",
                    IndexingHistory.created_at >= today_start,
                    IndexingHistory.created_at < today_end,
                )
                .first()
            )

            counts = {"success": 0, "fail": 0, "skipped": 0, "total": 0}
            if row and row.message:
                try:
                    prev = json.loads(row.message)
                    for k in counts:
                        counts[k] = int(prev.get(k, 0) or 0)
                except Exception:
                    counts = {"success": 0, "fail": 0, "skipped": 0, "total": 0}

            if file_status_norm == "success":
                counts["success"] += 1
            elif file_status_norm == "skipped":
                counts["skipped"] += 1
            else:
                counts["fail"] += 1
            counts["total"] += 1

            if counts["fail"] == 0:
                roll_status = "success"
            elif counts["success"] == 0 and counts["skipped"] == 0:
                roll_status = "fail"
            else:
                roll_status = "partial"

            summary_payload = {
                **counts,
                "last_file": file_name or "",
                "last_status": file_status_norm,
                "last_path": source_path or "",
                "last_sha": (file_sha or "")[:64],
                "last_at": datetime.now(timezone.utc).isoformat(),
                "last_message": (file_message or "")[:200],
            }
            file_label = (
                f"총 {counts['total']}건 (성공 {counts['success']} / 실패 {counts['fail']} / 스킵 {counts['skipped']})"
            )
            message_json = json.dumps(summary_payload, ensure_ascii=False)[:500]

            if row is None:
                db.add(
                    IndexingHistory(
                        source_type="agent",
                        source_name=safe_ip,
                        file_name=file_label[:260],
                        action="agent_summary",
                        status=roll_status,
                        message=message_json,
                    )
                )
            else:
                row.file_name = file_label[:260]
                row.status = roll_status
                row.message = message_json
                # created_at 은 일자별 키이므로 갱신하지 않음
    except Exception as exc:
        _logger.warning("agent IndexingHistory 기록 실패: %s", exc)


@router.get("/agent-check", summary="외부 에이전트 사전 SHA-256 중복 질의")
async def agent_check(
    sha256: str = Query(..., description="파일 전체 SHA-256 16진수 64자"),
    x_agent_key: str | None = Header(None, alias="X-Agent-Key"),
):
    """에이전트가 본문 업로드 전에 호출하는 사전 질의 엔드포인트.

    - 적중(exists=True): 에이전트는 본문 전송을 생략하고 로컬 registry 에만 등록한다.
    - 미적중(exists=False): 에이전트는 /agent-notify 로 본문 업로드 진행.

    *주의*: 본 응답만으로 색인 정합성을 보장하지 않는다 — 본문 업로드 시점에도
    서버에서 X-File-SHA256 재검증을 수행하므로, 사전 질의는 순수 전송량 절감용.
    """
    _verify_agent_key(x_agent_key)
    sha = (sha256 or "").strip().lower()
    if not _SHA256_RE.match(sha):
        raise HTTPException(status_code=400, detail="sha256 형식 오류 (소문자 16진수 64자 필요)")
    hit = DBService.find_duplicate_by_content_hash(sha)
    if hit.get("is_duplicate"):
        return {
            "exists": True,
            "sha256": sha,
            "doc_id": hit.get("doc_id"),
            "origin_file": hit.get("origin_file"),
        }
    return {"exists": False, "sha256": sha}


@router.post("/agent-notify", summary="외부 에이전트 신규파일 알림 → 색인 실행")
async def agent_notify(
    request: Request,
    file: UploadFile = File(..., description="감지된 신규 파일(이진)"),
    source_path: str = Form("", description="에이전트 측 절대 경로(추적용)"),
    x_agent_key: str | None = Header(None, alias="X-Agent-Key"),
    x_file_sha256: str | None = Header(None, alias="X-File-SHA256"),
    x_file_size: str | None = Header(None, alias="X-File-Size"),
):
    """
    외부 GUI 에이전트가 특정 폴더에서 신규 파일을 감지했을 때 호출하는 엔드포인트.
    파일을 디스크에 저장하지 않고 메모리에서 곧바로 IndexingService 로 넘긴다.
    색인 결과는 IndexingHistory(source_type='agent') 에도 기록되어 관리자 화면에서 추적 가능.

    추가 헤더:
      - X-File-SHA256 : (선택) 클라이언트가 계산한 전체 파일 SHA-256.
                        있으면 본문 수신 전 DB 중복 컷 + 수신 후 무결성 재검증에 사용.
      - X-File-Size   : (선택) 클라이언트가 본 파일 크기. 본문 수신 후 위변조 검증에 사용.
    """
    _verify_agent_key(x_agent_key)

    # 클라이언트(에이전트) 식별: X-Forwarded-For 우선, 없으면 직접 IP
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    client_ip = fwd or (request.client.host if request.client else "unknown")

    filename = DocumentUtils.sanitize_text(file.filename or "")
    if not filename:
        raise HTTPException(status_code=400, detail="파일명 누락")

    # ---- 사전 검증: 본문 받기 전 단계 ----------------------------------
    claimed_sha = (x_file_sha256 or "").strip().lower()
    if claimed_sha and not _SHA256_RE.match(claimed_sha):
        raise HTTPException(status_code=400, detail="X-File-SHA256 형식 오류 (16진수 64자)")

    claimed_size: int | None = None
    if x_file_size:
        try:
            claimed_size = int(x_file_size)
        except ValueError:
            raise HTTPException(status_code=400, detail="X-File-Size 형식 오류 (정수 필요)")
        if claimed_size <= 0:
            raise HTTPException(status_code=400, detail="X-File-Size 가 0 이하")
        if claimed_size > AGENT_MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"파일 크기 초과: 최대 {AGENT_MAX_UPLOAD_SIZE // 1024 // 1024}MB (claimed)",
            )

    # 헤더 sha 만으로 DB 중복 컷 (본문 수신 비용 회피)
    if claimed_sha:
        hash_dup = DBService.find_duplicate_by_content_hash(claimed_sha)
        if hash_dup.get("is_duplicate"):
            msg = f"DB 중복(헤더 SHA): {hash_dup.get('origin_file')}"
            _record_agent_history(client_ip, filename, "skipped", msg, source_path, claimed_sha)
            return {
                "status": "skipped",
                "message": msg,
                "file": filename,
                "source_path": source_path,
                "sha256": claimed_sha,
                "precheck": True,
            }

    # ---- 본문 수신 ------------------------------------------------------
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="빈 파일")
    if len(content) > AGENT_MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"파일 크기 초과: 최대 {AGENT_MAX_UPLOAD_SIZE // 1024 // 1024}MB",
        )

    # 서버에서 항상 재계산 → 신뢰 가능 디지스트
    binary_digest = hashlib.sha256(content).hexdigest()

    # 무결성 검증: 클라이언트가 헤더로 보낸 값과 일치해야 함
    if claimed_sha and claimed_sha != binary_digest:
        _logger.warning(
            "agent SHA mismatch: ip=%s file=%s claimed=%s actual=%s",
            client_ip, filename, claimed_sha, binary_digest,
        )
        _record_agent_history(
            client_ip, filename, "fail",
            "전송 무결성 오류: 헤더 SHA 와 본문 SHA 불일치",
            source_path, binary_digest,
        )
        raise HTTPException(
            status_code=422,
            detail="전송 무결성 오류: X-File-SHA256 과 본문 SHA-256 불일치",
        )
    if claimed_size is not None and claimed_size != len(content):
        _logger.warning(
            "agent size mismatch: ip=%s file=%s claimed=%s actual=%s",
            client_ip, filename, claimed_size, len(content),
        )
        _record_agent_history(
            client_ip, filename, "fail",
            f"전송 크기 불일치: claimed={claimed_size} actual={len(content)}",
            source_path, binary_digest,
        )
        raise HTTPException(status_code=422, detail="전송 크기 불일치")

    # 입구에서 동일 바이너리 빠른 차단 (전체 파싱 비용 절감)
    hash_dup = DBService.find_duplicate_by_content_hash(binary_digest)
    if hash_dup.get("is_duplicate"):
        msg = f"DB 중복(동일 파일): {hash_dup.get('origin_file')}"
        _record_agent_history(client_ip, filename, "skipped", msg, source_path, binary_digest)
        return {
            "status": "skipped",
            "message": msg,
            "file": filename,
            "source_path": source_path,
            "sha256": binary_digest,
        }

    label = f"agent:{source_path}" if source_path else "agent"
    try:
        result = IndexingService.index_bytes(filename, content, source_label=label)
    except Exception as exc:
        _record_agent_history(client_ip, filename, "fail", f"색인 실패: {exc}", source_path, binary_digest)
        raise HTTPException(status_code=500, detail=f"색인 실패: {exc}") from exc

    _record_agent_history(
        client_ip,
        filename,
        result.get("status", "unknown"),
        result.get("message", ""),
        source_path,
        binary_digest,
    )

    result["source_path"] = source_path
    result.setdefault("sha256", binary_digest)
    return result