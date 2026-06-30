#!/usr/bin/env python3
"""
CryOS Git Manager  —  apps/git-manager/main.py
===============================================
Клонирование репозиториев, список проектов, удаление.
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gio
import subprocess
import shutil
import json
import sys
import threading
from pathlib import Path

PROJECTS_DIR = Path.home() / "Projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
REGISTRY     = Path.home() / ".config" / "cryos" / "git_projects.json"
THEME_CSS    = Path(__file__).parent.parent.parent / "system" / "theme" / "gtk.css"


def load_registry() -> list:
    if REGISTRY.exists():
        try:
            return json.loads(REGISTRY.read_text())
        except Exception:
            pass
    return []

def save_registry(projects: list):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(projects, indent=2))


# ── Диалог клонирования ───────────────────────────────────────────
class CloneDialog(Gtk.Dialog):
    def __init__(self, parent):
        super().__init__(title="Клонировать репозиторий", transient_for=parent, modal=True)
        self.add_button("Отмена", Gtk.ResponseType.CANCEL)
        self.add_button("Клонировать", Gtk.ResponseType.OK)
        self.set_default_size(440, -1)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(20)
        box.set_margin_end(20)

        box.append(Gtk.Label(label="URL репозитория:"))
        self.url_entry = Gtk.Entry()
        self.url_entry.set_placeholder_text("https://github.com/user/repo.git")
        box.append(self.url_entry)

        box.append(Gtk.Label(label="Название (опционально):"))
        self.name_entry = Gtk.Entry()
        self.name_entry.set_placeholder_text("Оставьте пустым — имя из URL")
        box.append(self.name_entry)

    def get_values(self):
        return self.url_entry.get_text().strip(), self.name_entry.get_text().strip()


# ── Строка проекта ────────────────────────────────────────────────
class ProjectRow(Gtk.Box):
    def __init__(self, project: dict, on_open, on_delete):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        self.set_margin_start(8)
        self.set_margin_end(8)

        icon = Gtk.Label(label="🌿")
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.set_hexpand(True)

        name_lbl = Gtk.Label(label=project.get("name", "?"))
        name_lbl.set_halign(Gtk.Align.START)
        name_lbl.set_markup(f'<b>{project.get("name","?")}</b>')

        url_lbl = Gtk.Label(label=project.get("url", ""))
        url_lbl.set_halign(Gtk.Align.START)
        url_lbl.add_css_class("dim-label")
        url_lbl.set_ellipsize(__import__("gi").repository.Pango.EllipsizeMode.END)
        url_lbl.set_max_width_chars(50)

        info.append(name_lbl)
        info.append(url_lbl)

        open_btn = Gtk.Button(label="Открыть")
        open_btn.connect("clicked", lambda b: on_open(project))

        del_btn = Gtk.Button(label="Удалить")
        del_btn.add_css_class("destructive-action")
        del_btn.connect("clicked", lambda b: on_delete(project))

        self.append(icon)
        self.append(info)
        self.append(open_btn)
        self.append(del_btn)


# ── Главное окно ──────────────────────────────────────────────────
class GitManagerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CryOS — Git Manager")
        self.set_default_size(640, 440)
        self.projects = load_registry()
        self._build_ui()

    def _build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Заголовок
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("cry-oobe-header")
        header.set_margin_bottom(0)
        header.set_margin_start(8)
        header.set_margin_end(8)
        header.set_margin_top(0)

        title = Gtk.Label()
        title.set_markup('<span foreground="white" font="13" weight="bold">🌿 Git Manager</span>')
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        header.append(title)
        vbox.append(header)

        # Тулбар
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)
        toolbar.set_margin_start(8)
        toolbar.set_margin_end(8)

        clone_btn = Gtk.Button(label="+ Клонировать")
        clone_btn.connect("clicked", self._on_clone)
        toolbar.append(clone_btn)

        refresh_btn = Gtk.Button(label="↺ Обновить список")
        refresh_btn.connect("clicked", lambda b: self._refresh_list())
        toolbar.append(refresh_btn)

        vbox.append(toolbar)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        vbox.append(sep)

        # Список проектов
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.set_child(self.list_box)
        vbox.append(scroll)

        # Консоль вывода
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        vbox.append(sep2)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_monospace(True)
        self.log_view.set_size_request(-1, 100)
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_size_request(-1, 100)
        log_scroll.set_child(self.log_view)
        vbox.append(log_scroll)

        self.set_child(vbox)
        self._refresh_list()

    def _refresh_list(self):
        while row := self.list_box.get_row_at_index(0):
            self.list_box.remove(row)

        if not self.projects:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label="Нет клонированных репозиториев.\nНажмите «+ Клонировать».")
            lbl.set_justify(Gtk.Justification.CENTER)
            lbl.set_margin_top(32)
            lbl.set_margin_bottom(32)
            row.set_child(lbl)
            self.list_box.append(row)
            return

        for proj in self.projects:
            row = Gtk.ListBoxRow()
            widget = ProjectRow(proj, self._on_open, self._on_delete)
            row.set_child(widget)
            self.list_box.append(row)

    def _log(self, text: str):
        buf = self.log_view.get_buffer()
        buf.insert(buf.get_end_iter(), text + "\n")
        # Прокрутка вниз
        GLib.idle_add(lambda: self.log_view.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0))

    def _on_clone(self, *_):
        dlg = CloneDialog(self)
        if dlg.run() == Gtk.ResponseType.OK:
            url, name = dlg.get_values()
            if url:
                if not name:
                    name = url.rstrip("/").split("/")[-1].removesuffix(".git")
                self._do_clone(url, name)
        dlg.destroy()

    def _do_clone(self, url: str, name: str):
        dest = PROJECTS_DIR / name
        if dest.exists():
            self._log(f"⚠ Папка {dest} уже существует")
            return

        self._log(f"Клонирование {url} → {dest} ...")

        def run():
            try:
                result = subprocess.run(
                    ["git", "clone", "--progress", url, str(dest)],
                    capture_output=True, text=True, timeout=300
                )
                GLib.idle_add(self._clone_done, url, name, str(dest), result.returncode,
                              result.stdout + result.stderr)
            except subprocess.TimeoutExpired:
                GLib.idle_add(self._log, "❌ Тайм-аут клонирования")
            except FileNotFoundError:
                GLib.idle_add(self._log, "❌ git не найден. Установите git.")

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def _clone_done(self, url, name, dest, code, output):
        self._log(output)
        if code == 0:
            self._log(f"✅ Клонирован: {name}")
            self.projects.append({"name": name, "url": url, "path": dest})
            save_registry(self.projects)
            self._refresh_list()
        else:
            self._log(f"❌ Ошибка клонирования (код {code})")

    def _on_open(self, project: dict):
        path = project.get("path", "")
        if Path(path).exists():
            try:
                subprocess.Popen(["xdg-open", path])
            except Exception:
                self._log(f"Открыть: {path}")
        else:
            self._log(f"⚠ Папка не найдена: {path}")

    def _on_delete(self, project: dict):
        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Удалить репозиторий «{project['name']}»?",
        )
        dlg.format_secondary_text(
            f"Папка {project.get('path','')} будет удалена безвозвратно."
        )
        if dlg.run() == Gtk.ResponseType.YES:
            path = Path(project.get("path", ""))
            if path.exists():
                shutil.rmtree(path)
                self._log(f"🗑 Удалён: {project['name']}")
            self.projects = [p for p in self.projects if p["name"] != project["name"]]
            save_registry(self.projects)
            self._refresh_list()
        dlg.destroy()


class GitManagerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.cryos.GitManager",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        if THEME_CSS.exists():
            p = Gtk.CssProvider()
            p.load_from_path(str(THEME_CSS))
            import gi; gi.require_version("Gdk", "4.0")
            from gi.repository import Gdk
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), p,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        win = GitManagerWindow(self)
        win.present()


def main():
    app = GitManagerApp()
    app.run(sys.argv)

if __name__ == "__main__":
    main()
