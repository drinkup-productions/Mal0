"""Settings and calibration windows."""
import os
import threading
import tkinter as tk
import time

from ...core import config, feedback, personas
from ...tools import mcp
from . import theme

BG, PANEL, BORDER, FG = theme.BG, theme.PANEL, theme.BORDER, theme.FG
MUTED, ACCENT = theme.MUTED, theme.ACCENT


def _btn(parent, text, cmd):
    return tk.Button(parent, text=text, command=cmd, bg=PANEL, fg=FG, relief="flat",
                     activebackground=BORDER, activeforeground=FG,
                     font=("Segoe UI", 8), padx=9, pady=3, cursor="hand2")


def open_settings(app):
    if app.settings_win and app.settings_win.winfo_exists():
        app.settings_win.deiconify()
        app.settings_win.lift()
        return
    w = tk.Toplevel(app.root)
    app.settings_win = w
    w.title("MalO - settings")
    w.configure(bg=BG)
    w.geometry("560x980")
    w.transient(app.root)

    tk.Label(w, text="Settings", bg=BG, fg=FG,
             font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=(12, 6))

    tk.Label(w, text="Backend base URL", bg=BG, fg=MUTED,
             font=("Segoe UI", 8)).pack(anchor="w", padx=14)
    url = tk.Entry(w, bg=PANEL, fg=FG, relief="flat", insertbackground=FG)
    url.insert(0, app.cfg.get("base_url") or "")
    url.pack(fill="x", padx=14)

    tk.Label(w, text="API key (blank for local)", bg=BG, fg=MUTED,
             font=("Segoe UI", 8)).pack(anchor="w", padx=14, pady=(6, 0))
    key = tk.Entry(w, bg=PANEL, fg=FG, relief="flat", insertbackground=FG, show="*")
    key.insert(0, app.cfg.get("api_key") or "")
    key.pack(fill="x", padx=14)

    tk.Label(w, text="Workspace folder", bg=BG, fg=MUTED,
             font=("Segoe UI", 8)).pack(anchor="w", padx=14, pady=(6, 0))
    ws = tk.Entry(w, bg=PANEL, fg=FG, relief="flat", insertbackground=FG)
    ws.insert(0, app.cfg.get("workspace") or "")
    ws.pack(fill="x", padx=14)

    tk.Label(w, text="Temperature", bg=BG, fg=MUTED,
             font=("Segoe UI", 8)).pack(anchor="w", padx=14, pady=(6, 0))
    temp = tk.Entry(w, bg=PANEL, fg=FG, relief="flat", insertbackground=FG, width=10)
    temp.insert(0, str(app.cfg.get("temperature", 0.7)))
    temp.pack(anchor="w", padx=14)

    confv = tk.BooleanVar(value=bool(app.cfg.get("confirm")))
    tk.Checkbutton(w, text="Ask before write, edit and bash", variable=confv,
                   bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG,
                   activeforeground=FG, font=("Segoe UI", 9)).pack(anchor="w", padx=14,
                                                                    pady=(8, 2))
    idle_v = tk.BooleanVar(value=bool(app.cfg.get("idle", True)))
    tk.Checkbutton(w, text="Idle animations", variable=idle_v, bg=BG, fg=FG,
                   selectcolor=PANEL, activebackground=BG, activeforeground=FG,
                   font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(0, 2))

    ev_v = tk.BooleanVar(value=bool(app.cfg.get("idle_evolve", True)))
    tk.Checkbutton(w, text="Switch avatar after a long idle", variable=ev_v,
                   bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG,
                   activeforeground=FG,
                   font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(0, 2))
    erow = tk.Frame(w, bg=BG)
    erow.pack(fill="x", padx=14, pady=(0, 4))
    tk.Label(w, text="Wake brief - what an unattended wake should check", bg=BG, fg=MUTED,
             font=("Segoe UI", 8)).pack(anchor="w", padx=14, pady=(8, 0))
    brief = tk.Text(w, height=4, bg=PANEL, fg=FG, relief="flat", insertbackground=FG,
                    wrap="word", font=("Segoe UI", 9))
    brief.insert("1.0", app.cfg.get("wake_brief") or "")
    brief.pack(fill="x", padx=14)

    def _save_brief():
        app.cfg["wake_brief"] = brief.get("1.0", "end").strip()
        config.save()
        app.say("brief saved", 1400)

    _btn(w, "Save brief", _save_brief).pack(anchor="w", padx=14, pady=(4, 0))
    tk.Label(erow, text="after", bg=BG, fg=MUTED, width=14, anchor="w",
             font=("Segoe UI", 8)).pack(side="left")
    ev_min = tk.Entry(erow, bg=PANEL, fg=FG, relief="flat", insertbackground=FG, width=6)
    ev_min.insert(0, str(int(app.cfg.get("idle_evolve_minutes") or 10)))
    ev_min.pack(side="left")
    tk.Label(erow, text=" minutes", bg=BG, fg=MUTED,
             font=("Segoe UI", 8)).pack(side="left")

    sfx_v = tk.BooleanVar(value=bool(app.cfg.get("sfx", True)))
    tk.Checkbutton(w, text="Sound", variable=sfx_v, bg=BG, fg=FG, selectcolor=PANEL,
                   activebackground=BG, activeforeground=FG,
                   font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(0, 2))
    vrow = tk.Frame(w, bg=BG)
    vrow.pack(fill="x", padx=14)
    tk.Label(vrow, text="volume", bg=BG, fg=MUTED, width=14, anchor="w",
             font=("Segoe UI", 8)).pack(side="left")
    vol_v = tk.IntVar(value=int(app.cfg.get("sfx_volume") or 80))
    tk.Scale(vrow, from_=0, to=100, orient="horizontal", variable=vol_v,
             bg=BG, fg=FG, troughcolor=PANEL, highlightthickness=0,
             activebackground=ACCENT, length=250, font=("Segoe UI", 7),
             showvalue=True).pack(side="left", fill="x", expand=True)

    def _sfx_row(label, cfg_key):
        r = tk.Frame(w, bg=BG)
        r.pack(fill="x", padx=14, pady=1)
        tk.Label(r, text=label, bg=BG, fg=MUTED, width=14, anchor="w",
                 font=("Segoe UI", 8)).pack(side="left")
        names = ["(none)"] + _sfx_files(app)
        var = tk.StringVar(value=app.cfg.get(cfg_key) or "(none)")
        om = tk.OptionMenu(r, var, *names)
        om.configure(bg=PANEL, fg=FG, activebackground=BORDER, activeforeground=FG,
                     relief="flat", highlightthickness=0, font=("Segoe UI", 8),
                     width=24, anchor="w")
        om["menu"].configure(bg=PANEL, fg=FG)
        om.pack(side="left")

        def changed(*_a):
            app.cfg[cfg_key] = "" if var.get() == "(none)" else var.get()
            config.save()
        var.trace_add("write", changed)
        _btn(r, "test", lambda k=cfg_key: _play(app, app.cfg.get(k))).pack(side="left", padx=6)

    _sfx_row("headpat", "sfx_headpat")
    _sfx_row("good girl", "sfx_goodgirl")
    _sfx_row("error", "sfx_error")

    srow = tk.Frame(w, bg=BG)
    srow.pack(fill="x", padx=14, pady=(2, 4))
    _btn(srow, "Open sfx folder", lambda: app.rt.platform.open_path(app.rt.paths.sfx_dir)
         ).pack(side="left")
    tk.Label(srow, text="  drop .mp3 files there", bg=BG, fg=MUTED,
             font=("Segoe UI", 8)).pack(side="left")

    def save():
        app.cfg["base_url"] = url.get().strip()
        app.cfg["api_key"] = key.get().strip()
        app.cfg["workspace"] = os.path.expanduser(ws.get().strip() or "~")
        try:
            app.cfg["temperature"] = float(temp.get())
        except Exception:
            pass
        app.cfg["confirm"] = bool(confv.get())
        app.cfg["idle"] = bool(idle_v.get())
        app.cfg["idle_evolve"] = bool(ev_v.get())
        try:
            app.cfg["idle_evolve_minutes"] = max(1, int(float(ev_min.get())))
        except Exception:
            pass
        app.cfg["sfx"] = bool(sfx_v.get())
        app.cfg["sfx_volume"] = int(vol_v.get())
        config.save()
        app.say("saved", 1400)
        app._refresh_models()

    _btn(w, "Save settings", save).pack(anchor="w", padx=14, pady=(0, 10))

    tk.Label(w, text="MCP servers", bg=BG, fg=FG,
             font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14)
    box = tk.Frame(w, bg=BG)
    box.pack(fill="x", padx=14, pady=4)
    for row in mcp.status():
        r = tk.Frame(box, bg=BG)
        r.pack(fill="x")
        v = tk.BooleanVar(value=row["enabled"])

        def toggle(name=row["name"], v=v):
            conf = mcp.load_conf()
            if name not in conf:
                return
            conf[name]["enabled"] = bool(v.get())
            mcp.save_conf(conf)
            with mcp.LOCK:
                c = mcp.SERVERS.pop(name, None)
            if c:
                c.stop()
            if v.get():
                threading.Thread(target=mcp.start_all, args=([name],), daemon=True).start()
            app.lbl_mcp.configure(text=app._mcp_line())
            app._refresh_models()

        tk.Checkbutton(r, variable=v, command=toggle, bg=BG, fg=FG, selectcolor=PANEL,
                       activebackground=BG, activeforeground=FG).pack(side="left")
        tk.Label(r, text=row["name"], bg=BG, fg=FG,
                 font=("Consolas", 9)).pack(side="left")
        st, col = ("off", MUTED)
        if row["ready"]:
            st, col = "%d tools" % row["tools"], "#22c55e"
        elif row["error"]:
            st, col = "failed", "#ef4444"
        tk.Label(r, text=st, bg=BG, fg=col, font=("Segoe UI", 8)).pack(side="left", padx=8)

    brow = tk.Frame(w, bg=BG)
    brow.pack(fill="x", padx=14, pady=12)
    _btn(brow, "Calibration", app.open_calibration).pack(side="left")
    _btn(brow, "Load image", app._pick_image).pack(side="left", padx=6)
    _btn(brow, "Output", lambda: app.rt.platform.open_path(app.rt.paths.output)
         ).pack(side="left")
    _btn(brow, "Log", lambda: app.rt.platform.open_path(app.rt.paths.log)
         ).pack(side="left", padx=6)
    _btn(brow, "Memory", lambda: open_memory(app))


