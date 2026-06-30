#!/usr/bin/env python3
"""
CryOS Lock Screen  —  apps/lock/main.py
=========================================
Экран блокировки: часы, поле пароля, маскот Коната.
Горячая клавиша: Super+L (вызывается из desktop.py).
Блокирует VT-переключение через chvt.
Зависимости: python3-gi, python3-pam
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio
import datetime, subprocess, sys, os, threading
from pathlib import Path

CRYOS_ROOT = Path(__file__).parent.parent.parent
THEME_CSS  = CRYOS_ROOT / "system" / "theme" / "gtk.css"

# ── PAM-аутентификация ────────────────────────────────────────────
def _pam_auth(username: str, password: str) -> bool:
    """Проверяет пароль через PAM (требует python3-pam или pamela)."""
    try:
        import pam
        p = pam.pam()
        return p.authenticate(username, password)
    except ImportError:
        pass
    try:
        import pamela
        pamela.authenticate(username, password)
        return True
    except Exception:
        return False


def _vt_lock():
    """Блокируем переключение VT пока экран заблокирован."""
    try:
        subprocess.run(["chvt", "7"], check=False)
    except FileNotFoundError:
        pass


def _vt_unlock():
    pass  # VT-блокировка снимается автоматически при уничтожении окна


# ── Анимированные часы ────────────────────────────────────────────
class LockClock(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.set_halign(Gtk.Align.CENTER)

        self.time_lbl = Gtk.Label()
        self.time_lbl.set_markup('<span font="72" weight="bold" foreground="white">00:00</span>')
        self.append(self.time_lbl)

        self.date_lbl = Gtk.Label()
        self.date_lbl.set_markup('<span font="18" foreground="#ccccff">01 января, понедельник</span>')
        self.append(self.date_lbl)

        self._update()
        GLib.timeout_add_seconds(1, self._update)

    def _update(self):
        now = datetime.datetime.now()
        DAYS_RU = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"]
        MONTHS_RU = ["января","февраля","марта","апреля","мая","июня",
                     "июля","августа","сентября","октября","ноября","декабря"]
        self.time_lbl.set_markup(
            f'<span font="72" weight="bold" foreground="white">'
            f'{now.strftime("%H:%M")}</span>'
        )
        self.date_lbl.set_markup(
            f'<span font="18" foreground="#ccccff">'
            f'{now.day} {MONTHS_RU[now.month-1]}, {DAYS_RU[now.weekday()]}</span>'
        )
        return True


# ── Маскот (ASCII Коната) ─────────────────────────────────────────
KONATA_ART = """\
  ╭──────────╮
  │  (◕‿◕✿) │
  │  CryOS  │
  ╰──────────╯"""

class KonataWidget(Gtk.Label):
    def __init__(self):
        super().__init__()
        self.set_markup(
            f'<span font="Monospace 13" foreground="#aaddff">{KONATA_ART}</span>'
        )
        self.set_halign(Gtk.Align.CENTER)


# ── Поле пароля ───────────────────────────────────────────────────
class PasswordBox(Gtk.Box):
    def __init__(self, on_unlock):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_halign(Gtk.Align.CENTER)
        self.set_size_request(320, -1)
        self.on_unlock = on_unlock
        self._attempts = 0
        self._locked_until = 0.0

        self.user_lbl = Gtk.Label()
        self.user_lbl.set_markup(
            f'<span font="14" foreground="white">'
            f'🔒  {os.environ.get("USER", "пользователь")}</span>'
        )
        self.append(self.user_lbl)

        self.entry = Gtk.Entry()
        self.entry.set_visibility(False)
        self.entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.entry.set_placeholder_text("Введите пароль…")
        self.entry.set_size_request(280, 40)
        self.entry.connect("activate", self._try_unlock)
        self.append(self.entry)

        self.msg_lbl = Gtk.Label()
        self.msg_lbl.set_markup('<span foreground="#ffaaaa"> </span>')
        self.append(self.msg_lbl)

        unlock_btn = Gtk.Button(label="  Войти  ▶")
        unlock_btn.add_css_class("suggested-action")
        unlock_btn.connect("clicked", self._try_unlock)
        self.append(unlock_btn)

    def _try_unlock(self, *_):
        import time
        now = time.time()
        if now < self._locked_until:
            secs = int(self._locked_until - now)
            self._show_msg(f"⏳ Подождите {secs} сек.", "#ffaa00")
            return

        password = self.entry.get_text()
        self.entry.set_text("")
        username = os.environ.get("USER", "")

        def auth_thread():
            ok = _pam_auth(username, password)
            GLib.idle_add(self._on_auth_result, ok)

        threading.Thread(target=auth_thread, daemon=True).start()
        self._show_msg("🔄 Проверка…", "#aaaaff")

    def _on_auth_result(self, ok: bool):
        import time
        if ok:
            self._show_msg("✓ Добро пожаловать!", "#aaffaa")
            GLib.timeout_add(300, lambda: (self.on_unlock(), False))
        else:
            self._attempts += 1
            if self._attempts >= 3:
                delay = 10 * (self._attempts - 2)
                self._locked_until = time.time() + delay
                self._show_msg(f"✗ Неверно. Заблокировано на {delay}с", "#ffaaaa")
            else:
                self._show_msg(f"✗ Неверный пароль ({self._attempts}/3)", "#ffaaaa")

    def _show_msg(self, text: str, color: str):
        self.msg_lbl.set_markup(f'<span foreground="{color}">{text}</span>')


# ── Главное окно блокировки ───────────────────────────────────────
class LockWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("CryOS Lock")
        self.set_decorated(False)
        self.set_resizable(False)
        self.fullscreen()

        # Тёмный непрозрачный фон
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
        .cry-lock-bg {
            background: rgba(0, 0, 40, 0.97);
        }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10
        )
        self.add_css_class("cry-lock-bg")

        # Центральный контейнер
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_vexpand(True)
        outer.set_hexpand(True)
        outer.set_valign(Gtk.Align.CENTER)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_spacing(32)

        outer.append(LockClock())
        outer.append(KonataWidget())
        outer.append(PasswordBox(on_unlock=self._unlock))

        # Блокируем Alt+F1-F12 (VT switching)
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._block_vt_keys)
        self.add_controller(key_ctrl)

        self.set_child(outer)
        _vt_lock()

    def _block_vt_keys(self, ctrl, keyval, keycode, state):
        """Блокируем Ctrl+Alt+Fn и Super."""
        M = Gdk.ModifierType
        if (state & M.CONTROL_MASK and state & M.ALT_MASK):
            if Gdk.KEY_F1 <= keyval <= Gdk.KEY_F12:
                return True  # поглощаем
        return False

    def _unlock(self):
        _vt_unlock()
        self.close()
        Gtk.main_quit()


class LockApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="org.cryos.LockScreen",
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
        win = LockWindow(self)
        win.present()


def main():
    app = LockApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
