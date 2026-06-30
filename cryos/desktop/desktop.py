#!/usr/bin/env python3
"""
CryOS Desktop  —  desktop/desktop.py
======================================
Рабочий стол: панель задач, меню «Cry», часы, иконки, обои.
Обои: читает ~/.config/cryos/wallpaper.conf → assets/wallpapers/wXX.png.
ПКМ на рабочем столе → меню смены обоев.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gtk, Gdk, GLib, Gio
import subprocess, datetime, os, sys, json
from pathlib import Path

# ── Пути ─────────────────────────────────────────────────────────
CRYOS_ROOT   = Path(__file__).parent.parent
ASSETS       = CRYOS_ROOT / "assets"
WALLPAPER_DIR= ASSETS / "wallpapers"
CONFIG_DIR   = Path.home() / ".config" / "cryos"
CONFIG_FILE  = CONFIG_DIR / "desktop.json"
WALLPAPER_CFG= CONFIG_DIR / "wallpaper.conf"
THEME_CSS    = CRYOS_ROOT / "system" / "theme" / "gtk.css"
APPS_DEV = {
    "cryos-files":      [sys.executable, str(CRYOS_ROOT / "apps/file-manager/main.py")],
    "cryos-git":        [sys.executable, str(CRYOS_ROOT / "apps/git-manager/main.py")],
    "cryos-disk":       [sys.executable, str(CRYOS_ROOT / "apps/disk-utility/main.py")],
    "cryos-appinstall": [sys.executable, str(CRYOS_ROOT / "apps/app-installer/main.py")],
    "cryos-oobe":       [sys.executable, str(CRYOS_ROOT / "oobe/oobe.py")],
    "cryos-term":       [sys.executable, str(CRYOS_ROOT / "apps/terminal/main.py")],
    "cryos-edit":       [sys.executable, str(CRYOS_ROOT / "apps/text-editor/main.py")],
    "cryos-view":       [sys.executable, str(CRYOS_ROOT / "apps/image-viewer/main.py")],
    "cryos-sysmon":     [sys.executable, str(CRYOS_ROOT / "apps/system-monitor/main.py")],
    "cryos-settings":   [sys.executable, str(CRYOS_ROOT / "apps/settings/main.py")],
    "cryos-lock":       [sys.executable, str(CRYOS_ROOT / "apps/lock/main.py")],
    "cryos-notify":     [sys.executable, str(CRYOS_ROOT / "apps/notify/main.py")],
    "cryos-audio":      [sys.executable, str(CRYOS_ROOT / "apps/audio-mixer/main.py")],
    "cryos-net":        [sys.executable, str(CRYOS_ROOT / "apps/net-manager/main.py")],
    "cryos-pkgman":     [sys.executable, str(CRYOS_ROOT / "apps/pkg-manager/main.py")],
}

DESKTOP_ITEMS = [
    {"name": "Файлы",         "icon": "🗂",  "exec": "cryos-files"},
    {"name": "Терминал",      "icon": "💻",  "exec": "cryos-term"},
    {"name": "Редактор",      "icon": "📝",  "exec": "cryos-edit"},
    {"name": "Просмотрщик",   "icon": "🖼",  "exec": "cryos-view"},
    {"name": "Git Manager",   "icon": "🌿",  "exec": "cryos-git"},
    {"name": "Пакеты",        "icon": "📦",  "exec": "cryos-pkgman"},
    {"name": "Система",       "icon": "📊",  "exec": "cryos-sysmon"},
    {"name": "Настройки",     "icon": "⚙",  "exec": "cryos-settings"},
]

# В live-режиме показываем иконку установщика
if Path("/run/live").exists() or Path("/run/live/medium").exists():
    DESKTOP_ITEMS.insert(0, {"name": "Установить\nCryOS", "icon": "💿", "exec": "cryos-install"})

START_MENU_ITEMS = [
    {"name": "📁 Файлы",              "exec": "cryos-files"},
    {"name": "💻 Терминал",           "exec": "cryos-term"},
    {"name": "📝 Редактор",           "exec": "cryos-edit"},
    {"name": "🖼 Просмотрщик",        "exec": "cryos-view"},
    {"name": "🌿 Git Manager",        "exec": "cryos-git"},
    {"name": "💿 Утилита диска",      "exec": "cryos-disk"},
    {"name": "📦 Установка ПО",       "exec": "cryos-pkgman"},
    None,
    {"name": "⚙  Настройки",         "exec": "_settings"},
    {"name": "📊 Система",            "exec": "cryos-sysmon"},
    {"name": "🔊 Звук",               "exec": "cryos-audio"},
    {"name": "🌐 Сеть",               "exec": "cryos-net"},
    {"name": "🖼  Сменить обои",      "exec": "_wallpaper"},
    None,
    {"name": "🔒 Заблокировать",      "exec": "_lock"},
    {"name": "🚪 Завершить сессию",   "exec": "_logout"},
]

WALLPAPERS = ["w01.png", "w02.png", "w03.png"]


# ── Утилиты ──────────────────────────────────────────────────────
def load_css():
    if THEME_CSS.exists():
        p = Gtk.CssProvider()
        p.load_from_path(str(THEME_CSS))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), p,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

def run_app(exec_cmd: str):
    if exec_cmd.startswith("_"):
        _handle_special(exec_cmd)
        return
    try:
        subprocess.Popen(exec_cmd.split(), start_new_session=True)
    except FileNotFoundError:
        if exec_cmd in APPS_DEV:
            subprocess.Popen(APPS_DEV[exec_cmd], start_new_session=True)

def _handle_special(cmd: str):
    if cmd == "_logout":
        _do_logout()
    elif cmd == "_wallpaper":
        if _desktop_ref:
            _desktop_ref.open_wallpaper_dialog()
    elif cmd == "_settings":
        run_app("cryos-settings")
    elif cmd == "_lock":
        run_app("cryos-lock")

def _do_logout():
    win = _desktop_ref
    dlg = Gtk.MessageDialog(
        message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.YES_NO,
        text="Завершить сессию CryOS?",
    )
    dlg.set_title("Выход")
    if dlg.run() == Gtk.ResponseType.YES:
        Gtk.main_quit()
    dlg.destroy()

def read_wallpaper_cfg() -> str:
    """Возвращает имя файла обоев из конфига (w01.png по умолчанию)."""
    if WALLPAPER_CFG.exists():
        try:
            data = json.loads(WALLPAPER_CFG.read_text())
            return data.get("wallpaper", "w01.png")
        except Exception:
            pass
    return "w01.png"

def save_wallpaper_cfg(name: str):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    WALLPAPER_CFG.write_text(json.dumps({"wallpaper": name}, indent=2))

def apply_wallpaper_external(path: Path):
    """Устанавливает обои через feh или nitrogen, если доступны."""
    if not path.exists():
        return
    for cmd in [["feh", "--bg-scale", str(path)],
                ["nitrogen", "--set-scaled", str(path)]]:
        try:
            subprocess.Popen(cmd)
            return
        except FileNotFoundError:
            continue

_desktop_ref = None  # глобальная ссылка на Desktop


# ── Часы ─────────────────────────────────────────────────────────
class ClockWidget(Gtk.Label):
    def __init__(self):
        super().__init__()
        self.add_css_class("cry-taskbar-clock")
        self._update()
        GLib.timeout_add_seconds(1, self._update)

    def _update(self):
        self.set_text(datetime.datetime.now().strftime("%H:%M  %d.%m.%Y"))
        return True


# ── Меню «Cry» (Пуск) ────────────────────────────────────────────
class StartMenu(Gtk.Popover):
    def __init__(self, parent_btn):
        super().__init__()
        self.set_parent(parent_btn)
        self.set_position(Gtk.PositionType.TOP)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Шапка с Конатой (текстовый вариант)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("cry-oobe-header")
        header.set_margin_bottom(4)
        header.set_size_request(-1, 48)
        mascot = Gtk.Label()
        mascot.set_markup('<span font="24" foreground="white">◈</span>')
        mascot.set_margin_start(10)
        mascot.set_margin_end(6)
        name = Gtk.Label()
        name.set_markup('<span font="14" weight="bold" foreground="white">CryOS</span>')
        header.append(mascot)
        header.append(name)
        vbox.append(header)

        for item in START_MENU_ITEMS:
            if item is None:
                sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                sep.set_margin_top(2); sep.set_margin_bottom(2)
                vbox.append(sep)
            else:
                btn = Gtk.Button(label=item["name"])
                btn.set_has_frame(False)
                btn.add_css_class("flat")
                btn.set_halign(Gtk.Align.FILL)
                btn.connect("clicked", self._on_item, item["exec"])
                vbox.append(btn)

        self.set_child(vbox)

    def _on_item(self, btn, exec_cmd):
        self.popdown()
        run_app(exec_cmd)


# ── Панель задач ─────────────────────────────────────────────────
class Taskbar(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("CryOS Taskbar")
        self.set_decorated(False)
        self.set_resizable(False)
        self.add_css_class("cry-panel")

        display = Gdk.Display.get_default()
        monitors = display.get_monitors()
        w = 1280
        if monitors.get_n_items() > 0:
            g = monitors.get_item(0).get_geometry()
            w = g.width
        self.set_default_size(w, 32)
        self.set_size_request(w, 32)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        hbox.set_margin_start(4); hbox.set_margin_end(4)

        # Кнопка Cry
        self.start_btn = Gtk.Button()
        self.start_btn.add_css_class("cry-start-button")
        sb = Gtk.Box(spacing=4)
        sb.append(Gtk.Label(label="◈"))
        lbl = Gtk.Label(); lbl.set_markup("<b>Cry</b>")
        sb.append(lbl)
        self.start_btn.set_child(sb)
        self.start_btn.connect("clicked", self._on_start)
        self.start_menu = StartMenu(self.start_btn)
        hbox.append(self.start_btn)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.set_margin_start(4); sep.set_margin_end(4)
        hbox.append(sep)

        # Область задач
        self.tasks_box = Gtk.Box(spacing=2)
        self.tasks_box.set_hexpand(True)
        hbox.append(self.tasks_box)

        # Трей + часы
        tray = Gtk.Box(spacing=4)
        tray.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Wi-Fi индикатор
        self.wifi_lbl = Gtk.Label(label="📶")
        self.wifi_lbl.set_tooltip_text("Сеть")
        tray.append(self.wifi_lbl)

        # Громкость
        self.vol_btn = Gtk.Button(label="🔊")
        self.vol_btn.set_has_frame(False)
        self.vol_btn.add_css_class("flat")
        self.vol_btn.set_tooltip_text("Звук")
        self.vol_btn.connect("clicked", lambda *_: run_app("cryos-audio"))
        tray.append(self.vol_btn)

        # Батарея
        self.bat_lbl = Gtk.Label(label="🔋")
        self.bat_lbl.set_tooltip_text("Батарея")
        tray.append(self.bat_lbl)

        tray.append(ClockWidget())
        hbox.append(tray)

        self.set_child(hbox)

        # Обновление трея каждые 30с
        GLib.timeout_add_seconds(30, self._update_tray)
        self._update_tray()

    def _on_start(self, *_):
        if self.start_menu.is_visible():
            self.start_menu.popdown()
        else:
            self.start_menu.popup()

    def _update_tray(self):
        """Обновляем иконки трея."""
        # Батарея
        try:
            bat_path = Path("/sys/class/power_supply/BAT0")
            if bat_path.exists():
                cap = int((bat_path / "capacity").read_text().strip())
                charging = "Charging" in (bat_path / "status").read_text()
                if   cap > 80: icon = "🔋"
                elif cap > 40: icon = "🪫"
                else:          icon = "🔴"
                plug = "⚡" if charging else ""
                self.bat_lbl.set_text(f"{plug}{icon}{cap}%")
            else:
                self.bat_lbl.set_text("")
        except Exception:
            self.bat_lbl.set_text("")

        # Wi-Fi (упрощённо)
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "ACTIVE,SIGNAL", "device", "wifi"],
                capture_output=True, text=True, timeout=2
            )
            connected = "yes" in result.stdout
            self.wifi_lbl.set_text("📶" if connected else "📡")
        except Exception:
            self.wifi_lbl.set_text("📶")

        return True


# ── Диалог смены обоев ───────────────────────────────────────────
class WallpaperDialog(Gtk.Dialog):
    def __init__(self, parent, current: str):
        super().__init__(title="Смена обоев", transient_for=parent, modal=True)
        self.add_button("Отмена", Gtk.ResponseType.CANCEL)
        self.add_button("Применить", Gtk.ResponseType.OK)
        self.set_default_size(580, 260)
        self.chosen = current

        box = self.get_content_area()
        box.set_spacing(12)
        box.set_margin_top(16); box.set_margin_bottom(16)
        box.set_margin_start(20); box.set_margin_end(20)

        lbl = Gtk.Label()
        lbl.set_markup('<b>Выберите обои рабочего стола:</b>')
        lbl.set_halign(Gtk.Align.START)
        box.append(lbl)

        grid = Gtk.Box(spacing=16)
        grid.set_halign(Gtk.Align.CENTER)
        self._btns = []

        for name in WALLPAPERS:
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            vb.set_halign(Gtk.Align.CENTER)

            btn = Gtk.Button()
            btn.set_size_request(160, 100)

            p = WALLPAPER_DIR / name
            if p.exists():
                pic = Gtk.Picture()
                pic.set_filename(str(p))
                pic.set_content_fit(Gtk.ContentFit.COVER)
                pic.set_size_request(156, 96)
                btn.set_child(pic)
            else:
                ph = Gtk.Label()
                ph.set_markup(f'<span font="28">🖼</span>\n<span font="9" foreground="#888">{name}</span>')
                ph.set_justify(Gtk.Justification.CENTER)
                btn.set_child(ph)

            if name == current:
                btn.add_css_class("suggested-action")

            btn.connect("clicked", self._pick, name)
            self._btns.append((name, btn))

            namelbl = Gtk.Label(label=name)
            vb.append(btn)
            vb.append(namelbl)
            grid.append(vb)

        box.append(grid)

    def _pick(self, btn, name: str):
        self.chosen = name
        for n, b in self._btns:
            ctx = b.get_style_context()
            if n == name:
                ctx.add_class("suggested-action")
            else:
                ctx.remove_class("suggested-action")


# ── Иконка рабочего стола ────────────────────────────────────────
class DesktopIcon(Gtk.Button):
    def __init__(self, item: dict):
        super().__init__()
        self.item = item
        self.set_has_frame(False)
        self.add_css_class("flat")
        self.set_size_request(76, 80)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox.set_halign(Gtk.Align.CENTER)

        ico = Gtk.Label()
        ico.set_markup(f'<span font="30">{item["icon"]}</span>')
        vbox.append(ico)

        lbl = Gtk.Label(label=item["name"])
        lbl.set_wrap(True)
        lbl.set_max_width_chars(10)
        lbl.set_justify(Gtk.Justification.CENTER)
        lbl.set_markup(
            f'<span font="9" foreground="white" '
            f'background="#000080"> {item["name"]} </span>'
        )
        vbox.append(lbl)
        self.set_child(vbox)
        self.connect("clicked", lambda b: run_app(item["exec"]))


# ── Рабочий стол ─────────────────────────────────────────────────
class Desktop(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CryOS Desktop")
        self.set_decorated(False)
        self.set_resizable(False)
        self.add_css_class("cry-desktop")

        global _desktop_ref
        _desktop_ref = self

        display = Gdk.Display.get_default()
        monitors = display.get_monitors()
        w, h = 1280, 720
        if monitors.get_n_items() > 0:
            g = monitors.get_item(0).get_geometry()
            w, h = g.width, g.height
        self.set_default_size(w, h)
        self._screen_w = w
        self._screen_h = h

        # Слой обоев + контент
        overlay = Gtk.Overlay()

        # Обои
        self._wallpaper_pic = Gtk.Picture()
        self._wallpaper_pic.set_content_fit(Gtk.ContentFit.COVER)
        self._wallpaper_pic.set_size_request(w, h)
        overlay.set_child(self._wallpaper_pic)

        # Иконки поверх обоев
        flow = Gtk.FlowBox()
        flow.set_valign(Gtk.Align.START)
        flow.set_halign(Gtk.Align.START)
        flow.set_max_children_per_line(1)
        flow.set_column_spacing(8)
        flow.set_row_spacing(8)
        flow.set_margin_top(20)
        flow.set_margin_start(20)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        for item in DESKTOP_ITEMS:
            flow.append(DesktopIcon(item))
        overlay.add_overlay(flow)

        self.set_child(overlay)

        # ПКМ на рабочем столе
        gesture = Gtk.GestureClick()
        gesture.set_button(3)  # правая кнопка
        gesture.connect("pressed", self._on_right_click)
        self.add_controller(gesture)

        # Загружаем обои
        self._load_wallpaper()

    def _load_wallpaper(self):
        name = read_wallpaper_cfg()
        wall = WALLPAPER_DIR / name
        if wall.exists():
            self._wallpaper_pic.set_filename(str(wall))
        else:
            # Fallback — бирюзовый фон как в Win95
            provider = Gtk.CssProvider()
            provider.load_from_data(b".cry-desktop { background: #008080; }")
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
            )

    def open_wallpaper_dialog(self):
        current = read_wallpaper_cfg()
        dlg = WallpaperDialog(self, current)
        if dlg.run() == Gtk.ResponseType.OK:
            chosen = dlg.chosen
            save_wallpaper_cfg(chosen)
            wall = WALLPAPER_DIR / chosen
            self._wallpaper_pic.set_filename(str(wall)) if wall.exists() else None
            apply_wallpaper_external(wall)
        dlg.destroy()

    def _on_right_click(self, gesture, n_press, x, y):
        menu = Gtk.Menu()
        for label, cb in [
            ("🖼 Сменить обои",      lambda *_: self.open_wallpaper_dialog()),
            ("↺ Обновить рабочий стол", lambda *_: None),
            (None, None),
            ("🚪 Завершить сессию",  lambda *_: _do_logout()),
        ]:
            if label is None:
                menu.append(Gtk.SeparatorMenuItem())
            else:
                item = Gtk.MenuItem(label=label)
                item.connect("activate", cb)
                menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(None)


# ── Приложение ───────────────────────────────────────────────────
class CryDesktopApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="org.cryos.Desktop",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )

    def do_activate(self):
        load_css()
        self.desktop  = Desktop(self)
        self.desktop.present()
        self.taskbar  = Taskbar(self)
        self.taskbar.present()

        # Горячие клавиши (Super/Win)
        self._setup_hotkeys()

        # Автозапуск демона уведомлений
        GLib.timeout_add(800, self._launch_notify)

        # Проверяем OOBE
        flag = CONFIG_DIR / ".oobe_done"
        if not flag.exists():
            GLib.timeout_add(600, self._launch_oobe)

    def _setup_hotkeys(self):
        """Глобальные горячие клавиши через xbindkeys или нативно."""
        # Нативные через Gtk ShortcutController на рабочем столе
        ctrl = Gtk.ShortcutController()
        ctrl.set_scope(Gtk.ShortcutScope.GLOBAL)
        self.desktop.add_controller(ctrl)

        M = Gdk.ModifierType
        hotkeys = [
            (Gdk.KEY_e,      M.SUPER_MASK, "cryos-files"),
            (Gdk.KEY_t,      M.SUPER_MASK, "cryos-term"),
            (Gdk.KEY_r,      M.SUPER_MASK, "_run_dialog"),
            (Gdk.KEY_l,      M.SUPER_MASK, "_lock"),
            (Gdk.KEY_F2,     M.SUPER_MASK, "cryos-sysmon"),
        ]
        for key, mods, cmd in hotkeys:
            trigger = Gtk.KeyvalTrigger(keyval=key, modifiers=mods)
            action  = Gtk.CallbackAction.new(
                lambda *a, c=cmd: (run_app(c), True)[1]
            )
            ctrl.add_shortcut(Gtk.Shortcut(trigger=trigger, action=action))

    def _launch_notify(self):
        notify_py = CRYOS_ROOT / "apps" / "notify" / "main.py"
        if notify_py.exists():
            subprocess.Popen(
                [sys.executable, str(notify_py)],
                start_new_session=True
            )
        return False

    def _launch_oobe(self):
        oobe = CRYOS_ROOT / "oobe" / "oobe.py"
        if oobe.exists():
            subprocess.Popen([sys.executable, str(oobe)], start_new_session=True)
        return False


def main():
    app = CryDesktopApp()
    sys.exit(app.run(sys.argv))

if __name__ == "__main__":
    main()
