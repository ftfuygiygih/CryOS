#!/usr/bin/env python3
"""
CryOS Greeter  —  apps/greeter/main.py
=======================================
Замена LightDM greeter: поле логина/пароля,
маскот Коната, часы по центру, список пользователей.
Запускается как LightDM Greeter (greeter-session=cryos-greeter).
Зависимости: python3-gi, gir1.2-lightdm-1
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio
import sys, os, pwd, datetime
from pathlib import Path

CRYOS_ROOT = Path(__file__).parent.parent.parent
THEME_CSS  = CRYOS_ROOT / "system" / "theme" / "gtk.css"

# Пробуем LightDM GObject bindings
try:
    gi.require_version("LightDM", "1")
    from gi.repository import LightDM
    HAVE_LIGHTDM = True
except (ValueError, ImportError):
    HAVE_LIGHTDM = False

KONATA_ART = (
    "  ╭─────────────────╮\n"
    "  │   (◕‿◕✿)        │\n"
    "  │  Добро пожаловать│\n"
    "  │   в  CryOS      │\n"
    "  ╰─────────────────╯"
)

DAYS_RU   = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]
MONTHS_RU = ["января","февраля","марта","апреля","мая","июня",
              "июля","августа","сентября","октября","ноября","декабря"]


def get_system_users() -> list[str]:
    """Возвращает список «человеческих» пользователей системы."""
    users = []
    try:
        for entry in pwd.getpwall():
            uid = entry.pw_uid
            shell = entry.pw_shell
            if uid >= 1000 and "/nologin" not in shell and "/false" not in shell:
                users.append(entry.pw_name)
    except Exception:
        users = [os.environ.get("USER", "user")]
    return sorted(users)


class GreeterClock(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_halign(Gtk.Align.CENTER)

        self.time_lbl = Gtk.Label()
        self.time_lbl.set_markup(
            '<span font="80" weight="bold" foreground="white">00:00</span>'
        )
        self.append(self.time_lbl)

        self.date_lbl = Gtk.Label()
        self.date_lbl.set_markup(
            '<span font="20" foreground="#ccddff">Загрузка…</span>'
        )
        self.append(self.date_lbl)

        self._update()
        GLib.timeout_add_seconds(1, self._update)

    def _update(self):
        now = datetime.datetime.now()
        self.time_lbl.set_markup(
            f'<span font="80" weight="bold" foreground="white">'
            f'{now.strftime("%H:%M")}</span>'
        )
        self.date_lbl.set_markup(
            f'<span font="20" foreground="#ccddff">'
            f'{DAYS_RU[now.weekday()]}, '
            f'{now.day} {MONTHS_RU[now.month-1]} {now.year}</span>'
        )
        return True


class UserButton(Gtk.Box):
    def __init__(self, username: str, select_cb):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.set_halign(Gtk.Align.CENTER)

        avatar = Gtk.Button()
        avatar.set_has_frame(False)

        avatar_lbl = Gtk.Label()
        avatar_lbl.set_markup(
            f'<span font="32" foreground="white">👤</span>'
        )
        avatar.set_child(avatar_lbl)
        avatar.connect("clicked", lambda *_: select_cb(username))
        self.append(avatar)

        name_lbl = Gtk.Label(label=username)
        name_lbl.set_markup(
            f'<span font="12" foreground="white">{username}</span>'
        )
        self.append(name_lbl)


class GreeterWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("CryOS Greeter")
        self.set_decorated(False)
        self.fullscreen()
        self._selected_user = None
        self._greeter = None

        if HAVE_LIGHTDM:
            self._greeter = LightDM.Greeter()
            self._greeter.connect("authentication-complete",
                                  self._on_auth_complete)
            self._greeter.connect_to_daemon_sync()

        # Тёмный фон
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
        .cry-greeter {
            background: linear-gradient(135deg, #000028 0%, #000060 100%);
        }
        .cry-login-box {
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 6px;
            padding: 24px;
        }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10
        )
        self.add_css_class("cry-greeter")

        # Центральный контейнер
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=32)
        outer.set_valign(Gtk.Align.CENTER)
        outer.set_halign(Gtk.Align.CENTER)

        # Маскот
        mascot = Gtk.Label()
        mascot.set_markup(
            f'<span font="Monospace 13" foreground="#aaddff">{KONATA_ART}</span>'
        )
        outer.append(mascot)

        # Часы
        outer.append(GreeterClock())

        # Список пользователей
        users = get_system_users()
        if len(users) > 1:
            user_row = Gtk.Box(spacing=20)
            user_row.set_halign(Gtk.Align.CENTER)
            for u in users[:6]:
                user_row.append(UserButton(u, self._select_user))
            outer.append(user_row)

        # Форма входа
        login_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        login_box.set_halign(Gtk.Align.CENTER)
        login_box.set_size_request(320, -1)
        login_box.add_css_class("cry-login-box")

        self.user_entry = Gtk.Entry()
        self.user_entry.set_placeholder_text("Имя пользователя")
        if users:
            self.user_entry.set_text(users[0])
        login_box.append(self.user_entry)

        self.pass_entry = Gtk.Entry()
        self.pass_entry.set_visibility(False)
        self.pass_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.pass_entry.set_placeholder_text("Пароль")
        self.pass_entry.connect("activate", self._login)
        login_box.append(self.pass_entry)

        self.msg_lbl = Gtk.Label()
        self.msg_lbl.set_markup('<span foreground="white"> </span>')
        login_box.append(self.msg_lbl)

        login_btn = Gtk.Button(label="  Войти  ▶")
        login_btn.add_css_class("suggested-action")
        login_btn.connect("clicked", self._login)
        login_box.append(login_btn)

        outer.append(login_box)

        # Кнопки выключения
        power_box = Gtk.Box(spacing=16)
        power_box.set_halign(Gtk.Align.CENTER)
        power_box.set_margin_top(16)

        for label, cmd in [
            ("⏻ Выключить",  ["systemctl", "poweroff"]),
            ("↺ Перезагрузить", ["systemctl", "reboot"]),
        ]:
            btn = Gtk.Button(label=label)
            btn.set_has_frame(False)
            btn.add_css_class("flat")
            btn.connect("clicked", lambda b, c=cmd: self._power(c))
            # Метка белая
            lbl = btn.get_child()
            if lbl:
                lbl.set_markup(f'<span foreground="white">{label}</span>')
            power_box.append(btn)

        outer.append(power_box)

        # Блокировка Escape/Alt+F-keys
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._block_keys)
        self.add_controller(key_ctrl)

        self.set_child(outer)
        self.pass_entry.grab_focus()

    def _select_user(self, username: str):
        self.user_entry.set_text(username)
        self.pass_entry.grab_focus()

    def _login(self, *_):
        username = self.user_entry.get_text().strip()
        password = self.pass_entry.get_text()
        self.pass_entry.set_text("")

        if not username or not password:
            self._show_msg("Введите имя пользователя и пароль", "#ffaaaa")
            return

        if HAVE_LIGHTDM and self._greeter:
            self._selected_user = username
            self._greeter.authenticate(username)
            self._greeter.respond(password)
            self._show_msg("🔄 Проверка…", "#aaaaff")
        else:
            # Fallback: PAM
            import threading
            def auth():
                ok = self._pam_auth(username, password)
                GLib.idle_add(self._on_auth_result, ok)
            threading.Thread(target=auth, daemon=True).start()
            self._show_msg("🔄 Проверка…", "#aaaaff")

    def _pam_auth(self, username: str, password: str) -> bool:
        try:
            import pam
            return pam.pam().authenticate(username, password)
        except ImportError:
            pass
        try:
            import pamela
            pamela.authenticate(username, password)
            return True
        except Exception:
            return False

    def _on_auth_result(self, ok: bool):
        if ok:
            self._show_msg("✓ Добро пожаловать!", "#aaffaa")
            GLib.timeout_add(500, self._start_session)
        else:
            self._show_msg("✗ Неверный пароль", "#ffaaaa")

    def _on_auth_complete(self, greeter):
        if greeter.get_is_authenticated():
            greeter.start_session_sync("cryos")
        else:
            self._show_msg("✗ Неверный пароль", "#ffaaaa")

    def _start_session(self):
        import subprocess
        session_py = CRYOS_ROOT / "system" / "session" / "session.py"
        if session_py.exists():
            subprocess.Popen([sys.executable, str(session_py)])
        return False

    def _show_msg(self, text: str, color: str):
        self.msg_lbl.set_markup(f'<span foreground="{color}">{text}</span>')

    def _block_keys(self, ctrl, keyval, keycode, state):
        M = Gdk.ModifierType
        if state & M.CONTROL_MASK and state & M.ALT_MASK:
            if Gdk.KEY_F1 <= keyval <= Gdk.KEY_F12:
                return True
        return False

    def _power(self, cmd: list[str]):
        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"{cmd[-1].capitalize()}?"
        )
        if dlg.run() == Gtk.ResponseType.YES:
            import subprocess
            subprocess.run(cmd)
        dlg.destroy()


class GreeterApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.cryos.Greeter",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        if THEME_CSS.exists():
            p = Gtk.CssProvider(); p.load_from_path(str(THEME_CSS))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        GreeterWindow(self).present()


def main():
    GreeterApp().run(sys.argv)

if __name__ == "__main__":
    main()
