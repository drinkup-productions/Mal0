"""Kivy UI: chat, persona switcher, model picker. No avatar, tray or autonomy."""
import threading

from kivy.clock import Clock
from kivy.app import App as KApp
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from ...core import config, engine, events as E, ledger, personas, provider
from ...tools import mcp


class ChatApp(KApp):
    def __init__(self, rt, **kw):
        super().__init__(**kw)
        self.rt = rt
        self.cfg = rt.cfg
        self.history = []
        self.buf = []
        self.streaming = False
        self.engine = None
        self.models = []

    def build(self):
        self.title = "MalO"
        root = BoxLayout(orientation="vertical", padding=dp(6), spacing=dp(4))

        top = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(4))
        self.persona = Spinner(text=personas.active(self.cfg),
                               values=[p["id"] for p in personas.brief()])
        self.persona.bind(text=self._persona)
        self.model = Spinner(text=self.cfg.get("model") or "(none)")
        self.model.bind(text=self._model)
        top.add_widget(self.persona)
        top.add_widget(self.model)
        root.add_widget(top)

        self.scroll = ScrollView()
        self.log = Label(size_hint_y=None, markup=True, valign="top",
                         text_size=(None, None), padding=(dp(4), dp(4)))
        self.log.bind(texture_size=lambda i, v: setattr(i, "height", v[1]))
        self.scroll.add_widget(self.log)
        root.add_widget(self.scroll)

        bottom = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(4))
        self.input = TextInput(multiline=False, hint_text="say something")
        self.input.bind(on_text_validate=lambda *_: self.send())
        self.send_btn = Button(text="Send", size_hint_x=None, width=dp(64))
        self.send_btn.bind(on_release=lambda *_: self.send())
        bottom.add_widget(self.input)
        bottom.add_widget(self.send_btn)
        root.add_widget(bottom)

        Clock.schedule_interval(self._pump, 0.05)
        threading.Thread(target=self._load_models, daemon=True).start()
        g = personas.greeting(personas.active(self.cfg))
        if g:
            self._add("malo: " + g)
            self.history.append({"role": "assistant", "content": g})
        return root

    def _add(self, line):
        self.buf.append(line)
        self.log.text = "\n".join(self.buf[-400:])
        self.scroll.scroll_y = 0

    def _load_models(self):
        try:
            ids = provider.build(self.cfg).models()
        except Exception:
            ids = []
        Clock.schedule_once(lambda *_: self._set_models(ids), 0)

    def _set_models(self, ids):
        self.models = ids
        self.model.values = ids or ["(none)"]

    def _persona(self, _w, pid):
        self.cfg["persona"] = pid
        want = (personas.PERSONAS.get(pid) or {}).get("model") or ""
        if want:
            self.cfg["model"] = want
            self.model.text = want
        config.save()
        self._add("-- persona: %s --" % pid)

    def _model(self, _w, value):
        if value and value != "(none)":
            self.cfg["model"] = value
            config.save()

    def send(self):
        text = (self.input.text or "").strip()
        if not text or self.streaming:
            return
        model = self.cfg.get("model")
        if not model:
            self._add("! no model selected")
            return
        self.input.text = ""
        self._add("you: " + text)
        self.history.append({"role": "user", "content": text})
        self.streaming = True
        self.send_btn.disabled = True
        self.engine = engine.Engine(self.rt.bus, self.cfg)
        threading.Thread(target=self.engine.run,
                         args=(list(self.history), model, self.rt.platform.name),
                         daemon=True).start()

    def _pump(self, _dt):
        self.rt.bus.drain(self._handle)
        return True

    def _handle(self, ev):
        t = ev.get("type")
        if t == E.DELTA:
            if self.buf and self.buf[-1].startswith("malo: "):
                self.buf[-1] += ev["text"]
                self.log.text = "\n".join(self.buf[-400:])
                self.scroll.scroll_y = 0
            else:
                self._add("malo: " + ev["text"])
        elif t == E.TOOL:
            self._add("[b]%s[/b]" % ev.get("name"))
        elif t == E.TOOL_RESULT:
            self._add("  " + str(ev.get("text"))[:300])
        elif t == E.CONFIRM:
            self.engine.approve(ev["id"], True)
        elif t == E.TURN:
            for m in ev.get("messages") or []:
                if m.get("role") != "system":
                    self.history.append(m)
            while len(self.history) > 60:
                self.history.pop(0)
            self.streaming = False
            self.send_btn.disabled = False
        elif t == E.ERROR:
            self._add("! " + str(ev.get("text")))