#!/usr/bin/env python3
"""
CryOS Terminal  —  apps/terminal/main.py
=========================================
Лёгкий встроенный терминал на базе VTE (PTY).
Функции: вкладки, копирование/вставка, история команд,
         белый фон / синий текст, моноширинный шрифт.
Зависимости: python3-gi, gir1.2-vte-2.91
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Gdk, GLib, Gio, Vte
import os, sys
from pathlib import Path

CRYOS_ROOT = Path(__file__).parent.parent.parent
THEME_CSS  = CRYOS_ROOT / "system" / "theme" / "gtk.css"

SHELL = os.environ.get("SHELL", "/bin/bash")

# Цвета терминала: белый фон, синий текст (стиль CryOS)
FG = Gdk.RGBA(); FG.parse("rgba(0,0,128,1)")        # #000080 — тёмно-синий
BG = Gdk.RGBA(); BG.parse("rgba(255,255,255,1)")     # белый фон

PALETTE = [
    "#000000","#800000","#008000","#808000",
    "#000080","#800080","#008080","#c0c0c0",
    "#808080","#ff0000","#00ff00","#ffff00",
    "#0000ff","#ff00ff","#00ffff","#ffffff",
]

def make_rgba(hex_color: str) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.parse(hex_color)
    return c


class TerminalTab(Gtk.Box):
    """Одна вкладка с VTE-терминалом."""

    def __init__(self, cwd: str | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.vte = Vte.Terminal()
        self._setup_terminal()
        self._spawn(cwd)

        scroll = Gtk.ScrolledWindow()
        scroll.set_child(self.vte)
        scroll.set_vexpand(True)
        self.append(scroll)

    def _setup_terminal(self):
        vte = self.vte
        # Цвета
        palette = [make_rgba(c) for c in PALETTE]
        vte.set_colors(FG, BG, palette)
        # Шрифт
        from gi.repository import Pango
        vte.set_font(Pango.FontDescription.from_string("Monospace 11"))
        # Поведение
        vte.set_scrollback_lines(10000)
        vte.set_cursor_blink_mode(Vte.CursorBlinkMode.ON)
        vte.set_word_char_exceptions("-A-Za-z0-9,./?%&#:_=+@~")
        vte.set_mouse_autohide(True)
        # Копирование по Ctrl+Shift+C / вставка Ctrl+Shift+V
        vte.connect("key-press-event", self._on_key)

    def _spawn(self, cwd: str | None = None):
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env_list = [f"{k}={v}" for k, v in env.items()]
        self.vte.spawn_async(
            Vte.PtyFlags.DEFAULT,
            cwd or str(Path.home()),
            [SHELL],
            env_list,
            GLib.SpawnFlags.DEFAULT,
            None, None, -1, None, None
        )

    def _on_key(self, widget, event):
        # Ctrl+Shift+C → копировать
        if (event.state & Gdk.ModifierType.CONTROL_MASK and
                event.state & Gdk.ModifierType.SHIFT_MASK):
            if event.keyval == Gdk.KEY_c:
                self.vte.copy_clipboard_format(Vte.Format.TEXT)
                return True
            if event.keyval == Gdk.KEY_v:
                self.vte.paste_clipboard()
                return True
        return False

    @property
    def title(self) -> str:
        t = self.vte.get_window_title()
        return t if t else "Терминал"


class TerminalWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CryOS Терминал")
        self.set_default_size(900, 580)
        self.add_css_class("cry-window")
        self._tab_counter = 0

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Меню-бар
        menubar = self._build_menubar()
        vbox.append(menubar)

        # Notebook (вкладки)
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_tabs(True)
        self.notebook.set_tab_pos(Gtk.PositionType.TOP)
        self.notebook.set_vexpand(True)
        vbox.append(self.notebook)

        self.set_child(vbox)

        # Горячие клавиши
        self._setup_shortcuts()

        # Первая вкладка
        self.new_tab()

    def _build_menubar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        bar.add_css_class("cry-menubar")
        bar.set_margin_start(4)
        bar.set_margin_top(2)
        bar.set_margin_bottom(2)

        def add_btn(label, cb):
            b = Gtk.Button(label=label)
            b.set_has_frame(False)
            b.add_css_class("flat")
            b.connect("clicked", cb)
            bar.append(b)

        add_btn("Новая вкладка [Ctrl+T]", lambda *_: self.new_tab())
        add_btn("Закрыть вкладку [Ctrl+W]", lambda *_: self.close_current_tab())
        add_btn("Копировать [Ctrl+Shift+C]", lambda *_: self._copy())
        add_btn("Вставить [Ctrl+Shift+V]", lambda *_: self._paste())
        return bar

    def _setup_shortcuts(self):
        ctrl = Gtk.ShortcutController()
        ctrl.set_scope(Gtk.ShortcutScope.MANAGED)
        self.add_controller(ctrl)

        def shortcut(key, mods, cb):
            trigger = Gtk.KeyvalTrigger(keyval=key, modifiers=mods)
            action  = Gtk.CallbackAction.new(lambda *a: cb() or True)
            ctrl.add_shortcut(Gtk.Shortcut(trigger=trigger, action=action))

        M = Gdk.ModifierType
        shortcut(Gdk.KEY_t, M.CONTROL_MASK, self.new_tab)
        shortcut(Gdk.KEY_w, M.CONTROL_MASK, self.close_current_tab)
        shortcut(Gdk.KEY_Page_Up,   M.CONTROL_MASK, lambda: self.notebook.prev_page())
        shortcut(Gdk.KEY_Page_Down, M.CONTROL_MASK, lambda: self.notebook.next_page())

    def new_tab(self, cwd: str | None = None):
        self._tab_counter += 1
        tab = TerminalTab(cwd)

        # Шапка вкладки с кнопкой закрытия
        label_box = Gtk.Box(spacing=4)
        lbl = Gtk.Label(label=f"Терминал {self._tab_counter}")
        close_btn = Gtk.Button(label="✕")
        close_btn.set_has_frame(False)
        close_btn.add_css_class("flat")
        close_btn.set_size_request(20, 20)
        label_box.append(lbl)
        label_box.append(close_btn)
        label_box.show()

        idx = self.notebook.append_page(tab, label_box)
        self.notebook.set_current_page(idx)

        # Обновляем заголовок вкладки при изменении title в VTE
        tab.vte.connect("window-title-changed", lambda vte: lbl.set_text(tab.title[:20]))

        # Закрытие вкладки
        close_btn.connect("clicked", lambda *_: self._close_tab(tab))

        tab.show()

    def _close_tab(self, tab: TerminalTab):
        idx = self.notebook.page_num(tab)
        if idx >= 0:
            self.notebook.remove_page(idx)
        if self.notebook.get_n_pages() == 0:
            self.close()

    def close_current_tab(self):
        idx = self.notebook.get_current_page()
        if idx >= 0:
            page = self.notebook.get_nth_page(idx)
            self._close_tab(page)

    def _current_tab(self) -> TerminalTab | None:
        idx = self.notebook.get_current_page()
        if idx < 0:
            return None
        return self.notebook.get_nth_page(idx)

    def _copy(self):
        tab = self._current_tab()
        if tab:
            tab.vte.copy_clipboard_format(Vte.Format.TEXT)

    def _paste(self):
        tab = self._current_tab()
        if tab:
            tab.vte.paste_clipboard()


class TerminalApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="org.cryos.Terminal",
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
        win = TerminalWindow(self)
        win.present()


def main():
    app = TerminalApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
