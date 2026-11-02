"""OpenAI-compatible chat backend. Works against LM Studio, llama.cpp server,
or any remote endpoint that speaks the same wire format."""
import json
import urllib.error
import urllib.request


class ProviderError(RuntimeError):
    pass


class OpenAICompat:
    def __init__(self, base_url, api_key="", temperature=0.7, ctx=0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.temperature = temperature
        self.ctx = ctx

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = "Bearer " + self.api_key
        return h

    def models(self, timeout=4):
        req = urllib.request.Request(self.base_url + "/models", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return [m.get("id") for m in (json.loads(r.read()).get("data") or []) if m.get("id")]
        except Exception:
            return []

    def stream(self, messages, tools, stop, timeout=1800):
        """Yield parsed SSE chunks until [DONE] or stop is set."""
        payload = {"model": messages_model(messages), "stream": True,
                   "temperature": self.temperature, "messages": messages,
                   "stream_options": {"include_usage": True}}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if self.ctx:
            payload["context_length"] = int(self.ctx)
        req = urllib.request.Request(self.base_url + "/chat/completions",
                                     data=json.dumps(payload).encode(),
                                     method="POST", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as up:
                while not stop.is_set():
                    line = up.readline()
                    if not line:
                        break
                    s = line.decode("utf-8", "replace").strip()
                    if not s.startswith("data:"):
                        continue
                    s = s[5:].strip()
                    if s == "[DONE]":
                        break
                    try:
                        yield json.loads(s)
                    except Exception:
                        continue
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            raise ProviderError("HTTP %s %s" % (exc.code, body))
        except urllib.error.URLError as exc:
            raise ProviderError("cannot reach %s (%s)" % (self.base_url, exc.reason))


_MODEL = {"v": ""}


def set_model(m):
    _MODEL["v"] = m


def messages_model(_messages):
    return _MODEL["v"]


def build(cfg):
    return OpenAICompat(cfg.get("base_url") or "http://127.0.0.1:1234/v1",
                        cfg.get("api_key") or "",
                        float(cfg.get("temperature") or 0.7),
                        int(cfg.get("ctx") or 0))
                        
def complete(self, messages, timeout=90, max_tokens=400):
        payload = {"model": messages_model(messages), "messages": messages,
                   "temperature": 0.2, "max_tokens": max_tokens, "stream": False}
        req = urllib.request.Request(self.base_url + "/chat/completions",
                                     data=json.dumps(payload).encode(),
                                     method="POST", headers=self._headers())
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read())
        return ((j.get("choices") or [{}])[0].get("message") or {}).get("content") or ""