#!/usr/bin/env python3
"""
CryOS Notify Daemon  —  apps/notify/main.py
=============================================
Реализует D-Bus интерфейс org.freedesktop.Notifications.
Всплывающие плашки в правом нижнем углу экрана.
Стиль: белый фон, синяя полоска слева, иконка, кнопка ✕.
Очередь, таймаут, история уведомлений.
Зависимости: python3-gi, python3-dbus
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio
import sys, time, threading
from pathlib import Path
from collections import deque

CRYOS_ROOT = Path(__file__).parent.parent.parent
THEME_CSS  = CRYOS_ROOT / "system" / "theme" / "gtk.css"

NOTIF_WIDTH   = 340
NOTIF_HEIGHT  = 80
NOTIF_MARGIN  = 12
NOTIF_TIMEOUT = 5000   # мс по умолчанию
MAX_VISIBLE   = 5      # максимум плашек одновременно
SCREEN_MARGIN = 40     # отступ от края экрана

# ── CSS уведомления ───────────────────────────────────────────────
NOTIF_CSS = b"""
.cry-notif-window {
    background: transparent;
}
.cry-notif-box {
    background: white;
    border: 1px solid #c0c0c0;
    border-radius: 2px;
    box-shadow: 2px 2px 6px rgba(0,0,0,0.3);
}
.cry-notif-strip {
    background: #000080;
    min-width: 4px;
    border-radius: 2px 0 0 2px;
}
.cry-notif-title {
    font-weight: bold;
    font-size: 11pt;
    color: #000080;
}
.cry-notif-body {
    font-size: 10pt;
    color: #333333;
}
.cry-notif-close {
    color: #666;
    font-size: 10pt;
    min-width: 20px;
    min-height: 20px;
    padding: 0;
}
"""


# ── Модель уведомления ────────────────────────────────────────────
class Notification:
    _counter = 0

    def __init__(self, app_name, summary, body, icon, timeout, hints, actions):
        Notification._counter += 1
        self.id       = Notification._counter
        self.app_name = app_name
        self.summary  = summary or "Уведомление"
        self.body     = body or ""
        self.icon     = icon or ""
        self.timeout  = timeout if timeout > 0 else NOTIF_TIMEOUT
        self.hints    = hints
        self.actions  = actions
        self.created  = time.time()


# ── Плашка уведомления ────────────────────────────────────────────
class NotifToast(Gtk.Window):
    """Одна всплывающая плашка."""

    def __init__(self, notif: Notification, y_offset: int, on_close):
        super().__init__()
        self.notif = notif
        self.on_close = on_close
        self._timer_id = None

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(NOTIF_WIDTH, -1)
        self.add_css_class("cry-notif-window")
        self.set_opacity(0.97)

        # Позиция: правый нижний угол
        self._y_offset = y_offset
        self._position()

        self._build_ui()

        # Автозакрытие
        if notif.timeout > 0:
            self._timer_id = GLib.timeout_add(notif.timeout, self._auto_close)

    def _position(self):
        display = Gdk.Display.get_default()
        monitors = display.get_monitors()
        w = h = 1280
        if monitors.get_n_items() > 0:
            g = monitors.get_item(0).get_geometry()
            w, h = g.width, g.height
        x = w - NOTIF_WIDTH - SCREEN_MARGIN
        y = h - SCREEN_MARGIN - self._y_offset - NOTIF_HEIGHT
        # GTK4: позиционирование через geometry hint
        # (упрощённо — окно появится в правом углу через оконный менеджер)
        self.set_size_request(NOTIF_WIDTH, NOTIF_HEIGHT)

    def _build_ui(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        outer.add_css_class("cry-notif-box")
        outer.set_size_request(NOTIF_WIDTH, -1)

        # Синяя полоска слева
        strip = Gtk.Box()
        strip.add_css_class("cry-notif-strip")
        strip.set_size_request(5, -1)
        outer.append(strip)

        # Иконка
        icon_lbl = Gtk.Label()
        icon_text = self._get_icon_char()
        icon_lbl.set_markup(f'<span font="20">{icon_text}</span>')
        icon_lbl.set_margin_start(8)
        icon_lbl.set_margin_end(6)
        icon_lbl.set_valign(Gtk.Align.CENTER)
        outer.append(icon_lbl)

        # Текст
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)
        text_box.set_margin_top(8)
        text_box.set_margin_bottom(8)

        title = Gtk.Label(label=self.notif.summary[:60])
        title.add_css_class("cry-notif-title")
        title.set_halign(Gtk.Align.START)
        title.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        text_box.append(title)

        if self.notif.body:
            body = Gtk.Label(label=self.notif.body[:120])
            body.add_css_class("cry-notif-body")
            body.set_halign(Gtk.Align.START)
            body.set_wrap(True)
            body.set_max_width_chars(35)
            text_box.append(body)

        outer.append(text_box)

        # Кнопка закрытия
        close_btn = Gtk.Button(label="✕")
        close_btn.add_css_class("cry-notif-close")
        close_btn.set_has_frame(False)
        close_btn.set_valign(Gtk.Align.START)
        close_btn.set_margin_top(4)
        close_btn.set_margin_end(4)
        close_btn.connect("clicked", lambda *_: self.dismiss())
        outer.append(close_btn)

        self.set_child(outer)

    def _get_icon_char(self) -> str:
        icon = self.notif.icon.lower()
        if "error" in icon or "critical" in icon:
            return "❌"
        if "warn" in icon:
            return "⚠️"
        if "info" in icon or "dialog-information" in icon:
            return "ℹ️"
        if "mail" in icon or "email" in icon:
            return "📧"
        if "network" in icon:
            return "🌐"
        if "battery" in icon:
            return "🔋"
        if "update" in icon:
            return "🔄"
        return "🔔"

    def dismiss(self):
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
        self.on_close(self)
        self.destroy()

    def _auto_close(self):
        self.dismiss()
        return False


# ── Менеджер всплывашек ───────────────────────────────────────────
class ToastManager:
    """Управляет очередью и позициями плашек."""

    def __init__(self):
        self._active: list[NotifToast] = []
        self._queue: deque[Notification] = deque()
        self._history: list[Notification] = []

    def show(self, notif: Notification):
        self._history.append(notif)
        if len(self._history) > 100:
            self._history.pop(0)

        if len(self._active) >= MAX_VISIBLE:
            self._queue.append(notif)
            return

        self._spawn(notif)

    def _spawn(self, notif: Notification):
        y_offset = len(self._active) * (NOTIF_HEIGHT + NOTIF_MARGIN)
        toast = NotifToast(notif, y_offset, self._on_closed)
        self._active.append(toast)
        toast.present()

    def _on_closed(self, toast: NotifToast):
        if toast in self._active:
            self._active.remove(toast)
        self._reposition()
        # Показываем следующее из очереди
        if self._queue and len(self._active) < MAX_VISIBLE:
            next_notif = self._queue.popleft()
            self._spawn(next_notif)

    def _reposition(self):
        """Пересчитываем Y-позиции оставшихся плашек."""
        for i, toast in enumerate(self._active):
            toast._y_offset = i * (NOTIF_HEIGHT + NOTIF_MARGIN)

    @property
    def history(self) -> list[Notification]:
        return list(self._history)


_toast_manager = ToastManager()


# ── D-Bus сервер уведомлений ──────────────────────────────────────
DBUS_XML = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="GetCapabilities">
      <arg direction="out" type="as" name="capabilities"/>
    </method>
    <method name="Notify">
      <arg direction="in"  type="s"  name="app_name"/>
      <arg direction="in"  type="u"  name="replaces_id"/>
      <arg direction="in"  type="s"  name="app_icon"/>
      <arg direction="in"  type="s"  name="summary"/>
      <arg direction="in"  type="s"  name="body"/>
      <arg direction="in"  type="as" name="actions"/>
      <arg direction="in"  type="a{sv}" name="hints"/>
      <arg direction="in"  type="i"  name="expire_timeout"/>
      <arg direction="out" type="u"  name="id"/>
    </method>
    <method name="CloseNotification">
      <arg direction="in" type="u" name="id"/>
    </method>
    <method name="GetServerInformation">
      <arg direction="out" type="s" name="name"/>
      <arg direction="out" type="s" name="vendor"/>
      <arg direction="out" type="s" name="version"/>
      <arg direction="out" type="s" name="spec_version"/>
    </method>
  </interface>
</node>
"""

