#!/usr/bin/env python3
"""
CryOS Image Viewer  —  apps/image-viewer/main.py
=================================================
Открытие PNG, JPG, BMP, GIF.
Масштабирование колёсиком, переключение по папке стрелками,
полноэкранный режим, информация о файле.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GLib, Gio, GdkPixbuf
import sys
from pathlib import Path

CRYOS_ROOT = Path(__file__).parent.parent.parent
THEME_CSS  = CRYOS_ROOT / "system" / "theme" / "gtk.css"

SUPPORTED = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff", ".ico"}


class ImageViewer(Gtk.ApplicationWindow):
    def __init__(self, app, filepath: Path | None = None):
        super().__init__(application=app)
        self.set_default_size(900, 650)
        self.set_title("CryOS Просмотрщик")
        self.add_css_class("cry-window")

        self._files: list[Path] = []
        self._index = 0
        self._zoom  = 1.0
        self._pixbuf: GdkPixbuf.Pixbuf | None = None
        self._fullscreen = False

        self._build_ui()
        self._setup_shortcuts()

        if filepath:
            self._load_directory(filepath)
            self._show_image()

    def _build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Тулбар
        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        tb.add_css_class("cry-menubar")
        tb.set_margin_start(4)
        tb.set_margin_top(2)
        tb.set_margin_bottom(2)

        def tb_btn(label, cb, tooltip=""):
            b = Gtk.Button(label=label)
            b.set_has_frame(False)
            b.add_css_class("flat")
            b.set_tooltip_text(tooltip)
            b.connect("clicked", cb)
            tb.append(b)
            return b

        tb_btn("📂 Открыть", self._open_dialog, "Открыть файл")
        tb_btn("◀", lambda *_: self._prev(), "Предыдущее (←)")
        tb_btn("▶", lambda *_: self._next(), "Следующее (→)")

        tb.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        tb_btn("🔍+", lambda *_: self._zoom_in(), "Увеличить (+)")
        tb_btn("🔍−", lambda *_: self._zoom_out(), "Уменьшить (-)")
        tb_btn("⊡",   lambda *_: self._zoom_fit(), "По размеру окна (0)")
        tb_btn("1:1",  lambda *_: self._zoom_reset(), "Оригинальный размер (1)")

        tb.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        tb_btn("⛶ Полный экран", lambda *_: self._toggle_fullscreen(), "F11")

        tb.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self.info_lbl = Gtk.Label(label="")
        self.info_lbl.set_hexpand(True)
        self.info_lbl.set_halign(Gtk.Align.END)
        self.info_lbl.set_margin_end(8)
        tb.append(self.info_lbl)

        vbox.append(tb)

        # Холст с прокруткой
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_vexpand(True)
        self.scroll.set_hexpand(True)

        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(False)
        self.picture.set_content_fit(Gtk.ContentFit.SCALE_DOWN)
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)

        self.scroll.set_child(self.picture)
        vbox.append(self.scroll)

        # Статус-бар
        self.status = Gtk.Label(label="Нет файла")
        self.status.set_halign(Gtk.Align.START)
        self.status.set_margin_start(8)
        self.status.set_margin_top(2)
        self.status.set_margin_bottom(2)
        vbox.append(self.status)

        self.set_child(vbox)

        # Жест масштабирования колёсиком
        scroll_ctrl = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL
        )
        scroll_ctrl.connect("scroll", self._on_scroll_zoom)
        self.scroll.add_controller(scroll_ctrl)

    def _setup_shortcuts(self):
        ctrl = Gtk.ShortcutController()
        ctrl.set_scope(Gtk.ShortcutScope.MANAGED)
        self.add_controller(ctrl)

        def shortcut(key, mods, cb):
            trigger = Gtk.KeyvalTrigger(keyval=key, modifiers=mods)
            action  = Gtk.CallbackAction.new(lambda *a: cb() or True)
            ctrl.add_shortcut(Gtk.Shortcut(trigger=trigger, action=action))

        M = Gdk.ModifierType
        shortcut(Gdk.KEY_Left,      M(0), self._prev)
        shortcut(Gdk.KEY_Right,     M(0), self._next)
        shortcut(Gdk.KEY_plus,      M(0), self._zoom_in)
        shortcut(Gdk.KEY_minus,     M(0), self._zoom_out)
        shortcut(Gdk.KEY_0,         M(0), self._zoom_fit)
        shortcut(Gdk.KEY_1,         M(0), self._zoom_reset)
        shortcut(Gdk.KEY_F11,       M(0), self._toggle_fullscreen)
        shortcut(Gdk.KEY_Escape,    M(0), self._exit_fullscreen)
        shortcut(Gdk.KEY_o,         M.CONTROL_MASK, self._open_dialog)

    def _load_directory(self, filepath: Path):
        """Загружаем все изображения из папки файла."""
        folder = filepath.parent
        self._files = sorted(
            [f for f in folder.iterdir() if f.suffix.lower() in SUPPORTED],
            key=lambda p: p.name.lower()
        )
        try:
            self._index = self._files.index(filepath)
        except ValueError:
            self._index = 0

    def _show_image(self):
        if not self._files:
            self.status.set_text("Нет изображений")
            return
        path = self._files[self._index]
        try:
            self._pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
            self._apply_zoom()
            w = self._pixbuf.get_width()
            h = self._pixbuf.get_height()
            size = path.stat().st_size
            size_str = f"{size//1024} КБ" if size >= 1024 else f"{size} Б"
            self.status.set_text(
                f"{path.name}  |  {w}×{h} пкс  |  {size_str}"
            )
            self.info_lbl.set_text(
                f"{self._index+1} / {len(self._files)}"
            )
            self.set_title(f"{path.name} — CryOS Просмотрщик")
        except Exception as e:
            self.status.set_text(f"Ошибка: {e}")

    def _apply_zoom(self):
        if not self._pixbuf:
            return
        w = int(self._pixbuf.get_width()  * self._zoom)
        h = int(self._pixbuf.get_height() * self._zoom)
        scaled = self._pixbuf.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
        self.picture.set_pixbuf(scaled)

    def _zoom_in(self):
        self._zoom = min(self._zoom * 1.25, 8.0)
        self._apply_zoom()

    def _zoom_out(self):
        self._zoom = max(self._zoom / 1.25, 0.05)
        self._apply_zoom()

    def _zoom_fit(self):
        if not self._pixbuf:
            return
        alloc = self.scroll.get_allocation()
        if alloc.width <= 1:
            return
        wz = alloc.width  / self._pixbuf.get_width()
        hz = alloc.height / self._pixbuf.get_height()
        self._zoom = min(wz, hz, 1.0)
        self._apply_zoom()

    def _zoom_reset(self):
        self._zoom = 1.0
        self._apply_zoom()

    def _prev(self):
        if self._files:
            self._index = (self._index - 1) % len(self._files)
            self._zoom = 1.0
            self._show_image()

    def _next(self):
        if self._files:
            self._index = (self._index + 1) % len(self._files)
            self._zoom = 1.0
            self._show_image()

    def _on_scroll_zoom(self, ctrl, dx, dy):
        mods = ctrl.get_current_event_state()
        if mods & Gdk.ModifierType.CONTROL_MASK:
            if dy < 0:
                self._zoom_in()
            else:
                self._zoom_out()
            return True
        return False

    def _toggle_fullscreen(self):
        if self._fullscreen:
            self.unfullscreen()
            self._fullscreen = False
        else:
            self.fullscreen()
            self._fullscreen = True

    def _exit_fullscreen(self):
        if self._fullscreen:
            self.unfullscreen()
            self._fullscreen = False

    def _open_dialog(self, *_):
        dialog = Gtk.FileDialog()
        filt = Gtk.FileFilter()
        filt.set_name("Изображения")
        for ext in ["*.png","*.jpg","*.jpeg","*.bmp","*.gif","*.webp"]:
            filt.add_pattern(ext)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filt)
        dialog.set_filters(filters)
        dialog.open(self, None, self._on_open_response)

    def _on_open_response(self, dialog, result):
        try:
            f = dialog.open_finish(result)
            if f:
                p = Path(f.get_path())
                self._load_directory(p)
                self._zoom = 1.0
                self._show_image()
        except GLib.Error:
            pass


class ViewerApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="org.cryos.ImageViewer",
            flags=Gio.ApplicationFlags.HANDLES_OPEN
        )
        self.connect("open", self._on_open)

    def do_activate(self):
        self._load_css()
        ImageViewer(self).present()

    def _on_open(self, app, files, n_files, hint):
        self._load_css()
        for f in files:
            ImageViewer(self, filepath=Path(f.get_path())).present()

    def _load_css(self):
        if THEME_CSS.exists():
            p = Gtk.CssProvider()
            p.load_from_path(str(THEME_CSS))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), p,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )


def main():
    app = ViewerApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
