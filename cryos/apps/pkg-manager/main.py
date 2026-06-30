#!/usr/bin/env python3
"""
CryOS Package Manager  —  apps/pkg-manager/main.py
====================================================
Поиск в APT + Flatpak одновременно.
Установка / удаление с прогресс-баром.
Категории, история установок.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio
import subprocess, sys, threading, json, time
from pathlib import Path

CRYOS_ROOT = Path(__file__).parent.parent.parent
THEME_CSS  = CRYOS_ROOT / "system" / "theme" / "gtk.css"
HISTORY_FILE = Path.home() / ".config" / "cryos" / "pkg_history.json"

CATEGORIES = {
    "🌐 Интернет":      ["firefox", "chromium", "thunderbird", "transmission"],
    "🎵 Медиа":         ["vlc", "mpv", "gimp", "inkscape", "audacity"],
    "💻 Разработка":    ["code", "git", "python3", "nodejs", "gcc"],
    "📝 Офис":          ["libreoffice", "evince", "okular"],
    "🎮 Игры":          ["steam", "lutris", "dosbox"],
    "⚙ Системные":     ["htop", "neofetch", "curl", "wget", "vim"],
}


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Таймаут"
    except Exception as e:
        return -1, "", str(e)


def apt_search(query: str) -> list[dict]:
    rc, out, _ = run_cmd(["apt-cache", "search", "--names-only", query])
    results = []
    for line in (out or "").splitlines()[:40]:
        if " - " in line:
            name, desc = line.split(" - ", 1)
            results.append({"name": name.strip(), "desc": desc.strip(),
                             "source": "APT", "installed": _apt_installed(name.strip())})
    return results


def _apt_installed(name: str) -> bool:
    rc, out, _ = run_cmd(["dpkg", "-l", name])
    return rc == 0 and "ii" in out


def flatpak_search(query: str) -> list[dict]:
    rc, out, _ = run_cmd(["flatpak", "search", "--columns=name,description,application", query])
    results = []
    for line in (out or "").splitlines()[:20]:
        parts = line.split("\t")
        if len(parts) >= 3:
            results.append({"name": parts[0], "desc": parts[1][:80],
                             "app_id": parts[2], "source": "Flatpak", "installed": False})
    return results


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            pass
    return []


def save_history(history: list[dict]):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history[-100:], indent=2))


class PackageRow(Gtk.Box):
    def __init__(self, pkg: dict, action_cb):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.set_margin_top(4); self.set_margin_bottom(4)
        self.pkg = pkg

        src_badge = Gtk.Label()
        color = "#000080" if pkg["source"] == "APT" else "#800080"
        src_badge.set_markup(
            f'<span background="{color}" foreground="white"'
            f' font="9"> {pkg["source"]} </span>'
        )
        self.append(src_badge)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.set_hexpand(True)

        name_lbl = Gtk.Label()
        name_lbl.set_markup(f'<b>{pkg["name"]}</b>')
        name_lbl.set_halign(Gtk.Align.START)
        info.append(name_lbl)

        desc_lbl = Gtk.Label(label=pkg.get("desc", "")[:80])
        desc_lbl.set_halign(Gtk.Align.START)
        desc_lbl.add_css_class("dim-label")
        info.append(desc_lbl)

        self.append(info)

        if pkg.get("installed"):
            remove_btn = Gtk.Button(label="Удалить")
            remove_btn.add_css_class("destructive-action")
            remove_btn.connect("clicked", lambda *_: action_cb(pkg, "remove"))
            self.append(remove_btn)
        else:
            install_btn = Gtk.Button(label="Установить")
            install_btn.add_css_class("suggested-action")
            install_btn.connect("clicked", lambda *_: action_cb(pkg, "install"))
            self.append(install_btn)


class PkgManagerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CryOS Менеджер пакетов")
        self.set_default_size(760, 560)
        self.add_css_class("cry-window")
        self._history = load_history()

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Поиск
        search_box = Gtk.Box(spacing=8)
        search_box.set_margin_start(8); search_box.set_margin_end(8)
        search_box.set_margin_top(8); search_box.set_margin_bottom(4)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Поиск пакетов (APT + Flatpak)…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("activate", self._do_search)
        search_box.append(self.search_entry)

        search_btn = Gtk.Button(label="🔍 Найти")
        search_btn.add_css_class("suggested-action")
        search_btn.connect("clicked", self._do_search)
        search_box.append(search_btn)

        vbox.append(search_box)

        # Прогресс-бар (скрыт)
        self.progress = Gtk.ProgressBar()
        self.progress.set_visible(False)
        self.progress.set_margin_start(8); self.progress.set_margin_end(8)
        vbox.append(self.progress)

        self.status_lbl = Gtk.Label(label="")
        self.status_lbl.set_halign(Gtk.Align.START)
        self.status_lbl.set_margin_start(8)
        vbox.append(self.status_lbl)

        notebook = Gtk.Notebook()

        # Вкладка результатов
        results_scroll = Gtk.ScrolledWindow()
        results_scroll.set_vexpand(True)
        self._results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._results_box.set_margin_start(8); self._results_box.set_margin_end(8)
        results_scroll.set_child(self._results_box)
        notebook.append_page(results_scroll, Gtk.Label(label="📦 Результаты"))

        # Вкладка категорий
        cat_scroll = Gtk.ScrolledWindow()
        cat_scroll.set_vexpand(True)
        cat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cat_box.set_margin_start(8); cat_box.set_margin_end(8); cat_box.set_margin_top(8)
        for cat_name, pkgs in CATEGORIES.items():
            cat_lbl = Gtk.Label()
            cat_lbl.set_markup(f'<b>{cat_name}</b>')
            cat_lbl.set_halign(Gtk.Align.START)
            cat_box.append(cat_lbl)
            flow = Gtk.FlowBox()
            flow.set_selection_mode(Gtk.SelectionMode.NONE)
            flow.set_max_children_per_line(4)
            for pkg_name in pkgs:
                btn = Gtk.Button(label=pkg_name)
                btn.set_has_frame(False)
                btn.add_css_class("flat")
                btn.connect("clicked", lambda b, n=pkg_name: (
                    self.search_entry.set_text(n), self._do_search()
                ))
                flow.append(btn)
            cat_box.append(flow)
            cat_box.append(Gtk.Separator())
        cat_scroll.set_child(cat_box)
        notebook.append_page(cat_scroll, Gtk.Label(label="🗂 Категории"))

        # Вкладка истории
        hist_scroll = Gtk.ScrolledWindow()
        hist_scroll.set_vexpand(True)
        self._hist_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._hist_box.set_margin_start(8); self._hist_box.set_margin_end(8)
        hist_scroll.set_child(self._hist_box)
        notebook.append_page(hist_scroll, Gtk.Label(label="📜 История"))
        self._refresh_history()

        vbox.append(notebook)
        self.set_child(vbox)

    def _do_search(self, *_):
        query = self.search_entry.get_text().strip()
        if not query:
            return
        self.status_lbl.set_text(f"Поиск «{query}»…")
        self.progress.set_visible(True)
        self.progress.pulse()
        # Очищаем результаты
        child = self._results_box.get_first_child()
        while child:
            next_c = child.get_next_sibling()
            self._results_box.remove(child)
            child = next_c

        def search_thread():
            apt_results = apt_search(query)
            flat_results = flatpak_search(query)
            GLib.idle_add(self._show_results, apt_results + flat_results, query)

        threading.Thread(target=search_thread, daemon=True).start()
        GLib.timeout_add(200, lambda: (self.progress.pulse(), True)
                         if self.progress.is_visible() else False)

    def _show_results(self, results: list[dict], query: str):
        self.progress.set_visible(False)
        if not results:
            self.status_lbl.set_text(f"Ничего не найдено для «{query}»")
            return
        self.status_lbl.set_text(f"Найдено: {len(results)} пакетов")
        for pkg in results:
            row = PackageRow(pkg, self._action)
            self._results_box.append(row)
            self._results_box.append(Gtk.Separator())

    def _action(self, pkg: dict, action: str):
        name = pkg["name"]
        source = pkg["source"]
        verb = "Установка" if action == "install" else "Удаление"
        self.status_lbl.set_text(f"{verb}: {name}…")
        self.progress.set_visible(True)
        self.progress.set_fraction(0)

        def run_thread():
            if source == "APT":
                if action == "install":
                    cmd = ["pkexec", "apt-get", "install", "-y", name]
                else:
                    cmd = ["pkexec", "apt-get", "remove", "-y", name]
            else:  # Flatpak
                app_id = pkg.get("app_id", name)
                if action == "install":
                    cmd = ["flatpak", "install", "-y", "flathub", app_id]
                else:
                    cmd = ["flatpak", "uninstall", "-y", app_id]

            for i in range(10):
                GLib.idle_add(self.progress.set_fraction, (i+1)/10)
                time.sleep(0.3)

            rc, stdout, stderr = run_cmd(cmd)
            GLib.idle_add(self._action_done, pkg, action, rc, stderr)

        threading.Thread(target=run_thread, daemon=True).start()

    def _action_done(self, pkg: dict, action: str, rc: int, err: str):
        self.progress.set_fraction(1.0)
        name = pkg["name"]
        if rc == 0:
            verb = "Установлен" if action == "install" else "Удалён"
            self.status_lbl.set_text(f"✓ {verb}: {name}")
            self._history.insert(0, {
                "name": name, "action": action,
                "source": pkg["source"],
                "time": time.strftime("%Y-%m-%d %H:%M")
            })
            save_history(self._history)
            self._refresh_history()
        else:
            self.status_lbl.set_text(f"✗ Ошибка: {err[:80]}")
        GLib.timeout_add(3000, lambda: (self.progress.set_visible(False), False))

    def _refresh_history(self):
        child = self._hist_box.get_first_child()
        while child:
            next_c = child.get_next_sibling()
            self._hist_box.remove(child)
            child = next_c
        if not self._history:
            self._hist_box.append(Gtk.Label(label="История пуста"))
            return
        for entry in self._history[:50]:
            row = Gtk.Box(spacing=8)
            row.set_margin_top(4); row.set_margin_bottom(4)
            icon = "📥" if entry["action"] == "install" else "🗑"
            row.append(Gtk.Label(label=icon))
            lbl = Gtk.Label()
            lbl.set_markup(
                f'<b>{entry["name"]}</b>  '
                f'<span foreground="#666" size="small">'
                f'{entry["source"]} • {entry.get("time","")}</span>'
            )
            lbl.set_halign(Gtk.Align.START)
            row.append(lbl)
            self._hist_box.append(row)
            self._hist_box.append(Gtk.Separator())


class PkgManagerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.cryos.PkgManager",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        if THEME_CSS.exists():
            p = Gtk.CssProvider(); p.load_from_path(str(THEME_CSS))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        PkgManagerWindow(self).present()


def main():
    PkgManagerApp().run(sys.argv)

if __name__ == "__main__":
    main()
