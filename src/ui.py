"""진행 창, 결과 요약 창, 확인·안내 창 (tkinter)."""
import ctypes
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import processor

FONT = ("맑은 고딕", 10)
FONT_BOLD = ("맑은 고딕", 11, "bold")
APP_TITLE = "현장사진 정리기"


def enable_dpi():
    """고해상도 화면에서 글자가 흐리지 않게."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _hidden_root():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return root


def info(message):
    root = _hidden_root()
    messagebox.showinfo(APP_TITLE, message, parent=root)
    root.destroy()


def error(message):
    root = _hidden_root()
    messagebox.showerror(APP_TITLE, message, parent=root)
    root.destroy()


def ask(message):
    root = _hidden_root()
    ok = messagebox.askyesno(APP_TITLE, message, parent=root)
    root.destroy()
    return ok


def format_size(n):
    """탐색기와 같은 방식(1024 단위)으로 표시."""
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f}GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f}MB"
    return f"{n / 1024:.0f}KB"


class Window:
    """진행 막대를 보여주며 작업을 돌리고, 끝나면 같은 창에 결과를 보여준다."""

    def __init__(self, folder, verb):
        self.folder = folder
        self.verb = verb  # "정리", "되돌리기"
        self.q = queue.Queue()
        self.busy = True

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.frame = tk.Frame(self.root, padx=20, pady=16)
        self.frame.pack(fill="both", expand=True)
        tk.Label(self.frame, text=os.path.basename(folder) or folder, font=FONT_BOLD,
                 anchor="w").pack(fill="x")
        self.label = tk.Label(self.frame, text="준비 중…", font=FONT, anchor="w", width=44)
        self.label.pack(fill="x", pady=(8, 4))
        self.bar = ttk.Progressbar(self.frame, length=400, mode="determinate")
        self.bar.pack(fill="x")
        self.name_label = tk.Label(self.frame, text="", font=("맑은 고딕", 9), fg="#666",
                                   anchor="w", width=44)
        self.name_label.pack(fill="x", pady=(4, 0))
        self._center()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))

    def _center(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"+{x}+{y}")

    def _on_close(self):
        if not self.busy:  # 처리 중에는 닫지 않는다 (사진이 반쯤 처리된 채 멈추지 않게)
            self.root.destroy()

    def progress(self, i, total, name):
        """작업 스레드에서 부른다."""
        self.q.put(("progress", i, total, name))

    def run(self, work, show_result):
        """work(progress) 를 별도 스레드에서 실행하고, 끝나면 show_result(window, result)."""
        def target():
            try:
                self.q.put(("done", work(self.progress)))
            except Exception as e:
                self.q.put(("error", e))

        threading.Thread(target=target, daemon=True).start()
        self.root.after(100, self._poll, show_result)
        self.root.mainloop()

    def _poll(self, show_result):
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "progress":
                    _, i, total, name = msg
                    self.bar["maximum"] = max(total, 1)
                    self.bar["value"] = i
                    if i < total:
                        self.label["text"] = f"{total}장 중 {i + 1}장 {self.verb} 중…"
                        self.name_label["text"] = name
                elif msg[0] == "done":
                    self.busy = False
                    show_result(self, msg[1])
                    return
                elif msg[0] == "error":
                    self.busy = False
                    self.show_text(f"{self.verb} 중 문제가 생겼어요.",
                                   f"알 수 없는 오류: {msg[1]}")
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll, show_result)

    def show_text(self, headline, body):
        """진행 창 내용을 결과 요약으로 바꾼다."""
        for w in self.frame.winfo_children():
            w.destroy()
        tk.Label(self.frame, text=headline, font=FONT_BOLD, anchor="w",
                 justify="left").pack(fill="x")
        lines = body.count("\n") + 1
        box = tk.Frame(self.frame)
        box.pack(fill="both", expand=True, pady=(10, 12))
        text = tk.Text(box, font=FONT, width=56, height=min(max(lines, 4), 18),
                       wrap="word", relief="flat", bg=self.root.cget("bg"))
        text.insert("1.0", body)
        text.configure(state="disabled")
        if lines > 18:
            sb = ttk.Scrollbar(box, command=text.yview)
            text.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)

        buttons = tk.Frame(self.frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="닫기", command=self.root.destroy).pack(side="right")
        ttk.Button(buttons, text="폴더 열기", command=self._open_folder).pack(side="right", padx=(0, 8))
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self._center()

    def _open_folder(self):
        try:
            os.startfile(self.folder)
        except OSError:
            pass
        self.root.destroy()


def _list_section(title, items):
    if not items:
        return ""
    lines = [f"\n{title} ({len(items)}개)"]
    lines += [f"  • {name} — {reason}" for name, reason in items]
    return "\n".join(lines) + "\n"


def show_organize_result(win, r):
    c = r.counts
    if r.done:
        headline = f"사진 {r.done}장을 정리했어요."
        body = (f"처리한 사진: {r.done}장\n"
                f"  • 화질 조절: {c[processor.QUALITY]}장\n"
                f"  • 크기도 줄임: {c[processor.RESIZE]}장\n"
                f"  • 그대로 복사: {c[processor.COPY]}장\n"
                f"\n전체 용량: {format_size(r.bytes_before)} → {format_size(r.bytes_after)}\n")
    else:
        headline = "사진을 정리하지 못했어요."
        body = ""
    body += _list_section("건너뛴 파일", r.skipped)
    body += _list_section("실패한 파일 (원본은 제자리에 그대로 있어요)", r.failed)
    win.show_text(headline, body.strip())


def show_undo_result(win, r):
    headline = "사진 정리를 되돌렸어요." if r.restored else "되돌리지 못했어요."
    body = (f"제자리로 돌려놓은 원본: {r.restored}장\n"
            f"휴지통으로 보낸 줄인 사진: {r.trashed}장\n")
    body += _list_section("같은 이름이 있어 이름을 바꾼 사진", [(a, f"'{b}'(으)로 저장") for a, b in r.renamed])
    body += _list_section("실패한 파일", r.failed)
    win.show_text(headline, body.strip())
