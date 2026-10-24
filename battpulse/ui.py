"""BattPulse GUI."""

from __future__ import annotations

import ctypes
import threading
import time
import tkinter as tk
from tkinter import ttk

from . import __version__
from .batt import BattExtra, BattSnap, extra, sample
from .power import sample_power
from .instance import WINDOW_TITLE
from .settings import INTERVALS, load_interval, save_interval

BG = "#111111"
FG = "#ffffff"
MUTED = "#999999"
CARD = "#1a1a1a"
BAR = "#333333"
BTN = "#333333"
ACCENT = "#93c5fd"
OK = "#86efac"
WARN = "#fca5a5"
HOT = "#fde68a"


def _bar_color(pct: float) -> str:
    if pct <= 15:
        return WARN
    if pct <= 30:
        return HOT
    return OK


def _amt(ex: BattExtra, mwh: int | None) -> str:
    mah = ex.mah(mwh)
    if mah:
        return f"{mah} мА·ч"
    if mwh:
        return f"{mwh / 1000:.1f} Вт·ч"
    return ""


def _hm(secs: int) -> str:
    h, rem = divmod(secs, 3600)
    m = rem // 60
    if h <= 0:
        return f"{m} мин"
    return f"{h} ч {m:02d} мин"


class BattPulseApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("520x400")
        self.minsize(440, 360)
        self.configure(bg=BG)
        self._sec = load_interval()
        self._job: str | None = None
        self._hist: list[float] = []
        self._extra = BattExtra(None, "", None, None, None, None)
        self._wear_at = 0.0
        self._pwr_busy = False
        self._has_batt = False

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Dark.TCombobox",
            fieldbackground=CARD, background=BTN, foreground=FG, arrowcolor=FG,
            darkcolor=CARD, lightcolor=CARD, bordercolor=BTN,
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", CARD)],
            foreground=[("readonly", FG)],
            background=[("readonly", BTN)],
        )

        pad = tk.Frame(self, bg=BG)
        pad.pack(fill="both", expand=True, padx=22, pady=16)

        foot = tk.Frame(pad, bg=BG)
        foot.pack(fill="x", side="bottom", pady=(8, 0))
        tk.Label(
            foot, text="неделя 9 · день 61", bg=BG, fg=MUTED, font=("Segoe UI", 8)
        ).pack(side="left")
        tk.Label(foot, text=f"v{__version__} · darkshade", bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(side="right")
        labels = [lab for _, lab in INTERVALS]
        self._iv_var = tk.StringVar(value=next((lab for sec, lab in INTERVALS if sec == self._sec), "2 с"))
        self._iv = ttk.Combobox(
            foot, textvariable=self._iv_var, values=labels, state="readonly",
            width=5, style="Dark.TCombobox", font=("Segoe UI", 8),
        )
        self._iv.pack(side="right", padx=(0, 10))
        self._iv.bind("<<ComboboxSelected>>", lambda _e: self._on_interval())
        tk.Label(foot, text="обновление", bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(side="right", padx=(0, 6))

        head = tk.Frame(pad, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="BattPulse", bg=BG, fg=FG, font=("Segoe UI Semibold", 20)).pack(side="left", anchor="n")
        watts = tk.Frame(head, bg=BG)
        watts.pack(side="right", anchor="ne")
        self._watts = tk.Label(watts, text="— Вт", bg=BG, fg=ACCENT, font=("Segoe UI Semibold", 28), anchor="e")
        self._watts.pack(anchor="e")
        self._watts_src = tk.Label(watts, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="e")
        self._watts_src.pack(anchor="e")

        self._now = tk.Label(pad, text="—", bg=BG, fg=ACCENT, font=("Segoe UI Semibold", 32))
        self._now.pack(anchor="w", pady=(16, 0))
        self._mood = tk.Label(pad, text="", bg=BG, fg=MUTED, font=("Segoe UI", 12), wraplength=460, justify="left")
        self._mood.pack(anchor="w")

        tk.Label(pad, text="заряд сейчас", bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", pady=(12, 2))
        self._bar_track = tk.Frame(pad, bg=BAR, height=22)
        self._bar_track.pack(fill="x")
        self._bar_track.pack_propagate(False)
        self._bar_fill = tk.Frame(self._bar_track, bg=OK, height=22)
        self._bar_fill.place(relx=0, rely=0, relheight=1, relwidth=0)
        self._charge_lbl = tk.Label(pad, text="", bg=BG, fg=FG, font=("Segoe UI", 9))
        self._charge_lbl.pack(anchor="w", pady=(4, 0))

        tk.Label(pad, text="максимум сейчас", bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", pady=(12, 2))
        self._max_track = tk.Frame(pad, bg=BAR, height=22)
        self._max_track.pack(fill="x")
        self._max_track.pack_propagate(False)
        self._max_fill = tk.Frame(self._max_track, bg=ACCENT, height=22)
        self._max_fill.place(relx=0, rely=0, relheight=1, relwidth=0)
        self._max_lbl = tk.Label(pad, text="", bg=BG, fg=FG, font=("Segoe UI", 9))
        self._max_lbl.pack(anchor="w", pady=(4, 0))

        self._spark = tk.Canvas(pad, height=44, bg=CARD, highlightthickness=0)
        self._spark.pack(fill="x", pady=(10, 8))

        self._detail = tk.Label(pad, text="", bg=BG, fg=FG, font=("Segoe UI", 10), wraplength=460, justify="left")
        self._detail.pack(anchor="w")
        self._wear_lbl = tk.Label(pad, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), wraplength=460, justify="left")
        self._wear_lbl.pack(anchor="w", pady=(2, 0))

        self.bind("<Configure>", self._on_resize)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(20, self._place)
        self._job = self.after(200, self._tick)
        self.after(400, self._refresh_extra)

    def _alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _close(self) -> None:
        if self._job:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
        self.destroy()

    def _on_interval(self) -> None:
        lab = self._iv_var.get()
        for sec, name in INTERVALS:
            if name == lab:
                self._sec = sec
                save_interval(sec)
                self._schedule(0)
                return

    def _on_resize(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        w = max(320, event.width - 48)
        self._mood.configure(wraplength=w)
        self._detail.configure(wraplength=w)
        self._wear_lbl.configure(wraplength=w)
        self._draw_spark()

    def _place(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width() or 520, self.winfo_height() or 360
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        self.geometry(f"{w}x{h}+{(sw - w) // 2 + 160}+{(sh - h) // 6}")

    def _schedule(self, delay_ms: int | None = None) -> None:
        if self._job:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        ms = int(self._sec * 1000) if delay_ms is None else delay_ms
        self._job = self.after(max(0, ms), self._tick)

    def _tick(self) -> None:
        if not self._alive():
            return
        try:
            snap = sample()
        except Exception:
            snap = None
        if snap is None:
            self._now.configure(text="нет данных", fg=WARN)
            self._mood.configure(text="Windows не ответил про питание.", fg=WARN)
            has_batt = False
        else:
            self._apply(snap)
            has_batt = snap.present
        self._poll_power(has_batt)
        self._schedule()

    def _poll_power(self, has_battery: bool) -> None:
        if self._pwr_busy:
            return
        self._pwr_busy = True

        def work() -> None:
            try:
                pwr = sample_power(has_battery)
            except Exception:
                pwr = None

            def done() -> None:
                self._pwr_busy = False
                if not self._alive() or pwr is None:
                    return
                if pwr.watts is None:
                    self._watts.configure(text="— Вт", fg=MUTED)
                    self._watts_src.configure(text="нет датчика")
                    return
                self._watts.configure(text=f"{pwr.watts:.1f} Вт", fg=ACCENT)
                if pwr.source == "battery":
                    self._watts_src.configure(text="система с батареи")
                elif pwr.source == "gpu":
                    self._watts_src.configure(text="видеокарта · систему Windows не меряет")
                else:
                    self._watts_src.configure(text="")

            try:
                self.after(0, done)
            except tk.TclError:
                self._pwr_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, snap: BattSnap) -> None:
        self._has_batt = snap.present
        if not snap.present:
            self._now.configure(text="батареи нет", fg=MUTED)
            plug = "ПК на розетке." if snap.on_ac else "Питание не через батарею."
            self._mood.configure(
                text=f"{plug} Windows не видит аккумулятор — на этом железе так и должно быть.",
                fg=MUTED,
            )
            self._bar_fill.place(relx=0, rely=0, relheight=1, relwidth=0)
            self._max_fill.place(relx=0, rely=0, relheight=1, relwidth=0)
            self._charge_lbl.configure(text="")
            self._max_lbl.configure(text="")
            self._detail.configure(text="")
            self._wear_lbl.configure(text="")
            self._hist = []
            self._draw_spark()
            return
        pct = 0.0 if snap.percent is None else float(snap.percent)
        if snap.percent is not None:
            self._hist.append(pct)
            self._hist = self._hist[-60:]
            self._now.configure(text=f"{snap.percent} %", fg=_bar_color(pct))
        else:
            self._now.configure(text="— %", fg=MUTED)
        if snap.charging:
            mood = "заряжается"
        elif snap.on_ac:
            mood = "на розетке, не заряжается"
        elif snap.on_ac is False:
            mood = "от батареи"
        else:
            mood = "питание неизвестно"
        self._mood.configure(text=mood, fg=FG)
        self._bar_fill.configure(bg=_bar_color(pct))
        self._bar_fill.place(relx=0, rely=0, relheight=1, relwidth=max(0.02, pct / 100.0) if snap.percent else 0)
        ch = _amt(self._extra, self._extra.remain_mwh)
        if snap.percent is not None:
            self._charge_lbl.configure(text=f"{snap.percent} %" + (f"  ·  {ch}" if ch else ""))
        else:
            self._charge_lbl.configure(text=ch)
        bits = []
        if snap.secs_left is not None:
            bits.append("осталось " + _hm(snap.secs_left))
        if self._extra.name:
            bits.append(self._extra.name)
        self._detail.configure(text=" · ".join(bits))
        self._paint_max()
        self._draw_spark()

    def _paint_max(self) -> None:
        if not self._has_batt:
            self._max_fill.place(relx=0, rely=0, relheight=1, relwidth=0)
            self._max_lbl.configure(text="")
            self._wear_lbl.configure(text="")
            return
        ex = self._extra
        mx = ex.max_pct
        if mx is None:
            self._max_fill.place(relx=0, rely=0, relheight=1, relwidth=0)
            self._max_lbl.configure(text="Windows не отдал ёмкость")
            self._wear_lbl.configure(text="")
            return
        self._max_fill.configure(bg=_bar_color(mx))
        self._max_fill.place(relx=0, rely=0, relheight=1, relwidth=max(0.02, mx / 100.0))
        full = _amt(ex, ex.full_mwh)
        factory = _amt(ex, ex.designed_mwh)
        line = f"{mx:.0f} %"
        if full:
            line += f"  ·  {full}"
        self._max_lbl.configure(text=line)
        extra = []
        if factory:
            extra.append(f"завод {factory}")
        if ex.wear_pct is not None:
            extra.append(f"износ {ex.wear_pct:.0f}%")
        self._wear_lbl.configure(text=" · ".join(extra))

    def _draw_spark(self) -> None:
        c = self._spark
        c.delete("all")
        w = max(40, c.winfo_width())
        h = 44
        n = len(self._hist)
        if n < 2:
            return
        step = w / max(1, n)
        for i, v in enumerate(self._hist):
            x0 = i * step
            bh = max(1, int(h * v / 100.0))
            c.create_rectangle(x0, h - bh, x0 + step - 1, h, fill=_bar_color(v), outline="")

    def _refresh_extra(self) -> None:
        if not self._alive():
            return
        if time.monotonic() - self._wear_at < 30 and self._wear_at:
            self.after(5000, self._refresh_extra)
            return

        def work() -> None:
            try:
                info = extra()
            except Exception:
                info = BattExtra(None, "", None, None, None, None)

            def done() -> None:
                if not self._alive():
                    return
                self._extra = info
                self._wear_at = time.monotonic()
                self._paint_max()
                self.after(30000, self._refresh_extra)

            try:
                self.after(0, done)
            except tk.TclError:
                return

        threading.Thread(target=work, daemon=True).start()


def run() -> None:
    BattPulseApp().mainloop()
