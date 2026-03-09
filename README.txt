========================================
 파일정리 프로그램 v2.1
========================================

[ 개요 ]
다운로드 폴더 등의 파일을 자동으로 정리하는 Windows GUI 프로그램입니다.
중복 제거, 차단 해제, 확장자별 분류, 파일명 정규화 기능을 제공합니다.


[ 파일 구성 ]
  file_organizer.py     - GUI 진입점 (메인 스크립트)
  engine.py             - 파일 정리 엔진 (비즈니스 로직)
  terms.json            - 파일명 변환 용어 사전 (IT 약어 등)
  ext_descriptions.json - 확장자 설명 데이터
  build.bat             - PyInstaller exe 빌드 스크립트
  README.txt            - 이 파일


[ 기능 설명 ]
  1. 중복파일 제거  - MD5/SHA-256 3단계 해시 비교, 보존/삭제 선택 가능
  2. 차단 해제      - Zone.Identifier 스트림 제거 (Windows 전용)
  3. Util/프로젝트  - 실행파일·소스코드·코드 프로젝트 자동 분류
  4. 확장자별 분류  - 확장자 폴더로 정리, 영상·문서는 주제별 하위 폴더 생성
  5. 파일명 변환    - IT 용어 정규화 (예: youtube → YouTube)


[ 실행 방법 ]

  ■ 소스로 직접 실행 (Python 필요)
      python file_organizer.py

  ■ exe 빌드 후 실행
      1. build.bat 실행 (더블클릭)
      2. dist\FileOrganizer_v2.exe 실행


[ exe 빌드 요구사항 ]
  - Python 3.8 이상
  - PyInstaller (build.bat이 자동 설치)

  build.bat 실행 시 자동으로 아래 옵션이 적용됩니다:
    --onefile              : 단일 exe 파일로 생성
    --windowed             : 콘솔 창 없이 GUI만 표시
    --hidden-import engine : engine 모듈 명시적 포함
    --add-data terms.json;.
    --add-data ext_descriptions.json;.
    --add-data engine.py;.

  결과물: dist\FileOrganizer_v2.exe


[ 주의사항 ]
  - 기본 작업 경로는 E:\ 로 설정되어 있습니다.
    실행 후 "찾아보기" 버튼으로 원하는 경로를 선택하세요.
  - 작업 로그는 작업 경로 내 _Log\ 폴더에 저장됩니다.
  - 전체 실행 전 중요한 파일은 반드시 백업하세요.


[ v2.1 주요 수정 사항 ]
  - 삭제 시 권한 부족 오류 수정 (읽기전용 자동 해제)
  - 선택 삭제가 전체 삭제로 처리되던 버그 수정
  - 검색 기록 자동 저장 (_Log/search_history.json)
  - 진행률 % 표시 추가
  - Util 이동 실패 시 copy+delete fallback 적용
  - 폰트 깨짐 현상 수정 (fallback 체인)
  - 파일명 변환 빈 결과 방지
  - 빈 폴더 반복 삭제 (시스템 파일 무시)
  - 다이얼로그 표시 중 다른 작업 실행 방지 (3차 검토)

========================================
