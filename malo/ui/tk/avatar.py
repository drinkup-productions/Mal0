"""Avatar rig. Same compositing as before; PIL only, no Tk outside the canvas."""
import json
import math
import os
import random
import time

from PIL import Image, ImageTk

from ...core import config, personas, log as _log
from . import theme

PAD = 18
ANGLE_EPS = 0.015
ACTS = ("flick", "tilt", "peek", "hop", "stretch", "glance")
ACT_DUR = {"flick": 0.85, "tilt": 1.6, "peek": 1.8, "hop": 0.80, "stretch": 1.5, "glance": 1.5}

DEFAULT_TUNE = {"L": {"cx": 43.5, "cy": 7.0, "rx": 11.0, "ry": 8.0},
                "R": {"cx": 55.7, "cy": 6.6, "rx": 11.0, "ry": 8.0},
                "M": {"cx": 53.0, "cy": 23.0, "rx": 11.0, "ry": 8.0}}


def load_tune():
    t = json.loads(json.dumps(DEFAULT_TUNE))
    p = os.path.join(config.paths().root, "tune.json")
    try:
        with open(p, encoding="utf-8-sig") as fh:
            raw = json.load(fh)
        for k in ("L", "R", "M"):
            for a in ("cx", "cy", "rx", "ry"):
                if a in (raw.get(k) or {}):
                    t[k][a] = float(raw[k][a])
    except Exception:
        pass
    return t


def save_tune(t):
    try:
        with open(os.path.join(config.paths().root, "tune.json"), "w", encoding="utf-8") as fh:
            json.dump(t, fh, indent=2)
    except Exception:
        pass


