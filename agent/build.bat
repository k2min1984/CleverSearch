@echo off
REM ====================================================
REM  CleverSearch Agent - PyInstaller 빌드 스크립트
REM  결과물: dist\CleverSearchAgent.exe (단일 파일, 설치 불필요)
REM  사용:  agent 폴더에서 build.bat 실행
REM ====================================================
setlocal
cd /d "%~dp0"

echo.
echo [1/3] 의존성 설치
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [ERR] 의존성 설치 실패
    exit /b 1
)

echo.
echo [2/3] 빌드 시작
pyinstaller --noconfirm --clean --onefile --windowed ^
    --name CleverSearchAgent ^
    --hidden-import=watchdog.observers.read_directory_changes ^
    --collect-submodules httpx ^
    main.py
if errorlevel 1 (
    echo [ERR] 빌드 실패
    exit /b 1
)

echo.
echo [3/3] 빌드 완료
echo   -> %CD%\dist\CleverSearchAgent.exe
echo.
echo 단일 exe 로 배포 가능합니다 (Python/설치 불필요).
endlocal
