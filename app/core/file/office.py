import io
from docx import Document
from pptx import Presentation

def parse_word(content: bytes) -> str:
    try:
        doc = Document(io.BytesIO(content))
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        return f"Word 파싱 에러: {str(e)}"

def parse_pptx(content: bytes) -> str:
    try:
        prs = Presentation(io.BytesIO(content))
        text = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text.append(shape.text)
        return "\n".join(text)
    except Exception as e:
        return f"PPT 파싱 에러: {str(e)}"