try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False


def start_dbus_server():
    if not DBUS_AVAILABLE:
        print("[cryos-notify] python3-dbus не установлен, D-Bus отключён", file=sys.stderr)
        return

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    bus.request_name("org.freedesktop.Notifications")

    class NotifService(dbus.service.Object):
        def __init__(self):
            super().__init__(bus, "/org/freedesktop/Notifications")

        @dbus.service.method("org.freedesktop.Notifications",
                             in_signature="", out_signature="as")
        def GetCapabilities(self):
            return ["body", "body-markup", "icon-static", "actions"]

        @dbus.service.method("org.freedesktop.Notifications",
                             in_signature="susssasa{sv}i", out_signature="u")
        def Notify(self, app_name, replaces_id, app_icon, summary,
                   body, actions, hints, expire_timeout):
            notif = Notification(app_name, summary, body, app_icon,
                                 expire_timeout, dict(hints), list(actions))
            GLib.idle_add(_toast_manager.show, notif)
            return notif.id

        @dbus.service.method("org.freedesktop.Notifications",
                             in_signature="u", out_signature="")
        def CloseNotification(self, notif_id):
            for toast in list(_toast_manager._active):
                if toast.notif.id == notif_id:
                    GLib.idle_add(toast.dismiss)

        @dbus.service.method("org.freedesktop.Notifications",
                             in_signature="", out_signature="ssss")
        def GetServerInformation(self):
            return ("CryOS Notify", "CryOS", "1.0", "1.2")

    NotifService()


