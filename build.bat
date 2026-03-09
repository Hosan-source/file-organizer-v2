@echo off
chcp 65001 > nul
echo ========================================
echo  파일정리 프로그램 v2.1 - PyInstaller 빌드
echo ========================================
echo.

:: Python / PyInstaller 확인
python --version > nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않거나 PATH에 등록되지 않았습니다.
    pause
    exit /b 1
)

pyinstaller --version > nul 2>&1
if errorlevel 1 (
    echo [알림] PyInstaller가 없습니다. 설치 중...
    pip install pyinstaller
    if errorlevel 1 (
        echo [오류] PyInstaller 설치 실패.
        pause
        exit /b 1
    )
)

:: 이전 빌드 정리
echo [1/3] 이전 빌드 파일 정리 중...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist FileOrganizer_v2.spec del /q FileOrganizer_v2.spec

:: PyInstaller 빌드
echo [2/3] 빌드 시작...
pyinstaller ^
    --name FileOrganizer_v2 ^
    --onefile ^
    --windowed ^
    --hidden-import engine ^
    --add-data "terms.json;." ^
    --add-data "ext_descriptions.json;." ^
    --add-data "engine.py;." ^
    file_organizer.py

if errorlevel 1 (
    echo.
    echo [오류] 빌드 실패. 위 오류 메시지를 확인하세요.
    pause
    exit /b 1
)

:: 결과 확인
echo [3/3] 빌드 완료 확인...
if exist "dist\FileOrganizer_v2.exe" (
    echo.
    echo ========================================
    echo  빌드 성공!
    echo  결과물: dist\FileOrganizer_v2.exe
    echo ========================================
    explorer dist
) else (
    echo [오류] dist\FileOrganizer_v2.exe 파일을 찾을 수 없습니다.
)

pause
