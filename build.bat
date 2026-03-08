@echo off
chcp 65001 >nul
echo ========================================
echo 파일정리 프로그램 v2.0 빌드
echo ========================================
echo.

REM PyInstaller 설치 확인
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [1/3] PyInstaller 설치 중...
    pip install pyinstaller
) else (
    echo [1/3] PyInstaller 확인 완료
)

echo [2/3] 빌드 시작...
pyinstaller --noconfirm --onefile --windowed ^
    --name "FileOrganizer_v2" ^
    --hidden-import engine ^
    --add-data "terms.json;." ^
    --add-data "ext_descriptions.json;." ^
    --add-data "engine.py;." ^
    --icon "NONE" ^
    file_organizer.py

echo [3/3] 빌드 확인...
if exist "dist\FileOrganizer_v2.exe" (
    echo.
    echo ========================================
    echo 빌드 완료: dist\FileOrganizer_v2.exe
    echo ========================================
    echo.
    echo [단일 파일 모드]
    echo   terms.json, ext_descriptions.json 은 exe 내부에 번들됨.
    echo   exe 옆에 같은 이름의 파일을 두면 외부 파일을 우선 사용합니다.
) else (
    echo.
    echo [오류] 빌드 실패!
)

echo.
pause
