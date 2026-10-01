@echo off
setlocal
chcp 65001 > nul

REM ====================================================================
REM CleverSearch Local Cert Generator — exe 빌드
REM 결과물: tools\cert_gen\dist\CleverSearchCertGen.exe (단일 파일)
REM 사전 준비: 같은 PC 에 Python 3.10+ + pip install pyinstaller cryptography
REM ====================================================================

set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"

where python > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 이 PATH 에 없습니다.
    pause & exit /b 1
)

echo [STEP] 의존성 설치
python -m pip install --upgrade pip
python -m pip install pyinstaller cryptography

echo [STEP] PyInstaller 빌드 (--onefile --windowed)
cd /d "%HERE%"
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name CleverSearchCertGen ^
    --hidden-import cryptography ^
    --hidden-import cryptography.hazmat.bindings._rust ^
    main.py

if errorlevel 1 (
    echo [ERROR] 빌드 실패
    pause & exit /b 1
)

echo.
echo [DONE] %HERE%\dist\CleverSearchCertGen.exe
echo.
endlocal
