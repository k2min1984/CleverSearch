"""
[이유] 
이 파일은 app/core/file 폴더를 파키지로 인식하게 하며,
외부(file.py)에서 'from app.core.file import excel, hwp...' 처럼 
직관적으로 모듈을 불러올 수 있도록 통로 역할을 합니다.
app/core/file 패키지 초기화 모듈.

이 파일은 app/core/file 폴더를 패키지로 인식하게 하며,
외부에서 'from app.core.file import excel, hwp...' 처럼
직관적으로 하위 모듈을 불러올 수 있도록 통로 역할을 합니다.
"""

# 각 개별 파서 모듈들을 패키지 범위로 노출시킵니다.
from . import excel
from . import hwp
from . import image
from . import office
from . import pdf
from . import office
from . import image

# 외부에서 'from app.core.file import *' 를 사용할 때 허용할 목록을 정의합니다.
__all__ = ['excel', 'hwp', 'pdf', 'office', 'image']
__all__ = ['excel', 'hwp', 'image', 'office', 'pdf']