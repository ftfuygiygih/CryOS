#!/usr/bin/env python3
"""
CryOS Settings  —  apps/settings/main.py
=========================================
Единое окно настроек в стиле Win98.
Разделы: Внешний вид, Дисплей, Звук, Сеть,
         Пользователи, Автозапуск, О системе.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio
import subprocess, json, os, sys, platform
from pathlib import Path

CRYOS_ROOT = Path(__file__).parent.parent.parent
THEME_CSS  = CRYOS_ROOT / "system" / "theme" / "gtk.css"
CONFIG_DIR = Path.home() / ".config" / "cryos"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

VERSION_FILE = CRYOS_ROOT / "VERSION"


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except Exception:
            pass
    return {}

def save_settings(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ── Вкладка: Внешний вид ─────────────────────────────────────────
class AppearanceTab(Gtk.Box):
    def __init__(self, settings: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(12); self.set_margin_bottom(12)
        self.set_margin_start(16); self.set_margin_end(16)
        self.settings = settings

        self._add_section("🎨 Тема")
        theme_box = Gtk.Box(spacing=8)
        self.theme_combo = Gtk.ComboBoxText()
        for t in ["CryOS (по умолчанию)", "CryOS Dark", "Classic", "High Contrast"]:
            self.theme_combo.append_text(t)
        self.theme_combo.set_active(0)
        theme_box.append(Gtk.Label(label="Тема GTK:"))
        theme_box.append(self.theme_combo)
        self.append(theme_box)

        self._add_section("🖼 Обои")
        wall_box = Gtk.Box(spacing=8)
        self.wall_entry = Gtk.Entry()
        self.wall_entry.set_text(settings.get("wallpaper", ""))
        self.wall_entry.set_hexpand(True)
        self.wall_entry.set_placeholder_text("Путь к файлу обоев…")
        wall_btn = Gtk.Button(label="Обзор…")
        wall_btn.connect("clicked", self._browse_wallpaper)
        wall_box.append(self.wall_entry)
        wall_box.append(wall_btn)
        self.append(wall_box)

        self._add_section("🔤 Шрифт")
        font_box = Gtk.Box(spacing=8)
        font_box.append(Gtk.Label(label="Шрифт интерфейса:"))
        self.font_btn = Gtk.FontButton()
        self.font_btn.set_font(settings.get("font", "Sans 10"))
        font_box.append(self.font_btn)
        self.append(font_box)

        self._add_section("🗂 Иконки")
        icon_box = Gtk.Box(spacing=8)
        icon_box.append(Gtk.Label(label="Размер иконок рабочего стола:"))
        self.icon_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 32, 96, 8)
        self.icon_scale.set_value(settings.get("icon_size", 48))
        self.icon_scale.set_hexpand(True)
        self.icon_scale.set_draw_value(True)
        icon_box.append(self.icon_scale)
        self.append(icon_box)

    def _add_section(self, text: str):
        lbl = Gtk.Label()
        lbl.set_markup(f'<b>{text}</b>')
        lbl.set_halign(Gtk.Align.START)
        self.append(lbl)

    def _browse_wallpaper(self, *_):
        dialog = Gtk.FileDialog()
        dialog.open(self.get_ancestor(Gtk.Window), None, self._on_wall_chosen)

    def _on_wall_chosen(self, dialog, result):
        try:
            f = dialog.open_finish(result)
            if f:
                self.wall_entry.set_text(f.get_path())
        except GLib.Error:
            pass

    def collect(self) -> dict:
        return {
            "wallpaper": self.wall_entry.get_text(),
            "font":      self.font_btn.get_font(),
            "icon_size": int(self.icon_scale.get_value()),
        }


# ── Вкладка: Дисплей ─────────────────────────────────────────────
class DisplayTab(Gtk.Box):
    def __init__(self, settings: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(12); self.set_margin_bottom(12)
        self.set_margin_start(16); self.set_margin_end(16)

        lbl = Gtk.Label()
        lbl.set_markup('<b>🖥 Дисплей</b>')
        lbl.set_halign(Gtk.Align.START)
        self.append(lbl)

        # Разрешение
        res_box = Gtk.Box(spacing=8)
        res_box.append(Gtk.Label(label="Разрешение:"))
        self.res_combo = Gtk.ComboBoxText()
        resolutions = ["1920×1080", "1366×768", "1280×720", "1024×768", "800×600"]
        for r in resolutions:
            self.res_combo.append_text(r)
        self.res_combo.set_active(0)
        res_box.append(self.res_combo)
        self.append(res_box)

        # Частота
        freq_box = Gtk.Box(spacing=8)
        freq_box.append(Gtk.Label(label="Частота обновления:"))
        self.freq_combo = Gtk.ComboBoxText()
        for f in ["60 Гц", "75 Гц", "120 Гц", "144 Гц", "240 Гц"]:
            self.freq_combo.append_text(f)
        self.freq_combo.set_active(0)
        freq_box.append(self.freq_combo)
        self.append(freq_box)

        # Яркость
        bright_box = Gtk.Box(spacing=8)
        bright_box.append(Gtk.Label(label="Яркость:"))
        self.bright_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 100, 5)
        self.bright_scale.set_value(settings.get("brightness", 80))
        self.bright_scale.set_hexpand(True)
        self.bright_scale.set_draw_value(True)
        self.bright_scale.connect("value-changed", self._apply_brightness)
        bright_box.append(self.bright_scale)
        self.append(bright_box)

        # DPI
        dpi_box = Gtk.Box(spacing=8)
        dpi_box.append(Gtk.Label(label="DPI:"))
        self.dpi_spin = Gtk.SpinButton.new_with_range(72, 300, 4)
        self.dpi_spin.set_value(settings.get("dpi", 96))
        dpi_box.append(self.dpi_spin)
        self.append(dpi_box)

        apply_btn = Gtk.Button(label="Применить")
        apply_btn.connect("clicked", self._apply_display)
        self.append(apply_btn)

    def _apply_brightness(self, scale):
        val = scale.get_value()
        try:
            subprocess.run(
                ["xrandr", "--output", "eDP-1",
                 "--brightness", f"{val/100:.2f}"],
                check=False
            )
        except FileNotFoundError:
            pass

    def _apply_display(self, *_):
        res = self.res_combo.get_active_text() or ""
        res = res.replace("×", "x")
        freq = self.freq_combo.get_active_text() or ""
        rate = freq.replace(" Гц", "")
        dpi  = int(self.dpi_spin.get_value())
        try:
            subprocess.run(
                ["xrandr", "--dpi", str(dpi)], check=False
            )
        except FileNotFoundError:
            pass

    def collect(self) -> dict:
        return {
            "brightness": self.bright_scale.get_value(),
            "dpi": int(self.dpi_spin.get_value()),
        }


# ── Вкладка: Звук ────────────────────────────────────────────────
class SoundTab(Gtk.Box):
    def __init__(self, settings: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(12); self.set_margin_bottom(12)
        self.set_margin_start(16); self.set_margin_end(16)

        lbl = Gtk.Label(); lbl.set_markup('<b>🔊 Звук</b>')
        lbl.set_halign(Gtk.Align.START); self.append(lbl)

        vol_box = Gtk.Box(spacing=8)
        vol_box.append(Gtk.Label(label="Основная громкость:"))
        self.vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.vol_scale.set_value(settings.get("volume", 80))
        self.vol_scale.set_hexpand(True)
        self.vol_scale.set_draw_value(True)
        self.vol_scale.connect("value-changed", self._apply_volume)
        vol_box.append(self.vol_scale)
        self.append(vol_box)

        mute_box = Gtk.Box(spacing=8)
        self.mute_switch = Gtk.Switch()
        self.mute_switch.set_active(settings.get("mute", False))
        mute_box.append(Gtk.Label(label="Без звука:"))
        mute_box.append(self.mute_switch)
        self.append(mute_box)

        lbl2 = Gtk.Label(); lbl2.set_markup('<b>Устройство вывода:</b>')
        lbl2.set_halign(Gtk.Align.START); self.append(lbl2)
        self.dev_combo = Gtk.ComboBoxText()
        self._load_audio_devices()
        self.append(self.dev_combo)

        # Звук входа
        login_box = Gtk.Box(spacing=8)
        self.login_sound = Gtk.Switch()
        self.login_sound.set_active(settings.get("login_sound", True))
        login_box.append(Gtk.Label(label="Звук при входе:"))
        login_box.append(self.login_sound)
        self.append(login_box)

    def _load_audio_devices(self):
        self.dev_combo.append_text("(по умолчанию)")
        try:
            out = subprocess.check_output(
                ["pactl", "list", "short", "sinks"],
                text=True, stderr=subprocess.DEVNULL
            )
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    self.dev_combo.append_text(parts[1])
        except Exception:
            self.dev_combo.append_text("Встроенный аудио")
        self.dev_combo.set_active(0)

    def _apply_volume(self, scale):
        val = int(scale.get_value())
        try:
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{val}%"],
                check=False
            )
        except FileNotFoundError:
            pass

    def collect(self) -> dict:
        return {
            "volume": self.vol_scale.get_value(),
            "mute": self.mute_switch.get_active(),
            "login_sound": self.login_sound.get_active(),
        }


# ── Вкладка: Автозапуск ──────────────────────────────────────────
class AutostartTab(Gtk.Box):
    def __init__(self, settings: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_margin_top(12); self.set_margin_bottom(12)
        self.set_margin_start(16); self.set_margin_end(16)

        lbl = Gtk.Label(); lbl.set_markup('<b>▶ Автозапуск приложений</b>')
        lbl.set_halign(Gtk.Align.START); self.append(lbl)

        info = Gtk.Label(label="Программы, запускаемые при входе в систему:")
        info.set_halign(Gtk.Align.START)
        self.append(info)

        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(-1, 200)

        self.store = Gtk.ListStore(bool, str, str)
        view = Gtk.TreeView(model=self.store)

        toggle_r = Gtk.CellRendererToggle()
        toggle_r.connect("toggled", self._on_toggle)
        col0 = Gtk.TreeViewColumn("Вкл", toggle_r, active=0)
        view.append_column(col0)

        for i, name in [(1, "Приложение"), (2, "Команда")]:
            col = Gtk.TreeViewColumn(name, Gtk.CellRendererText(), text=i)
            col.set_resizable(True)
            view.append_column(col)

        scroll.set_child(view)
        self.append(scroll)

        # Загружаем из ~/.config/autostart
        self._load_autostart()

        # Кнопки
        btn_box = Gtk.Box(spacing=4)
        add_btn = Gtk.Button(label="+ Добавить")
        add_btn.connect("clicked", self._add)
        rem_btn = Gtk.Button(label="— Удалить")
        rem_btn.connect("clicked", lambda *_: None)
        btn_box.append(add_btn)
        btn_box.append(rem_btn)
        self.append(btn_box)
        self._view = view

    def _load_autostart(self):
        xdg_auto = Path.home() / ".config" / "autostart"
        if xdg_auto.exists():
            for f in xdg_auto.glob("*.desktop"):
                try:
                    text = f.read_text()
                    name = next((l.split("=",1)[1] for l in text.splitlines()
                                 if l.startswith("Name=")), f.stem)
                    cmd  = next((l.split("=",1)[1] for l in text.splitlines()
                                 if l.startswith("Exec=")), "")
                    hidden = "Hidden=true" in text
                    self.store.append([not hidden, name, cmd])
                except Exception:
                    pass
        # Системные сервисы CryOS
        for name, cmd in [
            ("CryOS Notify",   "python3 cryos-notify"),
            ("CryOS Taskbar",  "cryos-desktop"),
        ]:
            self.store.append([True, name, cmd])

    def _on_toggle(self, renderer, path):
        it = self.store.get_iter(path)
        self.store.set_value(it, 0, not self.store.get_value(it, 0))

    def _add(self, *_):
        dlg = Gtk.Dialog(title="Добавить в автозапуск",
                         transient_for=self.get_ancestor(Gtk.Window), modal=True)
        dlg.add_button("Отмена", Gtk.ResponseType.CANCEL)
        dlg.add_button("Добавить", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12); box.set_margin_bottom(12)
        box.set_margin_start(16); box.set_margin_end(16)
        name_e = Gtk.Entry(placeholder_text="Название")
        cmd_e  = Gtk.Entry(placeholder_text="Команда (например: cryos-term)")
        box.append(name_e); box.append(cmd_e)
        if dlg.run() == Gtk.ResponseType.OK:
            n = name_e.get_text().strip()
            c = cmd_e.get_text().strip()
            if n and c:
                self.store.append([True, n, c])
        dlg.destroy()

    def collect(self) -> dict:
        return {}


# ── Вкладка: О системе ───────────────────────────────────────────
class AboutTab(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_margin_top(12); self.set_margin_bottom(12)
        self.set_margin_start(16); self.set_margin_end(16)

        # Маскот
        mascot = Gtk.Label()
        mascot.set_markup('<span font="Monospace 14" foreground="#000080">'
                          '  ╭──────────╮\n'
                          '  │ (◕‿◕✿)  │\n'
                          '  │  CryOS   │\n'
                          '  ╰──────────╯</span>')
        self.append(mascot)

        version = "0.1.0"
        if VERSION_FILE.exists():
            version = VERSION_FILE.read_text().strip()

        grid = Gtk.Grid()
        grid.set_column_spacing(16)
        grid.set_row_spacing(6)

        info_rows = [
            ("Версия CryOS:",     version),
            ("Ядро Linux:",       platform.release()),
            ("Архитектура:",      platform.machine()),
            ("Имя хоста:",        platform.node()),
            ("Пользователь:",     os.environ.get("USER", "—")),
            ("Python:",           platform.python_version()),
        ]

        # RAM через psutil
        try:
            import psutil
            mem = psutil.virtual_memory()
            ram_gb = mem.total / (1024**3)
            info_rows.append(("ОЗУ:", f"{ram_gb:.1f} ГБ"))
            cpu_count = psutil.cpu_count()
            info_rows.append(("ЦП (ядер):", str(cpu_count)))
        except ImportError:
            pass

        for i, (key, val) in enumerate(info_rows):
            k = Gtk.Label(); k.set_markup(f'<b>{key}</b>')
            k.set_halign(Gtk.Align.START)
            v = Gtk.Label(label=val)
            v.set_halign(Gtk.Align.START)
            grid.attach(k, 0, i, 1, 1)
            grid.attach(v, 1, i, 1, 1)

        self.append(grid)

        copy_lbl = Gtk.Label()
        copy_lbl.set_markup('<span foreground="#666" size="small">'
                            '© CryOS Project. Распространяется под лицензией MIT.</span>')
        copy_lbl.set_margin_top(12)
        self.append(copy_lbl)

    def collect(self) -> dict:
        return {}


# ── Главное окно ─────────────────────────────────────────────────
class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CryOS — Настройки")
        self.set_default_size(700, 520)
        self.add_css_class("cry-window")

        self.settings = load_settings()

        hpaned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        hpaned.set_position(170)

        # Левая панель — список разделов
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Gtk.Label()
        header.set_markup('<span font="11" weight="bold">  ⚙ Настройки</span>')
        header.add_css_class("cry-oobe-header")
        header.set_size_request(-1, 36)
        sidebar.append(header)

        # Правая область — стек
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP_DOWN)

        self._tabs = [
            ("appearance", "🎨 Внешний вид", AppearanceTab(self.settings)),
            ("display",    "🖥 Дисплей",     DisplayTab(self.settings)),
            ("sound",      "🔊 Звук",         SoundTab(self.settings)),
            ("autostart",  "▶ Автозапуск",   AutostartTab(self.settings)),
            ("about",      "ℹ О системе",    AboutTab()),
        ]

        for name, label, widget in self._tabs:
            btn = Gtk.Button(label=label)
            btn.set_has_frame(False)
            btn.add_css_class("flat")
            btn.set_halign(Gtk.Align.FILL)
            btn.connect("clicked", self._switch, name)
            sidebar.append(btn)
            self.stack.add_named(widget, name)

        scroll_side = Gtk.ScrolledWindow()
        scroll_side.set_child(sidebar)
        scroll_side.set_size_request(170, -1)

        hpaned.set_start_child(scroll_side)
        hpaned.set_resize_start_child(False)

        # Правая часть: стек + кнопки OK/Apply
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        right.append(self.stack)

        btn_box = Gtk.Box(spacing=6)
        btn_box.set_halign(Gtk.Align.END)
        btn_box.set_margin_top(8)
        btn_box.set_margin_bottom(8)
        btn_box.set_margin_end(12)

        cancel_btn = Gtk.Button(label="Отмена")
        cancel_btn.connect("clicked", lambda *_: self.close())
        btn_box.append(cancel_btn)

        apply_btn = Gtk.Button(label="Применить")
        apply_btn.connect("clicked", self._apply)
        btn_box.append(apply_btn)

        ok_btn = Gtk.Button(label="ОК")
        ok_btn.add_css_class("suggested-action")
        ok_btn.connect("clicked", lambda *_: (self._apply(), self.close()))
        btn_box.append(ok_btn)

        right.append(btn_box)
        hpaned.set_end_child(right)
        self.set_child(hpaned)

        # Показываем первый раздел
        self.stack.set_visible_child_name("appearance")

    def _switch(self, btn, name: str):
        self.stack.set_visible_child_name(name)

    def _apply(self, *_):
        merged = {}
        for name, label, widget in self._tabs:
            if hasattr(widget, "collect"):
                merged.update(widget.collect())
        self.settings.update(merged)
        save_settings(self.settings)


class SettingsApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="org.cryos.Settings",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )

    def do_activate(self):
        if THEME_CSS.exists():
            p = Gtk.CssProvider()
            p.load_from_path(str(THEME_CSS))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), p,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        win = SettingsWindow(self)
        win.present()


def main():
    app = SettingsApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
