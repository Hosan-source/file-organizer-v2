# -*- coding: utf-8 -*-
"""
========================================
파일정리 프로그램 v2.1 - Engine
비즈니스 로직 (파일 조작, 해시, 분류)
========================================
v2.0 → v2.1 수정사항:
  #1  삭제 시 권한부족 → 읽기전용 해제 + 재시도
  #2  선택삭제 전체삭제 → delete_set → file_actions dict 방식 (GUI측)
  #3  검색기록 저장 → search_history.json 자동 저장
  #5  진행률 % → 콜백에 퍼센트 포함
  #6  유틸 이동실패 → shutil.move 권한 오류 시 copy+delete fallback
  #7  확장자 분류 오류 → 동일 fallback 적용
  #9  파일명 변환 → CJK 혼합 처리 개선, 빈 결과 방지
  #10 중복 폴더 미제거 → _remove_empty_dirs 다중패스 + 시스템파일 무시
  #11 작업속도 → 진행률 업데이트 빈도 감소
"""
import os
import sys
import json
import hashlib
import shutil
import re
import stat
import subprocess
import logging
from datetime import datetime
from collections import defaultdict
from typing import Callable, Optional, List, Tuple, Dict


def resource_path(relative_path: str) -> str:
    """리소스 경로: exe 옆 파일 우선 → 번들 내부 → 스크립트 디렉토리"""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(exe_dir, relative_path)
    if os.path.exists(local):
        return local
    if getattr(sys, '_MEIPASS', None):
        return os.path.join(sys._MEIPASS, relative_path)
    return local


def writable_path(relative_path: str) -> str:
    """쓰기 가능한 경로: exe 옆(frozen) 또는 스크립트 디렉토리"""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)


# ─── Constants ───
UTIL_EXTENSIONS = {'.exe', '.msi', '.bat', '.cmd', '.ps1', '.vbs', '.reg', '.inf', '.iso'}

CODE_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.c', '.cpp', '.h', '.hpp',
    '.cs', '.java', '.go', '.rs', '.rb', '.pl', '.lua', '.r',
    '.swift', '.kt', '.scala', '.php', '.sh', '.zsh', '.fish',
    '.vue', '.svelte',
    '.bat', '.cmd', '.vbs', '.ps1', '.m',
}

WEB_CONTENT_EXTENSIONS = {'.html', '.css', '.scss', '.sass', '.less'}
PROJECT_CODE_EXTENSIONS = CODE_EXTENSIONS | WEB_CONTENT_EXTENSIONS

PROJECT_MARKERS = {
    'package.json', 'requirements.txt', 'setup.py', 'pyproject.toml',
    'Cargo.toml', 'go.mod', 'pom.xml', 'build.gradle', 'Makefile',
    'CMakeLists.txt', '.git', '.gitignore', 'node_modules',
    'Dockerfile', 'docker-compose.yml', '.sln', '.csproj',
    '.vscode', '.idea', 'Gemfile', 'Pipfile', 'composer.json',
}

VIDEO_EXTENSIONS = {
    '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm',
    '.m4v', '.mpg', '.mpeg', '.3gp',
}

DOCUMENT_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.hwp', '.hwpx', '.txt', '.rtf', '.odt', '.ods', '.odp',
    '.csv', '.md',
}

EXCLUDED_FOLDERS = {'Util', '기타', '_Log'}

# [#10] 빈 폴더 판정 시 무시할 시스템 파일 (클래스 밖 상수)
_SYSTEM_JUNK_FILES = frozenset({'.DS_Store', 'Thumbs.db', 'desktop.ini', '._.DS_Store'})

# 크로스플랫폼 기본 경로
if sys.platform == 'win32':
    DEFAULT_BASE = 'E:\\'
elif sys.platform == 'darwin':
    DEFAULT_BASE = os.path.expanduser('~/Downloads')
else:
    DEFAULT_BASE = os.path.expanduser('~/Downloads')

