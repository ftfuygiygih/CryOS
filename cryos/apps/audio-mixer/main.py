#!/usr/bin/env python3
"""
CryOS Audio Mixer  —  apps/audio-mixer/main.py
================================================
Слайдеры громкости по приложениям (PulseAudio/PipeWire).
Выбор устройства вывода/ввода, индикатор уровня сигнала.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio
import subprocess, sys, re
from pathlib import Path

CRYOS_ROOT = Path(__file__).parent.parent.parent
THEME_CSS  = CRYOS_ROOT / "system" / "theme" / "gtk.css"


def pactl(*args) -> str:
    try:
        return subprocess.check_output(["pactl", *args], text=True,
                                        stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def get_sinks() -> list[dict]:
    out = pactl("list", "sinks")
    sinks = []
    current: dict = {}
    for line in out.splitlines():
        if line.startswith("Sink #"):
            if current:
                sinks.append(current)
            current = {"id": line.split("#")[1].strip()}
        elif "Name:" in line and "id" in current and "name" not in current:
            current["name"] = line.split(":", 1)[1].strip()
        elif "Volume:" in line and "volume" not in current:
            m = re.search(r"(\d+)%", line)
            current["volume"] = int(m.group(1)) if m else 50
        elif "Description:" in line and "desc" not in current:
            current["desc"] = line.split(":", 1)[1].strip()
    if current:
        sinks.append(current)
    return sinks


def get_sink_inputs() -> list[dict]:
    out = pactl("list", "sink-inputs")
    inputs = []
    current: dict = {}
    for line in out.splitlines():
        if line.startswith("Sink Input #"):
            if current:
                inputs.append(current)
            current = {"id": line.split("#")[1].strip()}
        elif "application.name" in line and "name" not in current:
            current["name"] = line.split("=", 1)[1].strip().strip('"')
        elif "Volume:" in line and "volume" not in current:
            m = re.search(r"(\d+)%", line)
            current["volume"] = int(m.group(1)) if m else 50
        elif "Mute:" in line and "mute" not in current:
            current["mute"] = "yes" in line.lower()
    if current:
        inputs.append(current)
    return inputs


class SinkRow(Gtk.Box):
    def __init__(self, sink: dict):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.sink = sink
        self.set_margin_top(4); self.set_margin_bottom(4)

        icon = Gtk.Label(label="🔊")
        self.append(icon)

        name_lbl = Gtk.Label(label=sink.get("desc", sink.get("name","?"))[:40])
        name_lbl.set_hexpand(True)
        name_lbl.set_halign(Gtk.Align.START)
        self.append(name_lbl)

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_value(sink.get("volume", 50))
        self.scale.set_size_request(200, -1)
        self.scale.connect("value-changed", self._on_volume)
        self.append(self.scale)

        self.vol_lbl = Gtk.Label(label=f"{sink.get('volume',50)}%")
        self.vol_lbl.set_size_request(42, -1)
        self.append(self.vol_lbl)

        mute_btn = Gtk.Button(label="🔇")
        mute_btn.set_has_frame(False)
        mute_btn.connect("clicked", self._toggle_mute)
        self.append(mute_btn)

    def _on_volume(self, scale):
        val = int(scale.get_value())
        self.vol_lbl.set_text(f"{val}%")
        pactl("set-sink-volume", self.sink["id"], f"{val}%")

    def _toggle_mute(self, *_):
        pactl("set-sink-mute", self.sink["id"], "toggle")


class AppRow(Gtk.Box):
    def __init__(self, inp: dict):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.inp = inp
        self.set_margin_top(4); self.set_margin_bottom(4)

        icon = Gtk.Label(label="🎵")
        self.append(icon)

        name = inp.get("name", "Неизвестно")[:36]
        name_lbl = Gtk.Label(label=name)
        name_lbl.set_hexpand(True)
        name_lbl.set_halign(Gtk.Align.START)
        self.append(name_lbl)

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_value(inp.get("volume", 50))
        self.scale.set_size_request(200, -1)
        self.scale.connect("value-changed", self._on_volume)
        self.append(self.scale)

        self.vol_lbl = Gtk.Label(label=f"{inp.get('volume',50)}%")
        self.vol_lbl.set_size_request(42, -1)
        self.append(self.vol_lbl)

    def _on_volume(self, scale):
        val = int(scale.get_value())
        self.vol_lbl.set_text(f"{val}%")
        pactl("set-sink-input-volume", self.inp["id"], f"{val}%")


class AudioMixerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CryOS Звуковой микшер")
        self.set_default_size(560, 400)
        self.add_css_class("cry-window")

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        notebook = Gtk.Notebook()

        # Вкладка устройств
        dev_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        dev_box.set_margin_top(8); dev_box.set_margin_start(8); dev_box.set_margin_end(8)
        lbl = Gtk.Label(); lbl.set_markup('<b>Устройства вывода</b>')
        lbl.set_halign(Gtk.Align.START); dev_box.append(lbl)
        self._dev_box = dev_box
        notebook.append_page(dev_box, Gtk.Label(label="Устройства"))

        # Вкладка приложений
        app_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        app_outer.set_margin_top(8); app_outer.set_margin_start(8); app_outer.set_margin_end(8)
        lbl2 = Gtk.Label(); lbl2.set_markup('<b>Громкость приложений</b>')
        lbl2.set_halign(Gtk.Align.START); app_outer.append(lbl2)
        self._app_box = app_outer
        notebook.append_page(app_outer, Gtk.Label(label="Приложения"))

        vbox.append(notebook)

        refresh_btn = Gtk.Button(label="🔄 Обновить")
        refresh_btn.connect("clicked", lambda *_: self._refresh())
        refresh_btn.set_margin_top(4); refresh_btn.set_margin_bottom(4)
        vbox.append(refresh_btn)

        self.set_child(vbox)
        self._refresh()
        GLib.timeout_add(3000, self._auto_refresh)

    def _refresh(self):
        # Устройства
        for child in list(self._iter_children(self._dev_box))[1:]:
            self._dev_box.remove(child)
        for sink in get_sinks():
            self._dev_box.append(SinkRow(sink))
        if not get_sinks():
            self._dev_box.append(Gtk.Label(label="PulseAudio/PipeWire не найден"))

        # Приложения
        for child in list(self._iter_children(self._app_box))[1:]:
            self._app_box.remove(child)
        for inp in get_sink_inputs():
            self._app_box.append(AppRow(inp))
        if not get_sink_inputs():
            self._app_box.append(Gtk.Label(label="Нет активных источников звука"))

    def _iter_children(self, box):
        child = box.get_first_child()
        while child:
            yield child
            child = child.get_next_sibling()

    def _auto_refresh(self):
        self._refresh()
        return True


class AudioMixerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.cryos.AudioMixer",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        if THEME_CSS.exists():
            p = Gtk.CssProvider(); p.load_from_path(str(THEME_CSS))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        AudioMixerWindow(self).present()


def main():
    AudioMixerApp().run(sys.argv)

if __name__ == "__main__":
    main()