def _sfx_files(app):
    try:
        return sorted(n for n in os.listdir(app.rt.paths.sfx_dir)
                      if n.lower().endswith((".mp3", ".wav", ".ogg", ".m4a", ".flac")))
    except Exception:
        return []


def _play(app, name):
    p = os.path.join(app.rt.paths.sfx_dir, os.path.basename(name or ""))
    if os.path.isfile(p):
        app.rt.audio.play(p, int(app.cfg.get("sfx_volume") or 80))


def open_calibration(app):
    if app.cal_win and app.cal_win.winfo_exists():
        app.cal_win.deiconify()
        app.cal_win.lift()
        return
    w = tk.Toplevel(app.root)
    app.cal_win = w
    w.title("MalO - calibration")
    w.configure(bg=BG)
    w.geometry("500x600")
    w.transient(app.root)

    app.rig.calm = True
    app.rig.show_zones = True
    app._zones()

    def close():
        app.rig.show_zones = False
        app.rig.calm = False
        app.canvas.delete("zone")
        w.destroy()
    w.protocol("WM_DELETE_WINDOW", close)

    tk.Label(w, text="Line the ear and mouth zones up with the picture",
             bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=12, pady=(10, 2))

    showv = tk.BooleanVar(value=True)
    top = tk.Frame(w, bg=BG)
    top.pack(fill="x", padx=12)
    tk.Checkbutton(top, text="show zones", variable=showv,
                   command=lambda: (setattr(app.rig, "show_zones", bool(showv.get())),
                                    app._zones()),
                   bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG,
                   activeforeground=FG, font=("Segoe UI", 9)).pack(side="left")
    _btn(top, "reset", app._cal_reset).pack(side="right")

    for side, label in (("L", "Left ear"), ("R", "Right ear"), ("M", "Mouth patch")):
        f = tk.Frame(w, bg=BG)
        f.pack(fill="x", padx=12, pady=4)
        tk.Label(f, text=label, bg=BG, fg=FG,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        for key, lab in (("cx", "X"), ("cy", "Y"), ("rx", "W"), ("ry", "H")):
            r = tk.Frame(f, bg=BG)
            r.pack(fill="x")
            tk.Label(r, text=lab, bg=BG, fg=MUTED, width=2,
                     font=("Segoe UI", 8)).pack(side="left")
            lo, hi = (25.0, 75.0) if key == "cx" else (0.0, 24.0)
            var = tk.DoubleVar(value=app.rig.tune[side][key])
            tk.Scale(r, from_=lo, to=hi, resolution=0.2, orient="horizontal",
                     variable=var, bg=BG, fg=FG, troughcolor=PANEL,
                     highlightthickness=0, activebackground=ACCENT, length=340,
                     font=("Segoe UI", 7),
                     command=lambda val, s=side, k=key: app._cal(s, k, float(val))
                     ).pack(side="left", fill="x", expand=True)

    tk.Label(w, text="Reactions", bg=BG, fg=FG,
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
    rx = tk.Frame(w, bg=BG)
    rx.pack(fill="x", padx=12)
    for icon in theme.REACTIONS:
        _btn(rx, theme.GLYPH.get(icon, "?"), lambda i=icon: app.react(i)).pack(side="left", padx=2)

    tk.Label(w, text="States", bg=BG, fg=FG,
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
    st = tk.Frame(w, bg=BG)
    st.pack(fill="x", padx=12)
    for name in theme.STATES:
        _btn(st, name, lambda n=name: app.set_state(n)).pack(side="left", padx=2, pady=2)

def open_memory(app):
    from ...core import memory
    if getattr(app, "mem_win", None) and app.mem_win.winfo_exists():
        app.mem_win.deiconify(); app.mem_win.lift(); return
    w = tk.Toplevel(app.root)
    app.mem_win = w
    w.title("MalO - memory")
    w.configure(bg=BG)
    w.geometry("620x560")
    w.transient(app.root)

    top = tk.Frame(w, bg=BG)
    top.pack(fill="x", padx=12, pady=8)
    qv = tk.StringVar()
    e = tk.Entry(top, textvariable=qv, bg=PANEL, fg=FG, relief="flat", insertbackground=FG)
    e.pack(side="left", fill="x", expand=True)
    body = tk.Frame(w, bg=BG)
    body.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    def render(*_a):
        for ch in body.winfo_children():
            ch.destroy()
        for r in memory.listing(qv.get()):
            row = tk.Frame(body, bg=PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text="%s:%d%s" % (r["kind"][0], r["id"], "*" if r["pinned"] else ""),
                     bg=PANEL, fg=ACCENT, font=("Consolas", 8), width=8,
                     anchor="w").pack(side="left")
            tk.Label(row, text=r["text"][:90], bg=PANEL, fg=FG, font=("Segoe UI", 8),
                     anchor="w", justify="left", wraplength=380).pack(side="left", fill="x",
                                                                     expand=True)
            tk.Label(row, text="%dh" % max(1, int((time.time() - r["seen"]) / 3600)),
                     bg=PANEL, fg=MUTED, font=("Segoe UI", 7)).pack(side="left", padx=4)
            _btn(row, "pin", lambda i=r["id"], p=r["pinned"]: (memory.set_pinned(i, not p), render())
                 ).pack(side="left", padx=2)
            _btn(row, "del", lambda i=r["id"]: (memory.forget(mid=i), render())
                 ).pack(side="left", padx=2)

    e.bind("<KeyRelease>", render)
    _btn(top, "clear", lambda: (qv.set(""), render())).pack(side="left", padx=4)
    render()