HASH_CHUNK_SIZE = 65536

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {'CON', 'PRN', 'AUX', 'NUL',
                      'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
                      'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}


def sanitize_name(name: str) -> str:
    """파일명/폴더명에서 금지 문자 제거 + path traversal 방지"""
    name = os.path.basename(name)
    name = name.replace('..', '_')
    name = _INVALID_FILENAME_CHARS.sub('_', name)
    base = name.split('.')[0].upper()
    if base in _WINDOWS_RESERVED:
        name = '_' + name
    name = name.strip(' .')
    return name or '_unnamed'


# ─── 콜백 타입 ───
ProgressCallback = Callable[[int, str], None]
LogCallback = Callable[[str], None]


class FileOrganizer:
    """파일 정리 엔진 v2.1"""

    def __init__(self, base_path: str,
                 log_callback: Optional[LogCallback] = None,
                 progress_callback: Optional[ProgressCallback] = None):
        self.base_path = base_path
        self.log_dir = os.path.join(base_path, '_Log')
        self.log_callback = log_callback or (lambda msg: None)
        self.progress_callback = progress_callback or (lambda pct, msg: None)
        self._cancel = False

        os.makedirs(self.log_dir, exist_ok=True)

        log_file = os.path.join(self.log_dir, f'log_{datetime.now():%Y%m%d_%H%M%S}.log')
        self.file_logger = logging.getLogger(f'FileOrganizer_{id(self)}')
        self.file_logger.setLevel(logging.INFO)
        for h in self.file_logger.handlers[:]:
            self.file_logger.removeHandler(h)
        handler = logging.FileHandler(log_file, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s', '%Y-%m-%d %H:%M:%S'))
        self.file_logger.addHandler(handler)

        self.terms = self._load_terms()
        self.ext_descriptions = self._load_json('ext_descriptions.json')

        # [#3] 검색기록 로드
        self._history_path = os.path.join(self.log_dir, 'search_history.json')
        self.search_history = self._load_search_history()

    def cancel(self):
        self._cancel = True

    def reset_cancel(self):
        self._cancel = False

    def _log(self, msg: str):
        self.file_logger.info(msg)
        self.log_callback(msg)

    def _progress(self, pct: int, msg: str = ''):
        """[#5] 진행률에 퍼센트 포함"""
        pct = min(pct, 100)
        display_msg = f'{msg} ({pct}%)' if msg and pct < 100 else msg
        self.progress_callback(pct, display_msg)

    def _load_json(self, filename: str) -> dict:
        try:
            with open(resource_path(filename), 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self._log(f'[경고] {filename} 로드 실패: {e}')
            return {}
        except Exception as e:
            self._log(f'[경고] {filename} 로드 실패: {e}')
            return {}

    def _load_terms(self) -> Dict[str, str]:
        data = self._load_json('terms.json')
        if not data:
            return {}
        if 'terms' in data and isinstance(data['terms'], list):
            return {t.lower(): t for t in data['terms']}
        if isinstance(data, list):
            return {t.lower(): t for t in data}
        if isinstance(data, dict):
            return {k.lower(): v for k, v in data.items()}
        return {}

    def save_terms(self, terms_dict: Dict[str, str]):
        path = writable_path('terms.json')
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(terms_dict, f, ensure_ascii=False, indent=2)
            self.terms = {k.lower(): v for k, v in terms_dict.items()}
        except (PermissionError, OSError) as e:
            self._log(f'[오류] terms.json 저장 실패: {e}')

    # ═══════════════════════════════════════
    # [#3] 검색기록 저장/로드
    # ═══════════════════════════════════════
    def _load_search_history(self) -> list:
        try:
            if os.path.exists(self._history_path):
                with open(self._history_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            pass
        return []

    def save_search_history(self, entry: dict):
        """검색기록 저장 - 최대 50개 유지"""
        self.search_history.append(entry)
        if len(self.search_history) > 50:
            self.search_history = self.search_history[-50:]
        try:
            with open(self._history_path, 'w', encoding='utf-8') as f:
                json.dump(self.search_history, f, ensure_ascii=False, indent=2)
        except (PermissionError, OSError) as e:
            self._log(f'[경고] 검색기록 저장 실패: {e}')

    def get_search_history(self) -> list:
        return self.search_history

    # ═══════════════════════════════════════
    # 유틸리티
    # ═══════════════════════════════════════
    def _is_excluded(self, path: str) -> bool:
        rel = os.path.relpath(path, self.base_path)
        top = rel.split(os.sep)[0]
        return top in EXCLUDED_FOLDERS

    def _force_remove_readonly(self, path: str):
        """[#1] 읽기전용 속성 해제"""
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass

    def _safe_delete(self, filepath: str, use_trash: bool = False) -> bool:
        """[#1] 안전한 삭제 - 권한 오류 시 읽기전용 해제 후 재시도"""
        try:
            if use_trash:
                self._send_to_trash(filepath)
            else:
                os.remove(filepath)
            return True
        except PermissionError:
            self._force_remove_readonly(filepath)
            try:
                os.remove(filepath)
                return True
            except PermissionError:
                self._log(f'  [오류] 권한 부족 (읽기전용 해제 실패): {filepath}')
                return False
            except OSError as e:
                self._log(f'  [오류] 삭제 실패: {filepath}: {e}')
                return False
        except FileNotFoundError:
            self._log(f'  [오류] 파일 없음: {filepath}')
            return False
        except OSError as e:
            self._log(f'  [오류] 삭제 실패: {filepath}: {e}')
            return False

    def _safe_move(self, src: str, dst_dir: str, filename: str = None) -> Optional[str]:
        """[#6] 이동 실패 시 copy+delete fallback"""
        os.makedirs(dst_dir, exist_ok=True)
        name = filename or os.path.basename(src)
        name = os.path.basename(name)
        name = _INVALID_FILENAME_CHARS.sub('_', name) if name else '_unnamed'
        base, ext = os.path.splitext(name)
        dst = os.path.join(dst_dir, name)
        counter = 2
        while os.path.exists(dst):
            dst = os.path.join(dst_dir, f'{base}({counter}){ext}')
            counter += 1
        try:
            shutil.move(src, dst)
            return dst
        except PermissionError:
            # [#6] fallback: 복사 후 원본 삭제 시도
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                # 원본 삭제 시도
                self._force_remove_readonly(src)
                try:
                    if os.path.isdir(src):
                        shutil.rmtree(src, onerror=self._rmtree_onerror)
                    else:
                        os.remove(src)
                except OSError:
                    self._log(f'  [경고] 복사 완료, 원본 삭제 실패: {src}')
                return dst
            except (PermissionError, OSError) as e:
                self._log(f'  [오류] 이동/복사 모두 실패 (액세스 거부): {src}: {e}')
                return None
        except FileNotFoundError:
            self._log(f'  [오류] 파일 없음: {src}')
            return None
        except OSError as e:
            self._log(f'  [오류] 이동 실패: {src} -> {dst}: {e}')
            return None

    @staticmethod
    def _rmtree_onerror(func, path, exc_info):
        """shutil.rmtree 에러 핸들러 - 읽기전용 해제 후 재시도"""
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)
        except OSError:
            pass

    def _collect_files(self) -> List[str]:
        """대상 파일 수집 (제외 폴더 skip)"""
        files = []
        for root, dirs, filenames in os.walk(self.base_path):
            dirs[:] = [d for d in dirs if not self._is_excluded(os.path.join(root, d))]
            for fn in filenames:
                fp = os.path.join(root, fn)
                if not self._is_excluded(fp):
                    files.append(fp)
        return files

    def _remove_empty_dirs(self):
        """[#10] 중복 폴더 제거 - 여러 패스 반복, 시스템 junk 파일 무시"""
        max_passes = 10
        for _ in range(max_passes):
            removed_any = False
            for root, dirs, files in os.walk(self.base_path, topdown=False):
                if self._is_excluded(root) or root == self.base_path:
                    continue
                try:
                    entries = os.listdir(root)
                    real_entries = [e for e in entries if e not in _SYSTEM_JUNK_FILES]
                    if not real_entries:
                        for sf in entries:
                            try:
                                os.remove(os.path.join(root, sf))
                            except OSError:
                                pass
                        os.rmdir(root)
                        self._log(f'[폴더삭제] {root}')
                        removed_any = True
                except OSError:
                    pass
            if not removed_any:
                break

    # ═══════════════════════════════════════
    # 1. 중복파일
    # ═══════════════════════════════════════
    def find_duplicates(self) -> Dict[str, List[str]]:
        self._log('=' * 50)
        self._log('[1] 중복파일 검색 시작...')
        files = self._collect_files()
        total = len(files)
        if total == 0:
            self._progress(100, '파일 없음')
            return {}

        # Stage 1: group by size
        self._progress(0, '파일 크기 분석 중...')
        size_groups = defaultdict(list)
        for i, fp in enumerate(files):
            if self._cancel:
                return {}
            try:
                sz = os.path.getsize(fp)
                if sz > 0:
                    size_groups[sz].append(fp)
            except OSError:
                pass
            if i % 100 == 0 or i == total - 1:
                self._progress(int(i / total * 30), f'크기 분석: {i + 1}/{total}')

        candidates = {sz: fps for sz, fps in size_groups.items() if len(fps) > 1}
        self._log(f'  크기 중복 그룹: {len(candidates)}개')

        # Stage 2: partial hash
        self._progress(30, '부분 해시 비교 중...')
        partial_groups = defaultdict(list)
        items = list(candidates.items())
        for idx, (sz, fps) in enumerate(items):
            if self._cancel:
                return {}
            for fp in fps:
                try:
                    with open(fp, 'rb') as f:
                        h = hashlib.md5(f.read(HASH_CHUNK_SIZE)).hexdigest()
                    partial_groups[(sz, h)].append(fp)
                except OSError:
                    pass
            if idx % 20 == 0 or idx == len(items) - 1:
                self._progress(30 + int(idx / max(len(items), 1) * 30),
                               f'부분 해시: {idx + 1}/{len(items)}')

        candidates2 = {k: v for k, v in partial_groups.items() if len(v) > 1}

        # Stage 3: full SHA-256
        self._progress(60, '전체 해시 비교 중...')
        full_groups = defaultdict(list)
        items2 = list(candidates2.values())
        for idx, fps in enumerate(items2):
            if self._cancel:
                return {}
            for fp in fps:
                try:
                    sha = hashlib.sha256()
                    with open(fp, 'rb') as f:
                        for chunk in iter(lambda: f.read(65536), b''):
                            sha.update(chunk)
                    full_groups[sha.hexdigest()].append(fp)
                except OSError:
                    pass
            if idx % 10 == 0 or idx == len(items2) - 1:
                self._progress(60 + int(idx / max(len(items2), 1) * 35),
                               f'전체 해시: {idx + 1}/{len(items2)}')

        duplicates = {h: fps for h, fps in full_groups.items() if len(fps) > 1}
        total_dup_files = sum(len(fps) - 1 for fps in duplicates.values())
        self._log(f'  최종 중복 그룹: {len(duplicates)}개 (삭제 대상 {total_dup_files}개)')
        self._progress(100, '중복파일 검색 완료')

        # [#3] 검색기록 저장
        self.save_search_history({
            'type': 'duplicate_search',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'path': self.base_path,
            'total_files': total,
            'duplicate_groups': len(duplicates),
            'duplicate_files': total_dup_files,
        })

        return duplicates

    def delete_duplicates(self, delete_list: List[str], use_trash: bool = False) -> int:
        """[#1] 권한 오류 개선 + [#2] 리스트 복사본 사용"""
        self._log('[중복삭제] 시작...')
        to_delete = list(delete_list)  # 원본 변경 방지
        total = len(to_delete)
        if total == 0:
            self._log('[중복삭제] 삭제할 파일 없음')
            return 0
        deleted = 0
        errors = 0
        for i, fp in enumerate(to_delete):
            if self._cancel:
                return deleted
            if self._safe_delete(fp, use_trash):
                deleted += 1
                self._log(f'  삭제: {fp}')
            else:
                errors += 1
            self._progress(int((i + 1) / total * 100), f'삭제: {i + 1}/{total}')

        self._log(f'[중복삭제] {deleted}/{total}개 완료' +
                  (f' ({errors}개 오류)' if errors else ''))
        self._progress(100, f'중복삭제 완료 ({deleted}/{total})')
        return deleted

    def _send_to_trash(self, filepath: str):
        """Windows 휴지통으로 이동"""
        if sys.platform != 'win32':
            os.remove(filepath)
            return
        try:
            import ctypes
            from ctypes import wintypes

            shell32 = ctypes.windll.shell32

            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ('hwnd', wintypes.HWND),
                    ('wFunc', ctypes.c_uint),
                    ('pFrom', ctypes.c_wchar_p),
                    ('pTo', ctypes.c_wchar_p),
                    ('fFlags', ctypes.c_ushort),
                    ('fAnyOperationsAborted', wintypes.BOOL),
                    ('hNameMappings', ctypes.c_void_p),
                    ('lpszProgressTitle', ctypes.c_wchar_p),
                ]

            FO_DELETE = 3
            FOF_ALLOWUNDO = 0x0040
            FOF_NOCONFIRMATION = 0x0010
            FOF_SILENT = 0x0004

            op = SHFILEOPSTRUCTW()
            op.wFunc = FO_DELETE
            op.pFrom = filepath + '\0'
            op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
            result = shell32.SHFileOperationW(ctypes.byref(op))
            if result != 0:
                raise OSError(f'SHFileOperation 실패: {result}')
        except (ImportError, AttributeError, OSError):
            os.remove(filepath)

    # ═══════════════════════════════════════
    # 2. 차단해제
    # ═══════════════════════════════════════
    def unblock_files(self) -> int:
        self._log('=' * 50)
        self._log('[2] 차단해제 시작...')

        if sys.platform != 'win32':
            self._log('  [건너뜀] 차단해제는 Windows 전용 기능입니다.')
            self._progress(100, '차단해제: Windows 전용')
            return 0

        files = self._collect_files()
        total = len(files)
        if total == 0:
            self._progress(100, '차단해제: 파일 없음')
            return 0
        unblocked = 0

        for i, fp in enumerate(files):
            if self._cancel:
                return unblocked
            try:
                zone = fp + ':Zone.Identifier'
                if os.path.exists(zone):
                    try:
                        subprocess.run(
                            ['powershell', '-NoProfile', '-Command',
                             'Unblock-File', '-LiteralPath', fp],
                            capture_output=True, timeout=10,
                            creationflags=0x08000000
                        )
                        unblocked += 1
                        self._log(f'  차단해제: {fp}')
                    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                        try:
                            os.remove(zone)
                            unblocked += 1
                            self._log(f'  차단해제(fallback): {fp}')
                        except OSError:
                            pass
            except OSError:
                pass
            if i % 50 == 0 or i == total - 1:
                self._progress(int((i + 1) / total * 100),
                               f'차단해제: {i + 1}/{total}')

        self._log(f'[차단해제] {unblocked}개 완료')
        self._progress(100, '차단해제 완료')
        return unblocked

    # ═══════════════════════════════════════
    # 3. Util / 프로젝트 분류
    # ═══════════════════════════════════════
    def _is_code_project(self, dirpath: str, max_depth: int = 2) -> bool:
        try:
            entries = set(os.listdir(dirpath))
        except OSError:
            return False

        if entries & PROJECT_MARKERS:
            return True

        if max_depth > 0:
            for entry in entries:
                subpath = os.path.join(dirpath, entry)
                if os.path.isdir(subpath) and entry not in {'.git', 'node_modules', '__pycache__', '.venv', 'venv'}:
                    try:
                        sub_entries = set(os.listdir(subpath))
                        if sub_entries & PROJECT_MARKERS:
                            return True
                    except OSError:
                        pass

        code_count = sum(1 for e in entries
                         if os.path.isfile(os.path.join(dirpath, e))
                         and os.path.splitext(e)[1].lower() in PROJECT_CODE_EXTENSIONS)
        total_count = sum(1 for e in entries if os.path.isfile(os.path.join(dirpath, e)))
        return total_count > 0 and code_count / total_count >= 0.5

    def classify_util(self) -> Tuple[int, int, int]:
        """[#6] Util 분류 - 이동실패 시 copy+delete fallback 적용"""
        self._log('=' * 50)
        self._log('[3] Util/프로젝트 분류 시작...')
        util_base = os.path.join(self.base_path, 'Util')
        moved_count = 0
        project_count = 0
        source_count = 0

        # 프로젝트 디렉토리 감지
        project_dirs = []
        for root, dirs, _ in os.walk(self.base_path):
            dirs[:] = [d for d in dirs if not self._is_excluded(os.path.join(root, d))]
            if root == self.base_path:
                continue
            if self._is_code_project(root):
                project_dirs.append(root)
                dirs.clear()

        if project_dirs:
            projects_dir = os.path.join(util_base, 'Projects')
            os.makedirs(projects_dir, exist_ok=True)
            for pdir in project_dirs:
                if self._cancel:
                    return moved_count, project_count, source_count
                dirname = os.path.basename(pdir)
                dst = os.path.join(projects_dir, dirname)
                c = 2
                while os.path.exists(dst):
                    dst = os.path.join(projects_dir, f'{dirname}({c})')
                    c += 1
                try:
                    shutil.move(pdir, dst)
                    project_count += 1
                    self._log(f'  [프로젝트] {pdir} -> {dst}')
                except PermissionError:
                    try:
                        shutil.copytree(pdir, dst)
                        shutil.rmtree(pdir, onerror=self._rmtree_onerror)
                        project_count += 1
                        self._log(f'  [프로젝트] {pdir} -> {dst} (복사방식)')
                    except (PermissionError, OSError) as e:
                        self._log(f'  [오류] 프로젝트 이동 실패 (액세스 거부): {pdir}: {e}')
                except OSError as e:
                    self._log(f'  [오류] 프로젝트 이동 실패: {pdir}: {e}')

        # 실행파일 + 개별 소스코드 분류
        files = self._collect_files()
        total = len(files)
        for i, fp in enumerate(files):
            if self._cancel:
                return moved_count, project_count, source_count
            ext = os.path.splitext(fp)[1].lower()

            if ext in UTIL_EXTENSIONS:
                dst_dir = os.path.join(util_base, ext.lstrip('.').upper())
                result = self._safe_move(fp, dst_dir)
                if result:
                    moved_count += 1
                    self._log(f'  [Util] {fp} -> {result}')
            elif ext in CODE_EXTENSIONS and ext not in UTIL_EXTENSIONS:
                ext_name = ext.lstrip('.').upper()
                dst_dir = os.path.join(util_base, 'Source', ext_name)
                result = self._safe_move(fp, dst_dir)
                if result:
                    source_count += 1
                    self._log(f'  [소스] {fp} -> {result}')

            if i % 50 == 0 or i == total - 1:
                self._progress(int((i + 1) / total * 100) if total else 100,
                               f'Util: {i + 1}/{total}')

        self._log(f'[Util] 실행파일 {moved_count}개, 프로젝트 {project_count}개, 소스 {source_count}개 완료')
        self._progress(100, 'Util 분류 완료')

        self.save_search_history({
            'type': 'util_classify',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'path': self.base_path,
            'util_files': moved_count,
            'projects': project_count,
            'source_files': source_count,
        })

        return moved_count, project_count, source_count

    # ═══════════════════════════════════════
    # 4. 확장자별 분류
    # ═══════════════════════════════════════
    _NOISE_PREFIXES = {'img', 'dsc', 'vid', 'mov', 'rec', 'screenshot', 'screen',
                        'capture', 'photo', 'pic', 'file', 'new', 'copy', 'temp',
                        'tmp', 'untitled', 'download',
                        'of', 'the', 'for', 'and', 'to', 'in', 'on', 'at', 'by'}

    def _extract_topic(self, filename: str) -> Optional[str]:
        name = os.path.splitext(filename)[0]
        if not name or name.startswith('.'):
            return None
        name = re.sub(r'\(\d+\)$', '', name)
        name = re.sub(r'[_\-]?\d{8}', '', name)
        name = re.sub(r'^\d{4}년?\s*', '', name)
        name = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name)
        name = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', name)
        tokens = re.split(r'[\s_\-\.]+', name.strip())
        for token in tokens:
            token = token.strip()
            if len(token) >= 2 and not token.isdigit():
                if token.lower() in self._NOISE_PREFIXES:
                    continue
                normalized = token.lower()
                if normalized in self.terms:
                    result = self.terms[normalized]
                elif token.isascii():
                    result = token.capitalize()
                else:
                    result = token
                result = sanitize_name(result)
                return result if result and result != '_unnamed' else None
        return None

    def _create_ext_description(self, ext_folder: str, ext_lower: str):
        desc_file = os.path.join(ext_folder, f'{ext_lower}.txt')
        if os.path.exists(desc_file):
            return
        info = self.ext_descriptions.get(ext_lower)
        if info:
            content = (f"확장자: .{ext_lower}\n"
                       f"이름: {info.get('name', ext_lower.upper())}\n"
                       f"{'─' * 40}\n"
                       f"설명: {info.get('description', '')}\n"
                       f"용도: {info.get('usage', '')}\n"
                       f"열기: {info.get('programs', '')}\n")
        else:
            content = (f"확장자: .{ext_lower}\n"
                       f"이 폴더에는 .{ext_lower} 확장자 파일이 저장되어 있습니다.\n")
        try:
            with open(desc_file, 'w', encoding='utf-8') as f:
                f.write(content)
        except OSError:
            pass

    def classify_by_extension(self) -> int:
        """[#7] 확장자별 분류 - 권한 오류 시 fallback 적용"""
        self._log('=' * 50)
        self._log('[4] 확장자별 분류 시작...')
        files = self._collect_files()
        total = len(files)
        if total == 0:
            self._log('[확장자 분류] 분류할 파일 없음')
            self._progress(100, '확장자별 분류: 파일 없음')
            return 0
        moved = 0
        errors = 0
        etc_dir = os.path.join(self.base_path, '기타')

        for i, fp in enumerate(files):
            if self._cancel:
                return moved
            ext = os.path.splitext(fp)[1].lower()
            if ext in UTIL_EXTENSIONS or ext in CODE_EXTENSIONS:
                if i % 50 == 0 or i == total - 1:
                    self._progress(int((i + 1) / total * 100),
                                   f'분류: {i + 1}/{total}')
                continue

            filename = os.path.basename(fp)
            if ext == '' or ext == '.':
                result = self._safe_move(fp, etc_dir)
                if result:
                    moved += 1
                    self._log(f'  [기타] {fp} -> {result}')
                else:
                    errors += 1
            else:
                ext_name = ext.lstrip('.').upper()
                ext_lower = ext.lstrip('.').lower()
                ext_folder = os.path.join(self.base_path, ext_name)
                os.makedirs(ext_folder, exist_ok=True)
                self._create_ext_description(ext_folder, ext_lower)

                if ext in VIDEO_EXTENSIONS or ext in DOCUMENT_EXTENSIONS:
                    topic = self._extract_topic(filename)
                    dst_dir = os.path.join(ext_folder, topic) if topic else ext_folder
                else:
                    dst_dir = ext_folder

                result = self._safe_move(fp, dst_dir)
                if result:
                    moved += 1
                    self._log(f'  [{ext_name}] {fp} -> {result}')
                else:
                    errors += 1

            if i % 50 == 0 or i == total - 1:
                self._progress(int((i + 1) / total * 100),
                               f'분류: {i + 1}/{total}')

        self._log(f'[확장자 분류] {moved}개 완료' +
                  (f' ({errors}개 오류)' if errors else ''))
        self._progress(100, '확장자별 분류 완료')

        self.save_search_history({
            'type': 'ext_classify',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'path': self.base_path,
            'moved_files': moved,
            'errors': errors,
        })

        return moved

    # ═══════════════════════════════════════
    # 5. 파일명 변환
    # ═══════════════════════════════════════
    def _is_cjk(self, text: str) -> bool:
        for ch in text:
            if '\u3400' <= ch <= '\u9fff' or '\uac00' <= ch <= '\ud7a3':
                return True
        return False

    def _convert_filename(self, name: str) -> str:
        """[#9] 파일명 변환 개선 - CJK 혼합 처리, 빈 결과 방지"""
        base, ext = os.path.splitext(name)
        ext = ext.lower()

        if base.startswith('.') or not base:
            return name

        if self._is_cjk(base):
            return base + ext

        parts = re.split(r'([\s_\-\.]+)', base)
        sorted_terms = sorted(self.terms.items(), key=lambda x: len(x[0]), reverse=True)

        new_parts = []
        for part in parts:
            if re.match(r'^[\s_\-\.]+$', part):
                new_parts.append(part)
                continue
            if not part:
                continue

            lower = part.lower()

            # 1) 정확히 매칭
            if lower in self.terms:
                new_parts.append(self.terms[lower])
                continue

            # 2) 복합어 내 부분 매칭 (3글자 이상 용어만)
            remaining = part
            result_pieces = []
            while remaining:
                matched = False
                remaining_lower = remaining.lower()
                for term_lower, term_original in sorted_terms:
                    if len(term_lower) >= 3 and term_lower in remaining_lower:
                        idx = remaining_lower.find(term_lower)
                        if idx > 0:
                            result_pieces.append(remaining[:idx].capitalize())
                        result_pieces.append(term_original)
                        remaining = remaining[idx + len(term_lower):]
                        matched = True
                        break
                if not matched:
                    if remaining:
                        result_pieces.append(remaining.capitalize())
                    break

            if result_pieces:
                new_parts.append(''.join(result_pieces))
            else:
                new_parts.append(part.capitalize())

        new_base = ''.join(new_parts)
        new_base = _INVALID_FILENAME_CHARS.sub('_', new_base)

        # 변환 결과가 비면 원본 유지
        if not new_base or not new_base.strip('_. '):
            return name

        return new_base + ext

    def preview_renames(self) -> List[Tuple[str, str, str]]:
        self._log('=' * 50)
        self._log('[5] 파일명 변환 미리보기...')
        renames = []
        files_list = []
        for root, dirs, filenames in os.walk(self.base_path):
            dirs[:] = [d for d in dirs if not self._is_excluded(os.path.join(root, d))]
            for fn in filenames:
                fp = os.path.join(root, fn)
                if not self._is_excluded(fp):
                    files_list.append((root, fn))

        total = len(files_list)
        for i, (root, fn) in enumerate(files_list):
            if self._cancel:
                return renames
            fp = os.path.join(root, fn)
            new_name = self._convert_filename(fn)
            if new_name != fn:
                renames.append((fp, fn, new_name))
            if i % 100 == 0 or i == total - 1:
                self._progress(int((i + 1) / total * 100) if total else 100,
                               f'미리보기: {i + 1}/{total}')

        self._log(f'  변환 대상: {len(renames)}개')
        return renames

    def apply_renames(self, renames: List[Tuple[str, str, str]]) -> int:
        self._log('[파일명 변환] 시작...')
        total = len(renames)
        if total == 0:
            self._progress(100, '변환할 파일 없음')
            return 0
        applied = 0
        for i, (fp, old_name, new_name) in enumerate(renames):
            if self._cancel:
                return applied
            dirpath = os.path.dirname(fp)
            new_path = os.path.join(dirpath, new_name)
            base_n, ext_n = os.path.splitext(new_name)
            c = 2
            while os.path.exists(new_path) and os.path.normcase(new_path) != os.path.normcase(fp):
                new_path = os.path.join(dirpath, f'{base_n}({c}){ext_n}')
                c += 1
            try:
                os.rename(fp, new_path)
                applied += 1
                self._log(f'  {old_name} -> {os.path.basename(new_path)}')
            except PermissionError:
                self._log(f'  [오류] 권한 부족: {old_name}')
            except FileNotFoundError:
                self._log(f'  [오류] 파일 없음: {old_name}')
            except OSError as e:
                self._log(f'  [오류] {old_name}: {e}')
            if i % 50 == 0 or i == total - 1:
                self._progress(int((i + 1) / total * 100),
                               f'변환: {i + 1}/{total}')

        self._log(f'[파일명 변환] {applied}개 완료')
        self._progress(100, '파일명 변환 완료')
        return applied

    # ═══════════════════════════════════════
    # 사전작업: 파일 꺼내기
    # ═══════════════════════════════════════
    def flatten_files(self) -> int:
        self._log('=' * 50)
        self._log('[사전작업] 하위 폴더 파일 꺼내기...')
        files = self._collect_files()
        total = len(files)
        moved = 0
        for i, fp in enumerate(files):
            if self._cancel:
                return moved
            if os.path.dirname(fp) == self.base_path:
                continue
            result = self._safe_move(fp, self.base_path)
            if result:
                moved += 1
            if i % 50 == 0 or i == total - 1:
                self._progress(int((i + 1) / total * 100) if total else 100,
                               f'꺼내기: {i + 1}/{total}')
        self._remove_empty_dirs()
        self._log(f'[사전작업] {moved}개 이동 완료')
        self._progress(100, '파일 꺼내기 완료')
        return moved
