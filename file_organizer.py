# -*- coding: utf-8 -*-
"""
========================================
파일정리 프로그램 v2.1
GUI + 앱 진입점
========================================
"""
import os
import sys
import threading
import traceback

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog, scrolledtext, simpledialog

from engine import FileOrganizer, DEFAULT_BASE


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('파일정리 프로그램 v2.1')
        self.configure(bg='#f0f0f0')

        # 크로스플랫폼 폰트 설정
        if sys.platform == 'win32':
            self._ui_font = '맑은 고딕'
            self._mono_font = 'Consolas'
        elif sys.platform == 'darwin':
            self._ui_font = 'Apple SD Gothic Neo'
            self._mono_font = 'Menlo'
        else:
            self._ui_font = 'Noto Sans CJK KR'
            self._mono_font = 'DejaVu Sans Mono'
            try:
                dpi = self.winfo_fpixels('1i')
                if dpi > 120:
                    scale = dpi / 96.0
                    self.tk.call('tk', 'scaling', scale)
            except Exception:
                pass

        # 폰트 사용 가능 여부 확인 후 fallback
        try:
            available_fonts = set(tkfont.families(self))
        except Exception:
            available_fonts = set()

        if available_fonts:
            if self._ui_font not in available_fonts:
                for fallback in ['맑은 고딕', 'Malgun Gothic', 'NanumGothic',
                                 'Apple SD Gothic Neo', 'Noto Sans CJK KR',
                                 'Arial Unicode MS', 'TkDefaultFont']:
                    if fallback in available_fonts:
                        self._ui_font = fallback
                        break
            if self._mono_font not in available_fonts:
                for fallback in ['Consolas', 'Menlo', 'DejaVu Sans Mono',
                                 'Courier New', 'TkFixedFont']:
                    if fallback in available_fonts:
                        self._mono_font = fallback
                        break

        self.organizer = None
        self.base_path = tk.StringVar(value=DEFAULT_BASE)
        self._worker = None
        self._is_running = False
        # [3차검토] 다이얼로그가 떠있는 동안 _wrap이 잠금 해제하지 않도록 하는 플래그
        self._keep_running = False

        self._build_ui()
        self._auto_resize()
        self._check_drive()

    # ═══════════════════════════════════════
    # UI 구성
    # ═══════════════════════════════════════
    def _auto_resize(self):
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        if screen_w >= 2560:
            win_w, win_h = 1200, 850
        elif screen_w >= 1920:
            win_w, win_h = 1000, 750
        elif screen_w >= 1366:
            win_w, win_h = 900, 680
        else:
            win_w, win_h = min(screen_w - 40, 850), min(screen_h - 80, 620)

        x = (screen_w - win_w) // 2
        y = (screen_h - win_h) // 2 - 30
        self.geometry(f'{win_w}x{win_h}+{x}+{max(0, y)}')
        self.minsize(700, 500)
        self.resizable(True, True)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        # ── 작업 경로 ──
        top = ttk.LabelFrame(self, text=' 작업 경로 ', padding=10)
        top.pack(fill='x', padx=10, pady=(10, 5))
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text='경로:').grid(row=0, column=0, padx=(0, 5))
        ttk.Entry(top, textvariable=self.base_path).grid(row=0, column=1, sticky='ew', padx=5)
        ttk.Button(top, text='찾아보기', command=self._browse).grid(row=0, column=2, padx=(5, 0))

        # ── 작업 버튼 ──
        mid = ttk.LabelFrame(self, text=' 작업 순서 ', padding=10)
        mid.pack(fill='x', padx=10, pady=5)
        self.step_buttons = []
        steps = [
            ('1. 중복파일 제거', self._step_dup),
            ('2. 차단해제', self._step_unblock),
            ('3. Util/프로젝트', self._step_util),
            ('4. 확장자별 분류', self._step_ext),
            ('5. 파일명 변환', self._step_rename),
        ]
        bf = ttk.Frame(mid)
        bf.pack(fill='x')
        for i in range(5):
            bf.columnconfigure(i, weight=1)
        for i, (text, cmd) in enumerate(steps):
            btn = ttk.Button(bf, text=text, command=cmd)
            btn.grid(row=0, column=i, padx=3, pady=3, sticky='ew')
            self.step_buttons.append(btn)

        ttk.Separator(mid).pack(fill='x', pady=5)
        bf2 = ttk.Frame(mid)
        bf2.pack()
        self.run_all_btn = ttk.Button(bf2, text='>> 전체 실행', command=self._run_all, width=25)
        self.run_all_btn.pack(side='left', padx=5)
        self.cancel_btn = ttk.Button(bf2, text='[X] 취소', command=self._cancel, width=10, state='disabled')
        self.cancel_btn.pack(side='left', padx=5)
        self.clear_btn = ttk.Button(bf2, text='클리어', command=self._clear_ui, width=10)
        self.clear_btn.pack(side='left', padx=5)

        # ── 진행 상황 ──
        pf = ttk.LabelFrame(self, text=' 진행 상황 ', padding=10)
        pf.pack(fill='x', padx=10, pady=5)
        self.progress_var = tk.DoubleVar(value=0)
        self.progressbar = ttk.Progressbar(pf, variable=self.progress_var, maximum=100,
                                            mode='determinate')
        self.progressbar.pack(fill='x')

        status_frame = ttk.Frame(pf)
        status_frame.pack(fill='x', pady=(5, 0))
        self.status_label = ttk.Label(status_frame, text='대기 중...', anchor='w')
        self.status_label.pack(side='left', fill='x', expand=True)
        self.pct_label = ttk.Label(status_frame, text='0%', anchor='e', width=6)
        self.pct_label.pack(side='right')

        self.step_label = ttk.Label(pf, text='', font=(self._ui_font, 10, 'bold'),
                                     foreground='#2060a0')
        self.step_label.pack(fill='x')

        # ── 작업 로그 ──
        lf = ttk.LabelFrame(self, text=' 작업 로그 ', padding=5)
        lf.pack(fill='both', expand=True, padx=10, pady=(5, 10))
        self.log_text = scrolledtext.ScrolledText(
            lf, height=10, font=(self._mono_font, 9),
            state='disabled', bg='#1e1e1e', fg='#d4d4d4'
        )
        self.log_text.pack(fill='both', expand=True)

    # ═══════════════════════════════════════
    # 유틸리티
    # ═══════════════════════════════════════
    def _check_drive(self):
        if not os.path.exists(DEFAULT_BASE):
            messagebox.showwarning('알림',
                                   f'기본 경로가 존재하지 않습니다:\n{DEFAULT_BASE}\n'
                                   '다른 경로를 선택해주세요.')
            self._browse()

    def _browse(self):
        p = filedialog.askdirectory(title='작업 폴더 선택')
        if p:
            self.base_path.set(p)

    def _log_msg(self, msg: str):
        def _do():
            self.log_text.config(state='normal')
            try:
                self.log_text.insert('end', msg + '\n')
            except tk.TclError:
                safe_msg = msg.encode('ascii', errors='replace').decode('ascii')
                self.log_text.insert('end', safe_msg + '\n')
            self.log_text.see('end')
            self.log_text.config(state='disabled')
        self.after(0, _do)

    def _update_progress(self, pct: int, msg: str):
        def _do():
            self.progress_var.set(pct)
            self.status_label.config(text=msg)
            self.pct_label.config(text=f'{pct}%')
        self.after(0, _do)

    def _set_step(self, text: str):
        def _do():
            try:
                self.step_label.config(text=text)
            except tk.TclError:
                safe_text = text.encode('ascii', errors='replace').decode('ascii')
                self.step_label.config(text=safe_text)
        self.after(0, _do)

    def _set_buttons(self, state: str):
        for b in self.step_buttons:
            b.config(state=state)
        self.run_all_btn.config(state=state)
        self.clear_btn.config(state=state)
        self.cancel_btn.config(state='normal' if state == 'disabled' else 'disabled')

    def _cancel(self):
        if self.organizer:
            self.organizer.cancel()
        self._log_msg('[취소] 요청됨')

    def _clear_ui(self):
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.config(state='disabled')
        self.progress_var.set(0)
        self.status_label.config(text='대기 중...')
        self.pct_label.config(text='0%')
        self.step_label.config(text='')

    def _init(self) -> bool:
        if self._is_running:
            messagebox.showwarning('알림', '이미 작업이 진행 중입니다.')
            return False
        bp = self.base_path.get()
        if not os.path.isdir(bp):
            messagebox.showerror('오류', f'경로가 존재하지 않습니다:\n{bp}')
            return False
        self.organizer = FileOrganizer(bp, self._log_msg, self._update_progress)
        return True

    def _run_thread(self, func, skip_init=False):
        if not skip_init and self._is_running:
            return
        self._is_running = True
        self._keep_running = False  # [3차검토] 매 실행마다 초기화
        self._set_buttons('disabled')
        self.progress_var.set(0)
        self.pct_label.config(text='0%')
        self._worker = threading.Thread(target=self._wrap, args=(func,), daemon=True)
        self._worker.start()

    def _wrap(self, func):
        try:
            func()
        except Exception as e:
            self._log_msg(f'[오류] {e}')
            self._log_msg(traceback.format_exc())
        finally:
            # [3차검토] _keep_running=True이면 다이얼로그가 관리하므로 여기서 해제하지 않음
            if not self._keep_running:
                self._is_running = False
                self.after(0, lambda: self._set_buttons('normal'))
                self.after(0, lambda: self._set_step(''))

    def _finish_running(self):
        """다이얼로그에서 작업 없이 닫힐 때 호출 - 잠금 해제"""
        self._is_running = False
        self._keep_running = False
        self.after(0, lambda: self._set_buttons('normal'))
        self.after(0, lambda: self._set_step(''))

    def _done(self):
        self._update_progress(100, '작업 완료!')
        self._set_step('작업이 완료되었습니다')
        self.after(0, lambda: messagebox.showinfo('완료', '작업이 완료되었습니다!'))

    # ═══════════════════════════════════════
    # 단계별 핸들러
    # ═══════════════════════════════════════

    # ── 1. 중복파일 ──
    def _step_dup(self):
        if not self._init():
            return
        self._run_thread(self._do_dup)

    def _do_dup(self):
        self._set_step('1. 중복파일 검색 중...')
        dupes = self.organizer.find_duplicates()
        if not dupes:
            self._log_msg('중복파일이 없습니다.')
            self._done()
            return
        # [3차검토] 다이얼로그로 전환할 때 _wrap이 잠금을 풀지 않도록 설정
        self._keep_running = True
        self.after(0, lambda: self._show_dup_dialog(dupes))

    def _show_dup_dialog(self, dupes):
        from datetime import datetime

        dlg = tk.Toplevel(self)
        dlg.title('중복파일 제거')
        dlg.geometry('850x550')
        dlg.transient(self)
        dlg.grab_set()

        def on_dialog_close():
            dlg.destroy()
            self._finish_running()

        dlg.protocol('WM_DELETE_WINDOW', on_dialog_close)

        ttk.Label(dlg, text=f'중복 그룹 {len(dupes)}개 발견',
                  font=(self._ui_font, 11, 'bold')).pack(pady=5)

        tf = ttk.Frame(dlg)
        tf.pack(fill='both', expand=True, padx=10, pady=5)

        tree = ttk.Treeview(tf, columns=('path', 'size', 'created', 'action'),
                            show='tree headings', height=15)
        tree.heading('path', text='경로')
        tree.heading('size', text='크기')
        tree.heading('created', text='생성일')
        tree.heading('action', text='상태')
        tree.column('#0', width=200)
        tree.column('path', width=250)
        tree.column('size', width=80)
        tree.column('created', width=120)
        tree.column('action', width=80)

        sb = ttk.Scrollbar(tf, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        file_actions = {}

        for gi, (h, files) in enumerate(dupes.items()):
            gn = tree.insert('', 'end', text=f'그룹 {gi + 1} ({len(files)}개)')
            oldest = min(files,
                         key=lambda f: os.path.getctime(f) if os.path.exists(f) else float('inf'))
            for fp in files:
                try:
                    sz = os.path.getsize(fp)
                    ct = datetime.fromtimestamp(os.path.getctime(fp)).strftime('%Y-%m-%d %H:%M')
                except OSError:
                    sz, ct = 0, '?'
                sz_s = f'{sz / 1024:.1f} KB' if sz < 1048576 else f'{sz / 1048576:.1f} MB'
                keep = (fp == oldest)
                action = '보존' if keep else '삭제'
                tree.insert(gn, 'end', text=os.path.basename(fp),
                            values=(fp, sz_s, ct, action))
                file_actions[fp] = 'keep' if keep else 'delete'

        def toggle(event):
            item = tree.focus()
            if not item:
                return
            vals = tree.item(item, 'values')
            if not vals or not vals[0]:
                return
            fp = vals[0]
            if fp not in file_actions:
                return
            if file_actions[fp] == 'delete':
                file_actions[fp] = 'keep'
                tree.set(item, 'action', '보존')
            else:
                file_actions[fp] = 'delete'
                tree.set(item, 'action', '삭제')

        tree.bind('<Double-1>', toggle)

        use_trash = tk.BooleanVar(value=True)

        def do_del():
            to_delete = [fp for fp, action in file_actions.items() if action == 'delete']
            if not to_delete:
                messagebox.showinfo('알림', '삭제할 파일이 없습니다.')
                return
            trash_msg = '휴지통으로 이동' if use_trash.get() else '영구 삭제'
            if messagebox.askyesno('확인',
                                   f'{len(to_delete)}개 파일을 {trash_msg}하시겠습니까?'):
                dlg.destroy()
                delete_copy = list(to_delete)
                # _is_running은 이미 True 상태 유지 중
                self._run_thread(
                    lambda: (self.organizer.delete_duplicates(
                        delete_copy, use_trash=use_trash.get()
                    ), self._done()),
                    skip_init=True
                )

        def select_all():
            for fp in file_actions:
                file_actions[fp] = 'delete'
            for item in tree.get_children():
                for child in tree.get_children(item):
                    vals = tree.item(child, 'values')
                    if vals and vals[0]:
                        tree.set(child, 'action', '삭제')

        def deselect_all():
            for fp in file_actions:
                file_actions[fp] = 'keep'
            for item in tree.get_children():
                for child in tree.get_children(item):
                    tree.set(child, 'action', '보존')

        bf = ttk.Frame(dlg)
        bf.pack(pady=10)
        ttk.Label(bf, text='더블클릭: 보존/삭제 전환').pack(side='left', padx=10)
        ttk.Checkbutton(bf, text='휴지통 사용', variable=use_trash).pack(side='left', padx=5)
        ttk.Button(bf, text='전체선택', command=select_all).pack(side='left', padx=3)
        ttk.Button(bf, text='전체해제', command=deselect_all).pack(side='left', padx=3)
        ttk.Button(bf, text='선택 삭제', command=do_del).pack(side='left', padx=5)
        ttk.Button(bf, text='취소', command=on_dialog_close).pack(side='left', padx=5)

    # ── 2. 차단해제 ──
    def _step_unblock(self):
        if not self._init():
            return
        self._run_thread(lambda: (self._set_step('2. 차단해제...'),
                                   self.organizer.unblock_files(), self._done()))

    # ── 3. Util/프로젝트 ──
    def _step_util(self):
        if not self._init():
            return
        self._run_thread(lambda: (self._set_step('3. Util/프로젝트 분류...'),
                                   self.organizer.classify_util(),
                                   self.organizer._remove_empty_dirs(), self._done()))

    # ── 4. 확장자별 분류 ──
    def _step_ext(self):
        if not self._init():
            return
        self._run_thread(lambda: (self._set_step('4. 확장자별 분류...'),
                                   self.organizer.classify_by_extension(),
                                   self.organizer._remove_empty_dirs(), self._done()))

    # ── 5. 파일명 변환 ──
    def _step_rename(self):
        if not self._init():
            return
        self._run_thread(self._do_rename_preview)

    def _do_rename_preview(self):
        self._set_step('5. 파일명 변환 미리보기...')
        renames = self.organizer.preview_renames()
        if not renames:
            self._log_msg('변환할 파일이 없습니다.')
            self._done()
            return
        # [3차검토] 다이얼로그로 전환할 때 잠금 유지
        self._keep_running = True
        self.after(0, lambda: self._show_rename_dialog(renames))

    def _show_rename_dialog(self, renames):
        dlg = tk.Toplevel(self)
        dlg.title('파일명 변환 미리보기')
        dlg.geometry('850x550')
        dlg.transient(self)
        dlg.grab_set()

        def on_dialog_close():
            dlg.destroy()
            self._finish_running()

        dlg.protocol('WM_DELETE_WINDOW', on_dialog_close)

        ttk.Label(dlg, text=f'변환 대상: {len(renames)}개',
                  font=(self._ui_font, 11, 'bold')).pack(pady=5)

        tf = ttk.Frame(dlg)
        tf.pack(fill='both', expand=True, padx=10, pady=5)

        tree = ttk.Treeview(tf, columns=('old', 'new', 'folder'),
                            show='headings', height=15)
        tree.heading('old', text='변환 전')
        tree.heading('new', text='변환 후')
        tree.heading('folder', text='폴더')
        tree.column('old', width=250)
        tree.column('new', width=250)
        tree.column('folder', width=300)

        sb = ttk.Scrollbar(tf, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        data = []
        for fp, old, new in renames:
            item = tree.insert('', 'end', values=(old, new, os.path.dirname(fp)))
            data.append({'item': item, 'path': fp, 'old': old, 'new': new})

        def edit(event):
            item = tree.focus()
            if not item:
                return
            for d in data:
                if d['item'] == item:
                    nn = simpledialog.askstring('수정', '새 파일명:',
                                                initialvalue=d['new'], parent=dlg)
                    if nn:
                        d['new'] = nn
                        tree.set(item, 'new', nn)
                    break

        tree.bind('<Double-1>', edit)

        def apply():
            final = [(d['path'], d['old'], d['new']) for d in data]
            dlg.destroy()
            # _is_running은 이미 True 상태 유지 중
            self._run_thread(lambda: (self._set_step('5. 변환 적용...'),
                                       self.organizer.apply_renames(final), self._done()),
                             skip_init=True)

        bf = ttk.Frame(dlg)
        bf.pack(pady=10)
        ttk.Label(bf, text='더블클릭: 개별 수정').pack(side='left', padx=10)
        ttk.Button(bf, text='변환 적용', command=apply).pack(side='left', padx=5)
        ttk.Button(bf, text='취소', command=on_dialog_close).pack(side='left', padx=5)

    # ═══════════════════════════════════════
    # 전체 실행
    # ═══════════════════════════════════════
    def _run_all(self):
        if not self._init():
            return
        msg = (f'작업 경로: {self.base_path.get()}\n\n'
               '다음 작업을 순서대로 실행합니다:\n'
               '1. 중복파일 제거  2. 차단해제  3. Util/프로젝트 분류\n'
               '4. 확장자별 분류  5. 파일명 변환\n\n'
               '계속하시겠습니까?')
        if not messagebox.askyesno('전체 실행', msg):
            return
        self._run_thread(self._do_all)

    def _do_all(self):
        org = self.organizer

        # 사전작업
        self._set_step('사전작업: 파일 꺼내기...')
        org.flatten_files()
        if org._cancel:
            return

        # 1. 중복파일
        self._set_step('1. 중복파일 검색 중...')
        dupes = org.find_duplicates()
        if dupes and not org._cancel:
            dl = []
            for h, files in dupes.items():
                oldest = min(files,
                             key=lambda f: os.path.getctime(f) if os.path.exists(f) else float('inf'))
                dl.extend(f for f in files if f != oldest)
            if dl:
                ev = threading.Event()
                result = [False]

                def ask():
                    result[0] = messagebox.askyesno(
                        '중복파일',
                        f'{len(dl)}개 중복파일을 삭제하시겠습니까?\n(휴지통으로 이동)')
                    ev.set()

                self.after(0, ask)
                ev.wait()
                if result[0]:
                    org.delete_duplicates(dl, use_trash=True)

        if org._cancel:
            return

        # 2. 차단해제
        self._set_step('2. 차단해제...')
        org.unblock_files()
        if org._cancel:
            return

        # 3. Util/프로젝트 분류
        self._set_step('3. Util/프로젝트 분류...')
        org.classify_util()
        if org._cancel:
            return

        # 4. 확장자별 분류
        self._set_step('4. 확장자별 분류...')
        org.classify_by_extension()
        if org._cancel:
            return

        # 5. 파일명 변환
        self._set_step('5. 파일명 변환...')
        renames = org.preview_renames()
        if renames and not org._cancel:
            org.apply_renames(renames)

        org._remove_empty_dirs()
        self._done()


if __name__ == '__main__':
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    app = App()
    app.mainloop()