# ── История уведомлений (окно) ────────────────────────────────────
class HistoryWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="История уведомлений")
        self.set_default_size(480, 400)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        hdr = Gtk.Label()
        hdr.set_markup('<b>  История уведомлений</b>')
        hdr.set_halign(Gtk.Align.START)
        hdr.set_margin_top(8)
        hdr.set_margin_bottom(8)
        vbox.append(hdr)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        self._list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        scroll.set_child(self._list)
        vbox.append(scroll)

        clear_btn = Gtk.Button(label="Очистить историю")
        clear_btn.set_margin_top(4)
        clear_btn.set_margin_bottom(4)
        clear_btn.connect("clicked", self._clear)
        vbox.append(clear_btn)

        self.set_child(vbox)
        self._refresh()

    def _refresh(self):
        while child := self._list.get_first_child():
            self._list.remove(child)
        for notif in reversed(_toast_manager.history):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.set_margin_start(8)
            row.set_margin_end(8)
            row.set_margin_top(4)
            row.set_margin_bottom(4)
            lbl = Gtk.Label()
            lbl.set_markup(
                f'<b>{notif.summary}</b>  '
                f'<span foreground="#888" size="small">{notif.app_name}</span>'
                + (f'\n<span size="small">{notif.body}</span>' if notif.body else "")
            )
            lbl.set_halign(Gtk.Align.START)
            lbl.set_wrap(True)
            row.append(lbl)
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            col.append(row)
            col.append(sep)
            self._list.append(col)

    def _clear(self, *_):
        _toast_manager._history.clear()
        self._refresh()


# ── Главное приложение ────────────────────────────────────────────
class NotifyApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="org.cryos.Notify",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )

    def do_activate(self):
        # CSS
        provider = Gtk.CssProvider()
        provider.load_from_data(NOTIF_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        if THEME_CSS.exists():
            p = Gtk.CssProvider()
            p.load_from_path(str(THEME_CSS))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), p,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

        # Запускаем D-Bus сервер
        start_dbus_server()

        # Тестовое уведомление при запуске
        test = Notification(
            "CryOS", "CryOS запущен", "Демон уведомлений активен",
            "dialog-information", 4000, {}, []
        )
        GLib.timeout_add(500, lambda: (_toast_manager.show(test), False))

        # Окно истории (скрыто, открывается по клику на трей)
        self._history_win = HistoryWindow(self)
        # self._history_win.present()  # раскомментить для отладки

        # Держим приложение живым (фоновый демон)
        self.hold()


def main():
    app = NotifyApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
