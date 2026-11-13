"""Always-on-top sprite. Not a window: no chrome, no focus, no taskbar entry."""
import ctypes
import ctypes.wintypes as wt
import math
import os
import time
import tkinter as tk

from PIL import Image, ImageTk

from ...core import personas
from ...core.log import log

KEY = "#010203"
SIZE = 320
FPS = 12
FULLSCREEN_POLL = 0.5

_u32 = ctypes.windll.user32


def _monitor_size(x, y):
    return (_u32.GetSystemMetrics(0), _u32.GetSystemMetrics(1))


def foreground_covers_screen():
    hwnd = _u32.GetForegroundWindow()
    if not hwnd:
        return False
    rect = wt.RECT()
    if not _u32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    sw, sh = _monitor_size(0, 0)
    return w >= sw - 4 and h >= sh - 4


class Overlay:
    def __init__(self, app):
        self.app = app
        self.cfg = app.cfg
        self.root = app.root
        self.win = None
        self.canvas = None
        self.photo = None
        self._job = None
        self._fs_job = None
        self._hidden_by_fs = False
        self._t = 0.0
        self._base_y = 0
        self._say_until = 0.0
        self._quiet_until = float(self.cfg.get("overlay_quiet_until") or 0.0)

    # -- lifecycle -----------------------------------------------------
    def start(self):
        if not self.cfg.get("overlay", True):
            return
        if self.win and self.win.winfo_exists():
            return
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        self.win.configure(bg=KEY)
        self.canvas = tk.Canvas(self.win, width=SIZE, height=SIZE, bg=KEY,
                                highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Button-3>", self._menu)
        self._place()
        self._load()
        self._fs_job = self.root.after(int(FULLSCREEN_POLL * 1000), self._poll_fs)
        self._job = self.root.after(int(1000 / FPS), self._tick)
        log("overlay up")

    def stop(self):
        for job in (self._job, self._fs_job):
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        self._job = self._fs_job = None
        if self.win:
            try:
                self.win.destroy()
            except Exception:
                pass
        self.win = None

    # -- placement -----------------------------------------------------
    def _place(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        corner = self.cfg.get("overlay_corner") or "br"
        x = 24 if corner.endswith("l") else sw - SIZE - 24
        y = 24 if corner.startswith("t") else sh - SIZE - 72
        self._base_y = y
        self.win.geometry("%dx%d+%d+%d" % (SIZE, SIZE, x, y))

    def _load(self):
        path = personas.base_image(personas.active(self.cfg))
        if not path or not os.path.isfile(path):
            return
        try:
            with Image.open(path) as src:
                im = src.convert("RGBA")
            im.thumbnail((SIZE, SIZE))
            bg = Image.new("RGBA", (SIZE, SIZE), KEY)
            bg.paste(im, ((SIZE - im.width) // 2, SIZE - im.height), im)
            self.photo = ImageTk.PhotoImage(bg.convert("RGB"))
        except Exception as exc:
            log("overlay image: %s" % exc)
            return
        self.canvas.delete("sprite")
        self.canvas.create_image(SIZE // 2, SIZE // 2, image=self.photo, tags="sprite")

    # -- behaviour -----------------------------------------------------
    def _tick(self):
        self._t += 1.0 / FPS
        if self.win and not self._hidden_by_fs and self._base_y:
            bob = int(round(math.sin(self._t * 1.6) * 2))
            x = self.win.winfo_x()
            self.win.geometry("+%d+%d" % (x, self._base_y + bob))
        if self._say_until and time.time() > self._say_until:
            self._say_until = 0.0
            self.canvas.delete("say")
        self._job = self.root.after(int(1000 / FPS), self._tick)

    def _poll_fs(self):
        try:
            if self.win:
                cover = foreground_covers_screen()
                if cover and not self._hidden_by_fs:
                    self.win.withdraw()
                    self._hidden_by_fs = True
                elif not cover and self._hidden_by_fs:
                    self.win.deiconify()
                    self.win.attributes("-topmost", True)
                    self._hidden_by_fs = False
        finally:
            self._fs_job = self.root.after(int(FULLSCREEN_POLL * 1000), self._poll_fs)

    def say(self, text, ms=4000):
        if not self.canvas or self._hidden_by_fs:
            return
        self.canvas.delete("say")
        self.canvas.create_text(SIZE // 2, SIZE - 18, text=text[:120], fill="#ffffff",
                                font=("Segoe UI", 9), width=SIZE - 30,
                                justify="center", tags="say")
        self._say_until = time.time() + ms / 1000.0

    def show(self):
        if not self.win:
            return self.start()
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self._hidden_by_fs = False

    def hide(self):
        if self.win:
            self.win.withdraw()
            self._hidden_by_fs = True

    def quiet(self, minutes=60):
        self._quiet_until = time.time() + minutes * 60
        self.cfg["overlay_quiet_until"] = self._quiet_until
        from ...core import config
        config.save()

    def quiet_now(self):
        return time.time() < self._quiet_until

    def _menu(self, event):
        m = tk.Menu(self.win, tearoff=0)
        m.add_command(label="quiet 1h", command=lambda: self.quiet(60))
        m.add_command(label="hide", command=self.hide)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()