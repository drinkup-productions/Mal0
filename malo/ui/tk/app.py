"""Tk UI. Owns the window, drains the bus, renders the avatar."""
import os
import random
import threading
import time
import tkinter as tk
from tkinter import filedialog

from ...core import (autonomy, config, engine, events as E, feedback, ledger,
                     personas, provider)
from ...core.log import log
from ...tools import mcp, registry
from . import dialogs, theme
from .avatar import DEFAULT_TUNE, AvatarRig, save_tune

BG, PANEL, BORDER, FG = theme.BG, theme.PANEL, theme.BORDER, theme.FG
MUTED, ACCENT = theme.MUTED, theme.ACCENT


class App:
    def __init__(self, rt, want_tray=True):
        self.rt = rt
        self.cfg = rt.cfg
        self.want_tray = want_tray
        self.root = tk.Tk()

        self.history = []
        self.streaming = False
        self.waker = autonomy.Waker(self.rt.bus, self.cfg, self._wake_turn)
        self.selfdev = autonomy.SelfDevWaker(self.rt.bus, self.cfg, self._wake_turn)
        self.pend = None
        self.last_user = ""
        self.last_bot = ""
        self.models = []
        self._all_models = []
        self.images = []
        self.bubbles = []
        self.hold_bub = None
        self.bot_open = False
        self._think_open = False
        self._delta_buf = []
        self.settings_win = None
        self.cal_win = None
        self.base_avatar = personas.base_image(personas.active(self.cfg))
        self.avatar_path = self.base_avatar
        self.idle_since = time.time()
        self.evolved = False
        self.treat_stage = 0
        self._treat_job = None
        self._rsz_job = self._cal_job = self._pat_job = None
        self._cap_until = 0.0
        self._models_busy = False
        self.engine = engine.Engine(self.rt.bus, self.cfg)
        self.state = "idle"

        self.root.title("MalO ver1.1.0")
        self.root.geometry("1280x880")
        self.root.minsize(980, 640)
        self.root.configure(bg=BG)

        self._build()
        self._load_personas()
        self._apply_bg(self.cfg.get("background") or "bd-lav")
        self._rebuild_avatar()
        self._refresh_models()
        self.set_state("idle")
        self.root.after(400, self._greet)
        self._tick()

    # ---- lifecycle ---------------------------------------------------
    def run(self):
        self.rt.app = self
        tray = None
        if self.want_tray and self.rt.platform.has_tray:
            tray = self.rt.platform.make_tray()
        if tray:
            self.rt.tray = tray
            threading.Thread(target=tray.run, args=(self,), daemon=True).start()
            self.root.protocol("WM_DELETE_WINDOW", self.hide)
        else:
            self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.bind_all("<Motion>", self._touch, add="+")
        self.root.bind_all("<KeyPress>", self._touch, add="+")
        self._pump()
        self.waker.start()
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        self.quit()

    def show(self):
        def go():
            try:
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
            except Exception:
                pass
        try:
            self.root.after(0, go)
        except Exception:
            pass

    def hide(self):
        self.root.withdraw()
        log("window hidden")

    def quit(self, *_a):
        if self.rt.quitting:
            return
        self.rt.quitting = True
        self.waker.halt()
        self.selfdev.halt()
        self.engine.release()
        for fn in (mcp.stop_all, self.rt.audio.stop_all,
                   lambda: self.rt.tray.stop() if self.rt.tray else None):
            try:
                fn()
            except Exception:
                pass
        try:
            self.root.after(0, self.root.destroy)
        except Exception:
            pass

    # ---- layout ------------------------------------------------------
    def _btn(self, parent, text, cmd, **kw):
        return tk.Button(parent, text=text, command=cmd, bg=PANEL, fg=FG, relief="flat",
                         activebackground=BORDER, activeforeground=FG,
                         font=("Segoe UI", 8), padx=9, pady=3, cursor="hand2", **kw)

    def _build(self):
        left = tk.Frame(self.root, bg=BG, width=330)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        self.stage = tk.Frame(left, bg=theme.BGS["bd-lav"], highlightthickness=1,
                              highlightbackground=BORDER)
        self.stage.pack(fill="both", expand=True, padx=14, pady=(14, 8))
        self.canvas = tk.Canvas(self.stage, bg=theme.BGS["bd-lav"], highlightthickness=0,
                                cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Motion>", self._on_move)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Configure>", self._on_resize)
        self.rig = AvatarRig(self.canvas)

        row = tk.Frame(left, bg=BG)
        row.pack(fill="x", padx=14)
        self.pill = tk.Label(row, text="idle", bg=ACCENT, fg="#fff",
                             font=("Segoe UI", 8, "bold"), padx=11, pady=2)
        self.pill.pack(side="left")
        self.stat = tk.Label(row, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8))
        self.stat.pack(side="right")

        brow = tk.Frame(left, bg=BG)
        brow.pack(fill="x", padx=14, pady=(8, 14))
        tk.Label(brow, text="bg", bg=BG, fg=MUTED, font=("Segoe UI", 7)).pack(side="left")
        for key, lab in (("bd-check", "check"), ("bd-dark", "dark"),
                         ("bd-lav", "lavender"), ("bd-none", "none")):
            self._btn(brow, lab, lambda k=key: self._apply_bg(k)).pack(side="left", padx=2)

        right = tk.Frame(self.root, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        head = tk.Frame(right, bg=BG)
        head.pack(fill="x", padx=12, pady=(12, 4))
        self.dot = tk.Canvas(head, width=9, height=9, bg=BG, highlightthickness=0)
        self.dot_id = self.dot.create_oval(0, 0, 9, 9, fill="#ef4444", outline="")
        self.dot.pack(side="left", padx=(0, 6))
        tk.Label(head, text="MalO", bg=BG, fg=FG,
                 font=("Segoe UI", 11, "bold")).pack(side="left")

        self.persona_var = tk.StringVar(value=personas.active(self.cfg))
        self.persona_menu = tk.OptionMenu(head, self.persona_var,
                                          personas.active(self.cfg), command=self._set_persona)
        self.persona_menu.configure(bg=PANEL, fg=FG, activebackground=BORDER,
                                    activeforeground=FG, relief="flat",
                                    highlightthickness=0, font=("Segoe UI", 8))
        self.persona_menu["menu"].configure(bg=PANEL, fg=FG)
        self.persona_menu.pack(side="left", padx=6)

        self.filter_var = tk.StringVar()
        fe = tk.Entry(head, textvariable=self.filter_var, width=10, bg=PANEL, fg=FG,
                      relief="flat", insertbackground=FG)
        fe.pack(side="left", padx=4)
        fe.bind("<KeyRelease>", lambda e: self._render_models())

        self.model_var = tk.StringVar(value=self.cfg.get("model") or "(none)")
        self.model_menu = tk.OptionMenu(head, self.model_var, "(none)", command=self._set_model)
        self.model_menu.configure(bg=PANEL, fg=FG, activebackground=BORDER,
                                  activeforeground=FG, relief="flat",
                                  highlightthickness=0, font=("Segoe UI", 8))
        self.model_menu["menu"].configure(bg=PANEL, fg=FG)
        self.model_menu.pack(side="left", padx=4)

        self._btn(head, "Reload", self._refresh_models).pack(side="left", padx=3)
        self._btn(head, "Settings", self.open_settings).pack(side="left", padx=3)
        self._btn(head, "Quit", self.quit).pack(side="left", padx=3)

        strip = tk.Frame(right, bg=BG)
        strip.pack(fill="x", padx=12)
        self.lbl_persona = self._stat(strip, "persona")
        self.lbl_mcp = self._stat(strip, "mcp")
        self.lbl_tools = self._stat(strip, "tools")
        self.lbl_tok = self._stat(strip, "session")
        self.lbl_ctx = self._stat(strip, "ctx")
        self.lbl_pats = self._stat(strip, "headpats")

        body = tk.Frame(right, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(6, 0))
        sb = tk.Scrollbar(body)
        sb.pack(side="right", fill="y")
        self.txt = tk.Text(body, bg=BG, fg=FG, insertbackground=FG, wrap="word",
                           relief="flat", padx=10, pady=8, font=("Segoe UI", 10),
                           state="disabled", cursor="arrow", yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.configure(command=self.txt.yview)
        self._tags()

        self.confirm_bar = tk.Frame(right, bg="#3a2f10")
        self.confirm_lbl = tk.Label(self.confirm_bar, text="", bg="#3a2f10", fg="#ffd479",
                                    font=("Segoe UI", 9), anchor="w")
        self.confirm_lbl.pack(side="left", padx=10, pady=6, fill="x", expand=True)
        self._btn(self.confirm_bar, "Run", lambda: self._approve(True)).pack(side="right", padx=2)
        self._btn(self.confirm_bar, "Skip", lambda: self._approve(False)).pack(side="right", padx=6)

        self.composer = tk.Frame(right, bg=BG)
        self.composer.pack(fill="x", padx=12, pady=(8, 4))
        self.input = tk.Text(self.composer, height=3, bg=PANEL, fg=FG, insertbackground=FG,
                             relief="flat", padx=8, pady=6, font=("Segoe UI", 10), wrap="word")
        self.input.pack(side="left", fill="both", expand=True)
        self.input.bind("<Return>", self._on_return)
        self.input.bind("<Shift-Return>", lambda e: None)
        btns = tk.Frame(self.composer, bg=BG)
        btns.pack(side="left", padx=(8, 0), fill="y")
        self.send_btn = tk.Button(btns, text="Send", command=self.send, bg=ACCENT, fg="#fff",
                                  relief="flat", activebackground="#7c4ce0", padx=14,
                                  font=("Segoe UI", 9, "bold"), cursor="hand2")
        self.send_btn.pack(fill="both", expand=True)
        self.stop_btn = tk.Button(btns, text="Stop", command=self.stop, bg=BORDER, fg=FG,
                                  relief="flat", activebackground=PANEL, padx=14,
                                  font=("Segoe UI", 9), cursor="hand2")

        fb = tk.Frame(right, bg=BG)
        fb.pack(fill="x", padx=12, pady=(0, 10))
        self._btn(fb, "headpat", self._pat).pack(side="left")
        self._btn(fb, "treat", self._treat).pack(side="left", padx=6)
        self._btn(fb, "that's wrong", self._wrong).pack(side="left", padx=6)
        self.fbnote = tk.Entry(fb, bg=PANEL, fg=FG, relief="flat", insertbackground=FG)
        self.fbnote.pack(side="left", fill="x", expand=True, padx=6)
        self.fbcount = tk.Label(fb, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8))
        self.fbcount.pack(side="right")
        self._fb_refresh()

    def _stat(self, parent, key):
        tk.Label(parent, text=key, bg=BG, fg=MUTED, font=("Consolas", 8)).pack(side="left")
        v = tk.Label(parent, text="-", bg=BG, fg=FG, font=("Consolas", 8))
        v.pack(side="left", padx=(3, 12))
        return v

    def _tags(self):
        t = self.txt
        t.tag_configure("user", foreground="#fff", background=ACCENT,
                        spacing1=4, spacing3=4, lmargin1=8, lmargin2=8, rmargin=8)
        t.tag_configure("bot", foreground=FG, background=PANEL,
                        spacing1=4, spacing3=4, lmargin1=8, lmargin2=8, rmargin=8)
        t.tag_configure("sys", foreground=MUTED, justify="center", spacing1=3, spacing3=3)
        t.tag_configure("think", foreground=MUTED, font=("Segoe UI", 9, "italic"),
                        lmargin1=16, lmargin2=16)
        t.tag_configure("tool", foreground="#9ecbff", font=("Consolas", 9),
                        spacing1=3, lmargin1=8)
        t.tag_configure("toolout", foreground="#b9c6dd", font=("Consolas", 8),
                        lmargin1=22, lmargin2=22)
        t.tag_configure("toolbad", foreground="#ffb4b4", font=("Consolas", 8),
                        lmargin1=22, lmargin2=22)

    def _ins(self, text, tag):
        self.txt.configure(state="normal")
        self.txt.insert("end", text, tag)
        self.txt.configure(state="disabled")
        self.txt.see("end")

    def _flush_delta(self):
        if self._delta_buf:
            self._ins("".join(self._delta_buf), "bot")
            self._delta_buf = []

    def _make_caption(self):
        self.cap_item = self.canvas.create_text(150, 0, text="", fill=FG,
                                                font=("Segoe UI", 9), tags="cap",
                                                anchor="s", width=280)
        self._place_caption()

    def _place_caption(self):
        self.canvas.coords(self.cap_item, max(1, self.canvas.winfo_width()) // 2,
                           max(1, self.canvas.winfo_height()) - 8)

    # ---- events ------------------------------------------------------
    def _on_move(self, e):
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        self.rig.tmx = ((e.x / cw) - 0.5) * 9
        self.rig.tmy = ((e.y / ch) - 0.5) * 5

    def _on_leave(self, _e):
        self.rig.tmx = self.rig.tmy = 0.0

    def _on_resize(self, _e):
        self._place_caption()
        if self._rsz_job:
            self.root.after_cancel(self._rsz_job)
        self._rsz_job = self.root.after(240, self._rebuild_avatar)

    def _rebuild_avatar(self):
        self._rsz_job = None
        self.rig.load(self.avatar_path)
        self._make_caption()
        self.canvas.tag_raise("cap")
        self.stat.configure(text=os.path.basename(self.avatar_path or ""))
        self.bubbles = []
        self.hold_bub = None
        self._zones()

    def _tick(self):
        self.rig.render()
        if self.rig.show_zones:
            self.canvas.tag_raise("zone")
        now = time.time()
        self._check_idle(now)
        reap = getattr(self.rt.audio, "reap", None)
        if reap:
            reap()
        for b in list(self.bubbles):
            if now > b[2]:
                self.canvas.delete(b[0])
                self.canvas.delete(b[1])
                self.bubbles.remove(b)
        if self._cap_until and now > self._cap_until:
            self.canvas.itemconfigure(self.cap_item, text="")
            self._cap_until = 0.0
        self.root.after(30, self._tick)

    def _zones(self):
        self.canvas.delete("zone")
        if not self.rig.show_zones or self.rig.W <= 0:
            return
        for key, col in (("L", "#22d3ee"), ("R", "#22d3ee"), ("M", "#f472b6")):
            t = self.rig.tune[key]
            cx = self.rig.ox + t["cx"] / 100 * self.rig.W
            cy = self.rig.oy + t["cy"] / 100 * self.rig.H
            rx = t["rx"] / 100 * self.rig.W
            ry = t["ry"] / 100 * self.rig.H
            self.canvas.create_oval(cx - rx, cy - ry, cx + rx, cy + ry,
                                    outline=col, width=2, dash=(5, 3), tags="zone")
            self.canvas.create_oval(cx - rx * 0.6, cy - ry * 0.6,
                                    cx + rx * 0.6, cy + ry * 0.6,
                                    outline=col, width=1, dash=(2, 4), tags="zone")
            self.canvas.create_text(cx, cy - ry - 9, text=key, fill=col,
                                    font=("Consolas", 8, "bold"), tags="zone")
        self.canvas.tag_raise("zone")

    def _cal(self, side, key, value):
        self.rig.tune[side][key] = value
        self._zones()
        if self._cal_job:
            self.root.after_cancel(self._cal_job)
        self._cal_job = self.root.after(70, self._cal_apply)

    def _cal_apply(self):
        self._cal_job = None
        save_tune(self.rig.tune)
        self.rig.rebuild()

    def _cal_reset(self):
        import json
        self.rig.tune = json.loads(json.dumps(DEFAULT_TUNE))
        save_tune(self.rig.tune)
        self.rig.rebuild()
        self._zones()

    # ---- idle evolve -------------------------------------------------
    def _evolve_spec(self):
        spec = (personas.PERSONAS.get(personas.active(self.cfg)) or {}).get("idle_evolve") or {}
        img = spec.get("image")
        if not img:
            return None, 0.0
        try:
            mins = float(self.cfg.get("idle_evolve_minutes") or 0) or \
                float(spec.get("after_minutes") or 10)
        except Exception:
            mins = 1.0
        return img, mins

    def _touch(self, _e=None, force=False):
        now = time.time()
        if not force and now - self.idle_since < 1.0:
            return
        self.idle_since = now
        if self.evolved:
            self._wake()

    def _wake(self):
        self.evolved = False
        self.avatar_path = self.base_avatar
        self._rebuild_avatar()
        self.set_state("idle")
        self.say("oh - you're back", 2200)
        self.react("bang")

    def _check_idle(self, now):
        if self.evolved or self.streaming or self.rig.calm:
            return
        if not self.cfg.get("idle_evolve", True):
            return
        img, mins = self._evolve_spec()
        if not img or mins <= 0 or now - self.idle_since < mins * 60:
            return
        p = personas.asset(personas.active(self.cfg), img)
        if not p:
            return
        if self.treat_stage:
            return
        self.evolved = True
        self.avatar_path = p
        self._rebuild_avatar()
        self.set_state("sleepy")
        self.say("...still here", 3500)

    # ---- avatar fx ---------------------------------------------------
    def say(self, text, ms=2000):
        self.canvas.itemconfigure(self.cap_item, text=text)
        self._cap_until = time.time() + ms / 1000.0

    def _bubble(self, icon, x, y, r=19):
        o = self.canvas.create_oval(x, y, x + r * 2, y + r * 2, fill="#fff", outline="")
        t = self.canvas.create_text(x + r, y + r, text=theme.GLYPH.get(icon, "\u2605"),
                                    fill="#2b2740", font=("Segoe UI Symbol", 12, "bold"))
        self.canvas.tag_raise(o)
        self.canvas.tag_raise(t)
        return o, t

    def react(self, icon):
        o, t = self._bubble(icon, 110 + random.random() * 60, 16 + random.random() * 26)
        self.bubbles.append([o, t, time.time() + 1.3])
        self.rig.twitch[random.choice(("L", "R"))] = random.choice((1, -1)) * 14

    def hold_icon(self, icon):
        if self.hold_bub:
            self.canvas.delete(self.hold_bub[0])
            self.canvas.delete(self.hold_bub[1])
            self.hold_bub = None
        if icon:
            self.hold_bub = self._bubble(icon, 200, 30)

    def set_state(self, name):
        s = theme.STATES.get(name)
        if not s:
            return
        self.state = name
        self.rig.ear_tgt["L"] = s["l"]
        self.rig.ear_tgt["R"] = s["r"]
        self.pill.configure(text=s["label"], bg=s["col"])
        self.hold_icon(s["icon"])
        if self.rt.tray:
            self.rt.tray.set_text(name)

    # ---- models / persona --------------------------------------------
    def _render_models(self):
        q = self.filter_var.get().lower()
        self.models = [m for m in self._all_models if not q or q in m.lower()]
        menu = self.model_menu["menu"]
        menu.delete(0, "end")
        if not self.models:
            menu.add_command(label="(none loaded)",
                             command=lambda: self._set_model("(none loaded)"))
            return
        for m in self.models:
            menu.add_command(label=m, command=lambda v=m: self._set_model(v))
        if self.model_var.get() not in self.models:
            self.model_var.set(self.models[0])

    def _refresh_models(self):
        if self._models_busy:
            return
        self._models_busy = True
        threading.Thread(target=self._models_worker, daemon=True).start()

    def _models_worker(self):
        try:
            ids = provider.build(self.cfg).models()
        except Exception:
            ids = []
        self.rt.bus.emit(E.ev(E.MODELS, ids=ids))

    def _apply_models(self, ids):
        self._models_busy = False
        self._all_models = ids
        self._render_models()
        self.dot.itemconfigure(self.dot_id, fill="#22c55e" if ids else "#ef4444")
        self.lbl_mcp.configure(text=self._mcp_line())
        if ids:
            self.lbl_tools.configure(text="%d core + %d mcp"
                                     % (len(registry.CORE_SPECS), len(mcp.tool_specs())))
        else:
            self.lbl_tools.configure(text="backend: no models")

    def _mcp_line(self):
        rows = mcp.status()
        return "%d/%d up" % (sum(1 for r in rows if r["ready"]), len(rows))

    def _set_model(self, value):
        if value == "(none loaded)":
            return
        self.model_var.set(value)
        self.cfg["model"] = value
        config.save()

    def _load_personas(self):
        menu = self.persona_menu["menu"]
        menu.delete(0, "end")
        for p in personas.brief():
            menu.add_command(label=p["label"], command=lambda v=p["id"]: self._set_persona(v))
        self.persona_var.set(personas.active(self.cfg))
        self.lbl_persona.configure(text=personas.active(self.cfg))

    def _set_persona(self, pid):
        if pid not in personas.PERSONAS:
            return
        self.cfg["persona"] = pid
        config.save()
        want = (personas.PERSONAS.get(pid) or {}).get("model") or ""
        if want:
            self.cfg["model"] = want
            config.save()
        self.persona_changed(pid, want, True, personas.greeting(pid))
        
        # Track the persona change
        try:
            from ..core import evolution
            evolution.track_mode_usage(pid)
        except Exception as e:
            print(f"Failed to track persona usage: {e}")

    def persona_changed(self, pid, want, ok, greeting):
        self.persona_var.set(pid)
        self.lbl_persona.configure(text=pid)
        self._flush_delta()
        self.history = []
        self._think_open = False
        self.bot_open = False
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")
        self.base_avatar = personas.base_image(pid)
        self.avatar_path = self.base_avatar
        self.idle_since = time.time()
        self.evolved = False
        if self._treat_job:
            self.root.after_cancel(self._treat_job)
            self._treat_job = None
        self.treat_stage = 0
        self._rebuild_avatar()
        self._refresh_models()
        if want and not ok:
            self._ins("persona wants model %r - not loaded\n" % want, "sys")
        if greeting:
            self._ins("malo \u25b8 " + greeting + "\n", "bot")
            self.history.append({"role": "assistant", "content": greeting})
            self.say(greeting, 4000)
            self.react("heart")

    def _greet(self):
        g = personas.greeting(personas.active(self.cfg))
        if not g:
            return
        self._ins("malo \u25b8 " + g + "\n", "bot")
        self.history.append({"role": "assistant", "content": g})
        self.say(g, 4000)
        self.react("heart")

    def _apply_bg(self, name):
        col = theme.BGS.get(name, theme.BGS["bd-lav"])
        self.stage.configure(bg=col)
        self.canvas.configure(bg=col)
        self.cfg["background"] = name
        config.save()

    # ---- chat --------------------------------------------------------
    def _on_return(self, e):
        if not e.state & 0x0001:
            self.send()
            return "break"

    def send(self):
        self._touch(force=True)
        if self.streaming:
            return
        text = self.input.get("1.0", "end").strip()
        if not text:
            return
        model = self.model_var.get()
        if not model or model == "(none loaded)":
            self.say("no model loaded", 1800)
            return
        if ledger.over_budget(float(self.cfg.get("budget_day") or 0)):
            self._ins("budget: $%.2f spent today\n" % ledger.SPEND["usd"], "sys")
        self.input.delete("1.0", "end")
        self._ins("you \u25b8 " + text + "\n", "user")
        self.history.append({"role": "user", "content": text})
        self.last_user, self.last_bot = text, ""
        self.bot_open = False
        self._delta_buf = []
        self.streaming = True
        self.send_btn.configure(state="disabled")
        self.stop_btn.pack(fill="both", expand=True, pady=(4, 0))
        self.set_state("thinking")
        self.say("...", 4000)
        self.react("dots")
        self.engine = engine.Engine(self.rt.bus, self.cfg)
        msgs = list(self.history)
        threading.Thread(target=self._run_engine, args=(msgs, model), daemon=True).start()

    def _wake_turn(self, kind, reason):
        self.root.after(0, lambda: self._wake_now(kind, reason))

    def _wake_now(self, kind, reason):
        if self.streaming:
            return
        model = self.model_var.get()
        if not model or model == "(none loaded)":
            return
        if kind == "selfdev":
            brief = autonomy.SELFDEV_BRIEF
            steps = 0
            tail = ("Work alone. Read before you write. Propose, then run the tests. "
                    "If the tests fail, say what broke and stop.")
        else:
            brief = (self.cfg.get("wake_brief") or "").strip() or autonomy.DEFAULT_BRIEF
            steps = 0
            tail = ("Reply in one sentence. Do not describe tools or list windows. "
                    "If nothing needs attention, reply exactly: nothing")
        self._ins("[wake] %s\n" % reason, "sys")
        self.history.append({"role": "user", "content": (
            "[unattended %s wake] %s\n%s" % (kind, brief, tail))})
        self.last_user, self.last_bot = "", ""
        self.bot_open = False
        self._delta_buf = []
        self.streaming = True
        self.send_btn.configure(state="disabled")
        self.stop_btn.pack(fill="both", expand=True, pady=(4, 0))
        self.set_state("thinking")
        wcfg = dict(self.cfg)
        wcfg["confirm"] = False
        self.engine = engine.Engine(self.rt.bus, wcfg)
        threading.Thread(target=self._run_engine,
                         args=(list(self.history), model, steps), daemon=True).start()

    def _run_engine(self, msgs, model, steps=None):
        self.engine.run(msgs, model, self.rt.platform.name,
                        max_steps=steps or engine.MAX_STEPS)

    def stop(self):
        if self.engine:
            self.engine.release()

    def _approve(self, ok):
        if self.pend is not None:
            self.engine.approve(self.pend, ok)
        self.pend = None
        self.confirm_bar.pack_forget()

    def _pump(self):
        self.rt.bus.drain(self._handle)
        self._flush_delta()
        self.root.after(45, self._pump)

    def _handle(self, ev):
        t = ev.get("type")
        if t != E.DELTA:
            self._flush_delta()
        if t == E.THINK:
            if not self._think_open:
                self._ins("", "think")
                self._think_open = True
            self._ins(ev["text"], "think")
        elif t == E.DELTA:
            self._think_open = False
            if not self.bot_open:
                self._ins("malo \u25b8 ", "bot")
                self.bot_open = True
                self.set_state("working")
                self.rig.talking = True
            self._delta_buf.append(ev["text"])
        elif t == E.TOOL_RESULT:
            ok = ev.get("ok")
            self._ins(ev["text"][:600] + "\n", "toolout" if ok else "toolbad")
            if not ok:
                self.react("cross")
                self.rt.play_sfx(self.cfg.get("sfx_error"))
        elif t == E.ARTIFACT:
            self._add_image(ev.get("url"))
            self.react("star")
        elif t == E.CONFIRM:
            self.bot_open = False
            self.pend = ev["id"]
            self.confirm_lbl.configure(text="run %s %s" % (ev["name"], str(ev["args"])[:90]))
            self.confirm_bar.pack(fill="x", before=self.composer)
        elif t == E.TURN:
            self._push_turn(ev.get("messages"))
            self._finish_turn()
        elif t == E.USAGE:
            self.lbl_tok.configure(text=str(ev.get("session", 0)))
            if ev.get("prompt"):
                self.lbl_ctx.configure(text=str(ev["prompt"]))
        elif t == E.MODELS:
            self._apply_models(ev.get("ids") or [])
        elif t == E.ERROR:
            self.bot_open = False
            self._ins("!! %s\n" % ev["text"], "sys")

    def _push_turn(self, msgs):
        for m in (msgs or []):
            if m.get("role") == "tool" and isinstance(m.get("content"), str) \
                    and len(m["content"]) > 2500:
                self.history.append({"role": "tool", "tool_call_id": m["tool_call_id"],
                                     "content": m["content"][:2500] + "\n...[trimmed]"})
            else:
                self.history.append(m)
        while len(self.history) > 60:
            self.history.pop(0)
            while self.history and self.history[0].get("role") == "tool":
                self.history.pop(0)

    def _add_image(self, name):
        from PIL import Image, ImageTk
        if not name:
            return
        path = os.path.join(self.rt.paths.output, os.path.basename(name))
        if not os.path.isfile(path):
            self._ins("[image] %s\n" % name, "sys")
            return
        try:
            with Image.open(path) as src:
                im = src.copy()
            im.thumbnail((520, 520))
            ph = ImageTk.PhotoImage(im)
        except Exception:
            self._ins("[image] %s\n" % name, "sys")
            return
        self.images.append(ph)
        self.txt.configure(state="normal")
        self.txt.insert("end", "\n")
        self.txt.image_create("end", image=ph, padx=6, pady=6)
        self.txt.insert("end", "\n")
        self.txt.configure(state="disabled")
        self.txt.see("end")

    def _finish_turn(self):
        self._flush_delta()
        self.streaming = False
        self.send_btn.configure(state="normal")
        self.stop_btn.pack_forget()
        self.confirm_bar.pack_forget()
        self.pend = None
        self.rig.talking = False
        self.input.focus_set()

    # ---- feedback ----------------------------------------------------
    def _fb_refresh(self):
        c = feedback.counts()
        self.lbl_pats.configure(text=str(c["good"]))
        self.fbcount.configure(text=("+%d" % c["good"] if c["good"] else "") +
                                    ("  -%d" % c["bad"] if c["bad"] else ""))


    def _treat_spec(self):
        return (personas.PERSONAS.get(personas.active(self.cfg)) or {}).get("treat") or {}

    def _apply_treat(self, stages):
        if not stages:
            return
        if self.treat_stage <= 0:
            self.avatar_path = self.base_avatar
        else:
            p = personas.asset(personas.active(self.cfg),
                               stages[min(self.treat_stage, len(stages)) - 1])
            if p:
                self.avatar_path = p
        self._rebuild_avatar()

    def _schedule_treat_decay(self, spec):
        if self._treat_job:
            self.root.after_cancel(self._treat_job)
        self._treat_job = self.root.after(
            int(float(spec.get("decay_secs") or 900) * 1000), self._treat_decay)

    def _treat_decay(self):
        self._treat_job = None
        spec = self._treat_spec()
        if self.treat_stage <= 0:
            return
        self.treat_stage -= 1
        self._apply_treat(spec.get("stages") or [])
        if self.treat_stage > 0:
            self._schedule_treat_decay(spec)
        else:
            self.say("...hungry again", 2000)

    def _treat(self):
        spec = self._treat_spec()
        stages = spec.get("stages") or []
        if not stages:
            self.say("no treats for this one", 1600)
            return
        self._touch(force=True)
        self.react("heart")
        self.set_state("happy")
        self.rt.play_sfx(self.cfg.get("sfx_treat"))
        if self.treat_stage >= len(stages):
            self.say("stuffed already", 1800)
        else:
            self.treat_stage += 1
        self._apply_treat(stages)
        self._schedule_treat_decay(spec)

    def _pat(self):
        self._touch(force=True)
        self.react("heart")
        self.set_state("happy")
        self.say("headpat!", 1800)
        self.rt.play_sfx(self.cfg.get("sfx_headpat"))
        self.rt.play_sfx(self.cfg.get("sfx_goodgirl"))
        if self._pat_job:
            self.root.after_cancel(self._pat_job)
        self._pat_job = self.root.after(1500, lambda: self.set_state("idle"))
        feedback.add("good", "", self.last_user, self.last_bot,
                     personas.active(self.cfg))
        self._fb_refresh()

    def _wrong(self):
        self._touch(force=True)
        note = self.fbnote.get().strip()
        self.react("cross")
        self.set_state("confused")
        self.say("noted", 1600)
        self.rt.play_sfx(self.cfg.get("sfx_error"))
        feedback.add("bad", note, self.last_user, self.last_bot,
                     personas.active(self.cfg))
        self.fbnote.delete(0, "end")
        self._fb_refresh()
        if self.streaming:
            return
        self.input.delete("1.0", "end")
        self.input.insert("1.0", "[feedback] that was wrong" +
                          (": " + note if note else ".") +
                          " Reassess it, fix it if you can, and tell me in one line what changed.")
        self.send()

    # ---- dialogs -----------------------------------------------------
    def open_settings(self):
        dialogs.open_settings(self)

    def open_calibration(self):
        dialogs.open_calibration(self)

    def _pick_image(self):
        p = filedialog.askopenfilename(
            title="Pick an avatar image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.gif"), ("All", "*.*")])
        if p:
            self.base_avatar = p
            self.avatar_path = p
            self._rebuild_avatar()