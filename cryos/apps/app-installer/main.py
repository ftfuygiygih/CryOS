#!/usr/bin/env python3
"""
CryOS App Installer  —  apps/app-installer/main.py
===================================================
Установка приложений: Flatpak и AppImage.
AppImage: автопроверка прав, предложение chmod +x.
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gio
import subprocess
import os
import sys
import threading
import stat
from pathlib import Path

THEME_CSS    = Path(__file__).parent.parent.parent / "system" / "theme" / "gtk.css"
APPIMAGE_DIR = Path.home() / "Applications"
APPIMAGE_DIR.mkdir(parents=True, exist_ok=True)


# ── Вкладка Flatpak ───────────────────────────────────────────────
class FlatpakTab(Gtk.Box):
    def __init__(self, log_fn):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.log = log_fn
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self._build()

    def _build(self):
        # Поиск/установка по App ID
        frame = Gtk.Frame(label="Установка Flatpak-приложения")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8); box.set_margin_bottom(8)
        box.set_margin_start(8); box.set_margin_end(8)

        box.append(Gtk.Label(label="App ID (например: org.videolan.VLC):"))
        self.id_entry = Gtk.Entry()
        self.id_entry.set_placeholder_text("org.videolan.VLC")
        box.append(self.id_entry)

        box.append(Gtk.Label(label="Удалённый репозиторий:"))
        self.remote_entry = Gtk.Entry(text="flathub")
        box.append(self.remote_entry)

        btn_box = Gtk.Box(spacing=6)
        install_btn = Gtk.Button(label="⬇ Установить")
        install_btn.connect("clicked", self._on_install)
        btn_box.append(install_btn)

        uninstall_btn = Gtk.Button(label="✗ Удалить")
        uninstall_btn.add_css_class("destructive-action")
        uninstall_btn.connect("clicked", self._on_uninstall)
        btn_box.append(uninstall_btn)

        info_btn = Gtk.Button(label="ℹ Информация")
        info_btn.connect("clicked", self._on_info)
        btn_box.append(info_btn)

        box.append(btn_box)
        frame.set_child(box)
        self.append(frame)

        # Список установленных Flatpak
        list_frame = Gtk.Frame(label="Установленные Flatpak")
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        list_box.set_margin_top(4); list_box.set_margin_bottom(4)
        list_box.set_margin_start(4); list_box.set_margin_end(4)

        refresh_btn = Gtk.Button(label="↺ Обновить список")
        refresh_btn.connect("clicked", lambda b: self._refresh_installed())
        list_box.append(refresh_btn)

        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(-1, 200)
        self.installed_view = Gtk.TextView()
        self.installed_view.set_editable(False)
        self.installed_view.set_monospace(True)
        scroll.set_child(self.installed_view)
        list_box.append(scroll)

        list_frame.set_child(list_box)
        self.append(list_frame)

        self._refresh_installed()

    def _refresh_installed(self):
        def run():
            result = subprocess.run(
                ["flatpak", "list", "--app", "--columns=application,name,version"],
                capture_output=True, text=True
            )
            GLib.idle_add(self._set_installed, result.stdout if result.returncode == 0
                          else "Flatpak не установлен или ошибка:\n" + result.stderr)
        threading.Thread(target=run, daemon=True).start()

    def _set_installed(self, text):
        self.installed_view.get_buffer().set_text(text or "(нет установленных приложений)")

    def _on_install(self, *_):
        app_id = self.id_entry.get_text().strip()
        remote  = self.remote_entry.get_text().strip() or "flathub"
        if not app_id:
            self.log("⚠ Введите App ID"); return
        self.log(f"Установка {app_id} из {remote}...")
        def run():
            result = subprocess.run(
                ["flatpak", "install", "-y", remote, app_id],
                capture_output=True, text=True
            )
            out = result.stdout + result.stderr
            GLib.idle_add(self.log, out)
            if result.returncode == 0:
                GLib.idle_add(self.log, f"✅ {app_id} установлен")
                GLib.idle_add(self._refresh_installed)
            else:
                GLib.idle_add(self.log, f"❌ Ошибка установки {app_id}")
        threading.Thread(target=run, daemon=True).start()

    def _on_uninstall(self, *_):
        app_id = self.id_entry.get_text().strip()
        if not app_id:
            self.log("⚠ Введите App ID"); return
        self.log(f"Удаление {app_id}...")
        def run():
            result = subprocess.run(
                ["flatpak", "uninstall", "-y", app_id],
                capture_output=True, text=True
            )
            GLib.idle_add(self.log, result.stdout + result.stderr)
            GLib.idle_add(self._refresh_installed)
        threading.Thread(target=run, daemon=True).start()

    def _on_info(self, *_):
        app_id = self.id_entry.get_text().strip()
        if not app_id:
            self.log("⚠ Введите App ID"); return
        def run():
            result = subprocess.run(
                ["flatpak", "info", app_id],
                capture_output=True, text=True
            )
            GLib.idle_add(self.log, result.stdout or result.stderr)
        threading.Thread(target=run, daemon=True).start()


# ── Вкладка AppImage ──────────────────────────────────────────────
class AppImageTab(Gtk.Box):
    def __init__(self, log_fn, parent_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.log = log_fn
        self.parent = parent_window
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self._build()

    def _build(self):
        info = Gtk.Label()
        info.set_markup(
            "AppImage-файлы запускаются без установки.\n"
            f"Рекомендуемая папка: <b>{APPIMAGE_DIR}</b>"
        )
        info.set_halign(Gtk.Align.START)
        self.append(info)

        # Выбор файла
        file_frame = Gtk.Frame(label="Выбрать AppImage")
        file_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        file_box.set_margin_top(8); file_box.set_margin_bottom(8)
        file_box.set_margin_start(8); file_box.set_margin_end(8)

        path_box = Gtk.Box(spacing=4)
        self.path_entry = Gtk.Entry()
        self.path_entry.set_hexpand(True)
        self.path_entry.set_placeholder_text("Путь к .AppImage файлу")
        browse_btn = Gtk.Button(label="Обзор...")
        browse_btn.connect("clicked", self._on_browse)
        path_box.append(self.path_entry)
        path_box.append(browse_btn)
        file_box.append(path_box)

        btn_box = Gtk.Box(spacing=6)
        check_btn = Gtk.Button(label="🔍 Проверить права")
        check_btn.connect("clicked", self._on_check)
        btn_box.append(check_btn)

        chmod_btn = Gtk.Button(label="🔧 Сделать исполняемым")
        chmod_btn.connect("clicked", self._on_chmod)
        btn_box.append(chmod_btn)

        run_btn = Gtk.Button(label="▶ Запустить")
        run_btn.add_css_class("suggested-action")
        run_btn.connect("clicked", self._on_run)
        btn_box.append(run_btn)

        install_btn = Gtk.Button(label="📥 Скопировать в Applications")
        install_btn.connect("clicked", self._on_install)
        btn_box.append(install_btn)

        file_box.append(btn_box)
        file_frame.set_child(file_box)
        self.append(file_frame)

        # Список AppImage в папке Applications
        list_frame = Gtk.Frame(label=f"Файлы в ~/Applications")
        list_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        list_vbox.set_margin_top(4); list_vbox.set_margin_bottom(4)
        list_vbox.set_margin_start(4); list_vbox.set_margin_end(4)

        refresh_btn = Gtk.Button(label="↺ Обновить")
        refresh_btn.connect("clicked", lambda b: self._refresh_list())
        list_vbox.append(refresh_btn)

        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(-1, 160)
        self.app_list = Gtk.ListBox()
        self.app_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        scroll.set_child(self.app_list)
        list_vbox.append(scroll)

        list_frame.set_child(list_vbox)
        self.append(list_frame)

        self._refresh_list()

    def _refresh_list(self):
        while row := self.app_list.get_row_at_index(0):
            self.app_list.remove(row)

        appimages = list(APPIMAGE_DIR.glob("*.AppImage")) + list(APPIMAGE_DIR.glob("*.appimage"))
        if not appimages:
            row = Gtk.ListBoxRow()
            row.set_child(Gtk.Label(label="Нет AppImage файлов"))
            self.app_list.append(row)
            return

        for ai in appimages:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=8)
            box.set_margin_top(3); box.set_margin_bottom(3)
            box.set_margin_start(8)
            mode   = ai.stat().st_mode
            is_exe = bool(mode & stat.S_IXUSR)
            icon   = Gtk.Label(label="▶" if is_exe else "🔒")
            name   = Gtk.Label(label=ai.name)
            name.set_halign(Gtk.Align.START)
            name.set_hexpand(True)
            perm   = Gtk.Label(label="исполняемый" if is_exe else "не исполняемый")
            perm.add_css_class("dim-label")
            run_b  = Gtk.Button(label="▶")
            run_b.connect("clicked", lambda b, p=ai: self._run_appimage(str(p)))
            box.append(icon); box.append(name); box.append(perm); box.append(run_b)
            row.set_child(box)
            self.app_list.append(row)

    def _on_browse(self, *_):
        dlg = Gtk.FileDialog()
        dlg.set_title("Выберите AppImage")
        filt = Gtk.FileFilter()
        filt.set_name("AppImage (*.AppImage, *.appimage)")
        filt.add_pattern("*.AppImage")
        filt.add_pattern("*.appimage")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filt)
        dlg.set_filters(filters)
        dlg.open(self.parent, None, self._browse_done)

    def _browse_done(self, dlg, result):
        try:
            file = dlg.open_finish(result)
            if file:
                self.path_entry.set_text(file.get_path())
                self._on_check()
        except Exception:
            pass

    def _on_check(self, *_):
        path = self.path_entry.get_text().strip()
        if not path or not Path(path).exists():
            self.log("⚠ Файл не найден"); return
        mode = Path(path).stat().st_mode
        is_exe = bool(mode & stat.S_IXUSR)
        if is_exe:
            self.log(f"✅ {Path(path).name}: файл уже исполняемый")
        else:
            self.log(f"⚠ {Path(path).name}: файл НЕ исполняемый. Нажмите «Сделать исполняемым»")
            self._offer_chmod(path)

    def _offer_chmod(self, path):
        dlg = Gtk.MessageDialog(
            transient_for=self.parent, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Файл не исполняемый",
        )
        dlg.format_secondary_text(
            f"{Path(path).name} не имеет права на выполнение.\n"
            "Сделать файл исполняемым (chmod +x)?"
        )
        if dlg.run() == Gtk.ResponseType.YES:
            self._chmod_file(path)
        dlg.destroy()

    def _on_chmod(self, *_):
        path = self.path_entry.get_text().strip()
        if path:
            self._chmod_file(path)

    def _chmod_file(self, path):
        try:
            p = Path(path)
            p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            self.log(f"✅ chmod +x: {p.name}")
            self._refresh_list()
        except Exception as e:
            self.log(f"❌ Ошибка chmod: {e}")

    def _on_run(self, *_):
        path = self.path_entry.get_text().strip()
        if path:
            self._run_appimage(path)

    def _run_appimage(self, path: str):
        p = Path(path)
        if not p.exists():
            self.log(f"❌ Файл не найден: {path}"); return
        if not (p.stat().st_mode & stat.S_IXUSR):
            self._offer_chmod(path)
            return
        try:
            subprocess.Popen([str(p)], start_new_session=True)
            self.log(f"▶ Запущен: {p.name}")
        except Exception as e:
            self.log(f"❌ Ошибка запуска: {e}")

    def _on_install(self, *_):
        path = self.path_entry.get_text().strip()
        if not path:
            return
        src = Path(path)
        dst = APPIMAGE_DIR / src.name
        if dst.exists():
            self.log(f"⚠ {dst.name} уже существует в Applications")
            return
        import shutil
        shutil.copy2(src, dst)
        # chmod +x автоматически
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.log(f"✅ Скопирован и помечен исполняемым: {dst.name}")
        self._refresh_list()


# ── Главное окно ──────────────────────────────────────────────────
class AppInstallerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CryOS — Установка приложений")
        self.set_default_size(680, 580)
        self._build()

    def _build(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Gtk.Box()
        header.add_css_class("cry-oobe-header")
        title = Gtk.Label()
        title.set_markup('<span foreground="white" font="13" weight="bold">📦 Установка приложений</span>')
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        title.set_margin_start(8)
        header.append(title)
        vbox.append(header)

        notebook = Gtk.Notebook()

        flatpak_tab = FlatpakTab(self._log)
        notebook.append_page(flatpak_tab, Gtk.Label(label="Flatpak"))

        appimage_tab = AppImageTab(self._log, self)
        notebook.append_page(appimage_tab, Gtk.Label(label="AppImage"))

        notebook.set_vexpand(True)
        vbox.append(notebook)

        sep = Gtk.Separator()
        vbox.append(sep)

        # Лог
        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_monospace(True)
        self.log_view.set_size_request(-1, 100)
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_size_request(-1, 100)
        log_scroll.set_child(self.log_view)
        vbox.append(log_scroll)

        self.set_child(vbox)

    def _log(self, text: str):
        buf = self.log_view.get_buffer()
        buf.insert(buf.get_end_iter(), text.strip() + "\n")


class AppInstallerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.cryos.AppInstaller",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        if THEME_CSS.exists():
            p = Gtk.CssProvider()
            p.load_from_path(str(THEME_CSS))
            import gi; gi.require_version("Gdk","4.0")
            from gi.repository import Gdk
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), p,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        win = AppInstallerWindow(self)
        win.present()

def main():
    app = AppInstallerApp()
    app.run(sys.argv)

if __name__ == "__main__":
    main()