def radial_mask(size, center, rx, ry, inner):
    w, h = size
    step = max(1, max(w, h) // 32)
    sw, sh = max(2, (w + step - 1) // step), max(2, (h + step - 1) // step)
    sx, sy = rx * sw / float(w), ry * sh / float(h)
    scx, scy = center[0] * sw / float(w), center[1] * sh / float(h)
    span = max(1e-6, 1.0 - inner)
    m = Image.new("L", (sw, sh), 0)
    px = m.load()
    for y in range(sh):
        dy = (y + 0.5 - scy) / sy
        for x in range(sw):
            dx = (x + 0.5 - scx) / sx
            r = math.sqrt(dx * dx + dy * dy)
            if r < 1.0:
                px[x, y] = 255 if r <= inner else int(255 * (r - inner) / span)
    return m.resize((w, h), Image.BILINEAR) if (sw, sh) != (w, h) else m


class Patch:
    __slots__ = ("rgba", "pivot", "anchor")

    def __init__(self, rgba, pivot, anchor):
        self.rgba, self.pivot, self.anchor = rgba, pivot, anchor


class AvatarRig:
    def __init__(self, canvas):
        self.canvas = canvas
        self.tune = load_tune()
        self.raw = self.ears = self.jaws = None
        self.ears = {"L": None, "R": None}
        self.jaws = [None, None, None]
        self.W = self.H = self.ox = self.oy = 0
        self.item = self._shown = None
        self._tk_cache, self._blend_lut = {}, {}
        self._base_ang, self._base_rgb, self._base_alpha = 1e9, None, None
        self._base_ca, self._base_sa = 1.0, 0.0
        self.t = 0.0
        self.last_t = time.time()
        self.mx = self.my = self.tmx = self.tmy = self.nod = 0.0
        self.ear_cur = {"L": 0.0, "R": 0.0}
        self.ear_tgt = {"L": 0.0, "R": 0.0}
        self.twitch = {"L": 0.0, "R": 0.0}
        self.open = self.open_tgt = self.burst = 0.0
        self.talking = False
        self.act = None
        self.act_left = self.gap_left = 0.0
        self.act_side, self.act_sign = "L", 1.0
        self.add_tilt = self.add_dx = self.add_dy = 0.0
        self.add_sx = self.add_sy = 1.0
        self.add_ear = {"L": 0.0, "R": 0.0}
        self.calm = self.show_zones = False

    # geometry, crop, rebuild, render, blit — identical to the monolith,
    # with personas.base_image/jaw_image substituted in.

    def _geom(self, side):
        t = self.tune[side]
        cx, cy = t["cx"] / 100 * self.W, t["cy"] / 100 * self.H
        rx, ry = max(8.0, t["rx"] / 100 * self.W), max(8.0, t["ry"] / 100 * self.H)
        return cx, cy, rx, ry, (max(0, int(cx - rx)), max(0, int(cy - ry)),
                                min(self.W, int(cx + rx)), min(self.H, int(cy + ry)))

    def load(self, path):
        self.canvas.delete("all")
        self.item = self._shown = None
        self._tk_cache.clear()
        self._base_ang, self._base_rgb, self._base_alpha = 1e9, None, None
        self.raw = None
        self.ears = {"L": None, "R": None}
        self.jaws = [None, None, None]
        self.last_t = time.time()
        if not path or not os.path.isfile(path):
            return
        cw, ch = max(160, self.canvas.winfo_width()), max(200, self.canvas.winfo_height())
        try:
            src = Image.open(path).convert("RGBA")
        except Exception as exc:
            _log.log("avatar: %s" % exc)
            return
        h = int((ch - 2 * PAD) * 0.98)
        w = int(h * 2 / 3)
        if w > cw - 30:
            w, h = cw - 30, int((cw - 30) * 1.5)
        if w < 60 or h < 90:
            return
        self.W, self.H = w, h
        self.raw = src.resize((w, h), Image.LANCZOS)
        self.ox, self.oy = (cw - w) // 2, ch - h - PAD
        self.canvas.create_oval(self.ox + w * 0.2, self.oy + h - 18,
                                self.ox + w * 0.8, self.oy + h - 2,
                                fill="#8f88a8", outline="", tags="shadow")
        self.canvas.tag_lower("shadow")
        self.rebuild()

    def rebuild(self):
        if self.raw is None:
            return
        pid = personas.active(config.CFG)
        for side in ("L", "R"):
            cx, cy, rx, ry, box = self._geom(side)
            if box[2] - box[0] < 6:
                self.ears[side] = None
                continue
            crop = self.raw.crop(box).copy()
            crop.putalpha(radial_mask(crop.size, (cx - box[0], cy - box[1]), rx, ry, 0.58))
            anc = (cx, cy + ry * 0.62)
            self.ears[side] = Patch(crop, (anc[0] - box[0], anc[1] - box[1]), anc)
        cx, cy, rx, ry, box = self._geom("M")
        mask = None
        if box[2] - box[0] >= 6 and box[3] - box[1] >= 6:
            mask = radial_mask((box[2] - box[0], box[3] - box[1]),
                               (cx - box[0], cy - box[1]), rx, ry, 0.72)
        for i, name in enumerate(("jaw-slight.png", "jaw-half.png", "jaw-wide.png")):
            p = personas.jaw_image(pid, name)
            if not p or mask is None:
                self.jaws[i] = None
                continue
            im = Image.open(p).convert("RGBA").resize((self.W, self.H), Image.LANCZOS)
            crop = im.crop(box).copy()
            crop.putalpha(mask)
            self.jaws[i] = Patch(crop, (cx - box[0], cy - box[1]), (cx, cy))

    def flap(self, ms):
        self.burst = max(self.burst, time.time() + ms / 1000.0)

    def _pick(self):
        self.act = random.choice(ACTS)
        self.act_left = ACT_DUR[self.act]
        self.act_side = random.choice(("L", "R"))
        self.act_sign = random.choice((1.0, -1.0))

    def _blit(self, frame):
        key = (frame.width, frame.height)
        img = self._tk_cache.pop(key, None)
        if img is None:
            img = ImageTk.PhotoImage(frame)
        else:
            try:
                img.paste(frame)
            except Exception:
                img = ImageTk.PhotoImage(frame)
        prev = self._shown
        if prev is not None and prev is not img:
            self._tk_cache[(prev.width(), prev.height())] = prev
            while len(self._tk_cache) > 12:
                self._tk_cache.pop(next(iter(self._tk_cache)))
        self._shown = img
        return img

    def render(self):
        now = time.time()
        dt = min(0.08, max(0.001, now - self.last_t))
        self.last_t = now
        self.t += dt
        self.mx += (self.tmx - self.mx) * 0.07
        self.my += (self.tmy - self.my) * 0.07
        self.nod += (0.0 - self.nod) * 0.22
        if self.raw is None:
            return
        for k in ("L", "R"):
            self.ear_cur[k] += (self.ear_tgt[k] + self.twitch[k] - self.ear_cur[k]) * 0.14
            self.twitch[k] *= 0.86
        self.open += (self.open_tgt - self.open) * (0.38 if self.open_tgt > self.open else 0.24)
        if self.talking or now < self.burst:
            r = random.random()
            self.open_tgt = (0.02 if r < 0.10 else 0.20 + r * 0.30 if r < 0.42
                             else 0.55 + r * 0.30 if r < 0.82 else 1.0)
        else:
            self.open_tgt = 0.0

        self.add_tilt = self.add_dx = self.add_dy = 0.0
        self.add_sx = self.add_sy = 1.0
        self.add_ear["L"] = self.add_ear["R"] = 0.0
        if self.act:
            self.act_left -= dt
            if self.act_left <= 0:
                self.act, self.gap_left = None, random.uniform(2.4, 6.0)
        else:
            self.gap_left -= dt
            if self.gap_left <= 0 and not self.calm and not self.talking and config.get("idle", True):
                self._pick()
        if self.act:
            u = max(0.0, min(1.0, 1.0 - self.act_left / max(0.01, ACT_DUR[self.act])))
            e = math.sin(math.pi * u)
            if self.act == "flick":
                self.add_ear[self.act_side] = 26.0 * self.act_sign * (e ** 2)
            elif self.act == "tilt":
                self.add_tilt, self.add_dx = 4.0 * e, 3.0 * e
                self.add_ear["L"], self.add_ear["R"] = 5.0 * e, -5.0 * e
            elif self.act == "peek":
                self.add_dx = 10.0 * e * self.act_sign
                self.add_tilt = -2.5 * e * self.act_sign
                self.add_ear["L"], self.add_ear["R"] = 6.0 * e, -6.0 * e
            elif self.act == "hop":
                self.add_dy = -16.0 * (e ** 0.6)
                self.add_sy, self.add_sx = 1.0 + 0.06 * e, 1.0 - 0.04 * e
            elif self.act == "stretch":
                self.add_sy, self.add_sx = 1.0 + 0.055 * e, 1.0 - 0.035 * e
                self.add_ear["L"], self.add_ear["R"] = 9.0 * e, -9.0 * e
            elif self.act == "glance":
                self.add_dx = 5.0 * e * self.act_sign
                self.add_ear["L"] = self.add_ear["R"] = -7.0 * e * self.act_sign

        if self.calm:
            br = lean = shift = sway = bob = 0.0
        else:
            br = math.sin(self.t * 0.95)
            lean, shift = math.sin(self.t * 0.44) * 2.4, math.sin(self.t * 0.44) * 0.9
            sway = math.sin(self.t * 0.83) * 0.9
            bob = math.sin(self.t * 1.7) * 2.2 + math.sin(self.t * 0.61) * 1.3

        ang = -(sway + shift) - self.add_tilt
        dx = self.mx + lean + self.add_dx
        dy = bob + self.my + self.nod * 3 + self.add_dy
        sy = 1.0 + br * 0.009 + (self.add_sy - 1.0)
        sx = 1.0 - br * 0.005 + (self.add_sx - 1.0)
        cx, cy = self.W / 2.0, self.H * 0.75

        if self._base_rgb is None or abs(ang - self._base_ang) > ANGLE_EPS:
            base = self.raw.rotate(ang, resample=Image.BILINEAR, center=(cx, cy))
            self._base_ang = ang
            self._base_rgb = base.convert("RGB")
            self._base_alpha = base.getchannel("A")
            th = math.radians(ang)
            self._base_ca, self._base_sa = math.cos(th), math.sin(th)
        ca, sa = self._base_ca, self._base_sa

        def rot(x, y):
            ax, ay = x - cx, y - cy
            return (cx + ax * ca + ay * sa, cy - ax * sa + ay * ca)

        rgb = self._base_rgb.copy()
        for side in ("L", "R"):
            p = self.ears.get(side)
            if p is None:
                continue
            r = p.rgba.rotate(-(self.ear_cur[side] + self.add_ear[side]),
                              resample=Image.BILINEAR, center=p.pivot)
            tx, ty = rot(p.anchor[0], p.anchor[1])
            rgb.paste(r.convert("RGB"), (int(tx - p.pivot[0]), int(ty - p.pivot[1])),
                      r.getchannel("A"))

        o, a, b, c = self.open, 0.0, 0.0, 0.0
        if o <= 0.5:
            a = o * 2
        elif o <= 0.8:
            a, b = 1.0, (o - 0.5) / 0.3
        else:
            a, b, c = 1.0, 1.0, (o - 0.8) / 0.2
        for i, amt in enumerate((a, b, c)):
            p = self.jaws[i]
            if p is None or amt <= 0.01:
                continue
            r = p.rgba.rotate(-self._base_ang, resample=Image.BILINEAR, center=p.pivot)
            m = r.getchannel("A")
            if amt < 0.999:
                k = int(amt * 64)
                lut = self._blend_lut.get(k)
                if lut is None:
                    lut = [int(v * amt) for v in range(256)]
                    self._blend_lut[k] = lut
                m = m.point(lut)
            tx, ty = rot(p.anchor[0], p.anchor[1])
            rgb.paste(r.convert("RGB"), (int(tx - p.pivot[0]), int(ty - p.pivot[1])), m)

        frame = Image.merge("RGBA", (*rgb.split(), self._base_alpha))
        if abs(sx - 1.0) > 0.0015 or abs(sy - 1.0) > 0.0015:
            nw, nh = max(8, int(self.W * sx)), max(8, int(self.H * sy))
            frame = frame.resize((nw, nh), Image.BILINEAR)
            dx += (self.W - nw) / 2.0
            dy += (self.H - nh)

        photo = self._blit(frame)
        x, y = self.ox + dx, self.oy + dy
        if self.item is None:
            self.item = self.canvas.create_image(x, y, image=photo, anchor="nw")
        else:
            self.canvas.itemconfig(self.item, image=photo)
            self.canvas.coords(self.item, x, y)