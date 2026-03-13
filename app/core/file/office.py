import io
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pptx import Presentation

def _extract_text(content: bytes, ext: str) -> str:
    """
    Office 파일(.docx, .pptx)에서 텍스트를 추출하는 메인 핸들러.
    """
    if ext == 'docx':
        return _parse_word(content)
    elif ext in ['pptx', 'ppt']:
        return _parse_pptx(content)
    return f"지원하지 않는 오피스 파일 형식입니다: .{ext}"


def _parse_word(content: bytes) -> str:
    """
    Word(.docx) 파일에서 텍스트를 추출합니다.
    - 문단(Paragraph)과 표(Table)를 순서대로 순회하며 추출하여 문맥을 보존합니다.
    """
    try:
        doc = Document(io.BytesIO(content))
        text_result = ["[[Page 1]]"]

        # 문서 본문의 자식 요소들을 순서대로 순회 (문단 + 표)
        for element in doc.element.body:
            # 1. 문단(Paragraph) 처리
            if element.tag.endswith('p'):
                para = Paragraph(element, doc)
                if para.text.strip():
                    text_result.append(para.text.strip())
            
            # 2. 표(Table) 처리
            elif element.tag.endswith('tbl'):
                table = Table(element, doc)
                for row in table.rows:
                    # 셀 내용을 파이프(|)로 구분하여 표 구조 표현
                    row_cells = [cell.text.strip().replace('\n', ' ') for cell in row.cells]
                    # 빈 행이 아니면 추가
                    if any(row_cells):
                        text_result.append(" | ".join(row_cells))

        return "\n\n".join(text_result)
    except Exception as e:
        return f"Word 파싱 에러: {str(e)}"


def _parse_pptx(content: bytes) -> str:
    """
    PowerPoint(.pptx) 파일에서 텍스트를 추출합니다.
    - 슬라이드별 구분, 도형(TextFrame), 표(Table), 노트(Notes)를 모두 포함합니다.
    - 도형을 위치(top, left) 기준으로 정렬하여 읽는 순서를 보정합니다.
    """
    try:
        prs = Presentation(io.BytesIO(content))
        text_result = []

        for i, slide in enumerate(prs.slides, 1):
            slide_texts = [f"[[Page {i}]] ## Slide {i}"]
            
            # 읽는 순서(좌상단 -> 우하단)로 도형 정렬
            # shape.top/left가 없는 경우(그룹 등)를 대비해 안전하게 처리
            shapes_with_pos = []
            for s in slide.shapes:
                top = getattr(s, 'top', 0) or 0
                left = getattr(s, 'left', 0) or 0
                shapes_with_pos.append((top, left, s))
            
            sorted_shapes = sorted(shapes_with_pos, key=lambda x: (x[0], x[1]))

            for _, _, shape in sorted_shapes:
                # 1. 텍스트 상자 (TextFrame)
                if hasattr(shape, "text_frame") and shape.text_frame and shape.text.strip():
                    slide_texts.append(shape.text.strip())
                
                # 2. 표 (Table)
                if hasattr(shape, "has_table") and shape.has_table:
                    for row in shape.table.rows:
                        row_data = []
                        for cell in row.cells:
                            # 셀 내부 텍스트 추출 (text_frame 사용)
                            cell_text = cell.text_frame.text.strip().replace('\n', ' ') if hasattr(cell, "text_frame") else ""
                            row_data.append(cell_text)
                        
                        if any(row_data):
                            slide_texts.append(" | ".join(row_data))

            # 3. 슬라이드 노트 (발표자 메모) 추출
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame and slide.notes_slide.notes_text_frame.text.strip():
                notes = slide.notes_slide.notes_text_frame.text.strip()
                slide_texts.append(f"\n[발표자 노트]\n{notes}")

            if len(slide_texts) > 1:
                text_result.append("\n".join(slide_texts))

        return "\n\n".join(text_result)
    except Exception as e:
        return f"PPT 파싱 에러: {str(e)}"