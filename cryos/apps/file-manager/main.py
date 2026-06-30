#!/usr/bin/env python3
"""
CryOS File Manager  —  apps/file-manager/main.py
=================================================
Полный файловый менеджер:

1. Двухпанельный режим (Total Commander style)
2. Превью изображений (боковая панель)
3. Поиск файлов (встроенный, рекурсивный)
4. ПКМ-меню (контекстное меню на файле/папке)
5. Drag & Drop (перетаскивание между панелями)
6. Закладки (быстрый доступ, редактируемые)
7. Архивация (zip/tar.gz — создание и распаковка)
8. Свойства файла (размер, дата, права, владелец)

Секретная папка:
- 3 корневых папки: Документы, Загрузки, [???]
- Защита паролем, 2 попытки -> безвозвратное уничтожение
- Смена пароля через кнопку в тулбаре
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GLib, Gio, GdkPixbuf

import os, shutil, hashlib, json, subprocess, sys, threading
import zipfile, tarfile, stat, fnmatch
from pathlib import Path
from datetime import datetime

# Paths
CONFIG_DIR    = Path.home() / ".config" / "cryos"
SECRET_CONFIG = CONFIG_DIR / "secret_folder.json"
BOOKMARKS_CFG = CONFIG_DIR / "fm_bookmarks.json"
THEME_CSS     = Path(__file__).parent.parent.parent / "system" / "theme" / "gtk.css"

IMAGE_EXTS   = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".svg"}
ARCHIVE_EXTS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz"}

ROOTS = {
    "Документы": Path.home() / "Documents",
    "Загрузки":  Path.home() / "Downloads",
    "???":       None,
}


def load_css():
    if THEME_CSS.exists():
        p = Gtk.CssProvider()
        p.load_from_path(str(THEME_CSS))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), p,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def format_size(n: int) -> str:
    for unit in ["Б","КБ","МБ","ГБ","ТБ"]:
        if n < 1024: return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ПБ"


def format_perms(mode: int) -> str:
    s = ""
    for r, w, x in [(stat.S_IRUSR,stat.S_IWUSR,stat.S_IXUSR),
                    (stat.S_IRGRP,stat.S_IWGRP,stat.S_IXGRP),
                    (stat.S_IROTH,stat.S_IWOTH,stat.S_IXOTH)]:
        s += ("r" if mode & r else "-") + ("w" if mode & w else "-") + ("x" if mode & x else "-")
    return s


def get_icon(path: Path) -> str:
    if path.is_dir(): return "📁"
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:   return "🖼"
    if ext in ARCHIVE_EXTS: return "📦"
    if ext in {".py",".js",".ts",".c",".cpp",".h",".rs",".go"}: return "📜"
    if ext in {".sh",".bash",".zsh"}: return "⚙"
    if ext in {".mp3",".ogg",".wav",".flac",".m4a"}: return "🎵"
    if ext in {".mp4",".avi",".mkv",".mov"}: return "🎬"
    if ext in {".pdf"}: return "📕"
    if ext in {".doc",".docx",".odt"}: return "📝"
    return "📄"


# ================================================================
# SECRET FOLDER MANAGER
# ================================================================
class SecretFolderManager:
    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.cfg = self._load()
        self._session_blocked = False  # True после уничтожения в этой сессии

    def _load(self) -> dict:
        if SECRET_CONFIG.exists():
            try: return json.loads(SECRET_CONFIG.read_text())
            except: pass
        return {"hash": None, "path": None, "attempts": 0, "destroyed": False}

    def _save(self):
        SECRET_CONFIG.write_text(json.dumps(self.cfg, indent=2))

    @property
    def is_destroyed(self) -> bool:
        return self.cfg["destroyed"] or self._session_blocked

    @property
    def is_setup(self) -> bool:
        return self.cfg["hash"] is not None and not self.is_destroyed

    def setup(self, password: str, path: str):
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        self.cfg = {"hash": self._hash(password), "path": str(p),
                    "attempts": 0, "destroyed": False}
        self._session_blocked = False
        self._save()

    def change_password(self, old_pw: str, new_pw: str) -> bool:
        if self._hash(old_pw) != self.cfg.get("hash"):
            return False
        self.cfg["hash"] = self._hash(new_pw)
        self._save()
        return True

    def verify(self, password: str) -> bool:
        if self.is_destroyed: return False
        if self._hash(password) == self.cfg["hash"]:
            self.cfg["attempts"] = 0
            self._save()
            return True
        self.cfg["attempts"] += 1
        self._save()
        if self.cfg["attempts"] >= 2:
            self._destroy()
        return False

    def remaining_attempts(self) -> int:
        return max(0, 2 - self.cfg.get("attempts", 0))

    def get_path(self) -> Path:
        return Path(self.cfg["path"])

    def _hash(self, pw: str) -> str:
        return hashlib.sha256(pw.encode()).hexdigest()

    def _destroy(self):
        try:
            if self.cfg["path"] and Path(self.cfg["path"]).exists():
                shutil.rmtree(self.cfg["path"])
        except: pass
        self.cfg.update({"destroyed": True, "hash": None, "path": None})
        self._session_blocked = True
        self._save()


secret_mgr = SecretFolderManager()


# ================================================================
# DIALOGS: Secret folder
# ================================================================
class PasswordDialog(Gtk.Dialog):
    def __init__(self, parent, remaining: int):
        super().__init__(title="Секретная папка", transient_for=parent, modal=True)
        self.add_button("Отмена", Gtk.ResponseType.CANCEL)
        self.add_button("Войти", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        box = self.get_content_area()
        box.set_spacing(10)
        box.set_margin_top(16); box.set_margin_bottom(16)
        box.set_margin_start(24); box.set_margin_end(24)
        lbl = Gtk.Label()
        lbl.set_markup(
            f'<b>Осталось попыток: {remaining}</b>\n'
            '<span foreground="#CC0000" size="small">'
            '2 неверных попытки = папка уничтожается навсегда</span>')
        lbl.set_justify(Gtk.Justification.CENTER)
        box.append(lbl)
        self.entry = Gtk.Entry()
        self.entry.set_visibility(False)
        self.entry.set_placeholder_text("Пароль")
        self.entry.connect("activate", lambda e: self.response(Gtk.ResponseType.OK))
        box.append(self.entry)
    def get_password(self): return self.entry.get_text()


class SetupSecretDialog(Gtk.Dialog):
    def __init__(self, parent):
        super().__init__(title="Создать секретную папку", transient_for=parent, modal=True)
        self.add_button("Отмена", Gtk.ResponseType.CANCEL)
        self.add_button("Создать", Gtk.ResponseType.OK)
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(16); box.set_margin_bottom(16)
        box.set_margin_start(24); box.set_margin_end(24)
        box.append(Gtk.Label(label="Придумайте пароль:"))
        self.pw1 = Gtk.Entry(); self.pw1.set_visibility(False)
        self.pw1.set_placeholder_text("Пароль")
        box.append(self.pw1)
        box.append(Gtk.Label(label="Повторите:"))
        self.pw2 = Gtk.Entry(); self.pw2.set_visibility(False)
        self.pw2.set_placeholder_text("Ещё раз")
        box.append(self.pw2)
        warn = Gtk.Label()
        warn.set_markup('<span foreground="#CC0000" size="small">'
                        'Запомните пароль — восстановление невозможно!</span>')
        box.append(warn)
    def get_passwords(self): return self.pw1.get_text(), self.pw2.get_text()


class ChangePasswordDialog(Gtk.Dialog):
    def __init__(self, parent):
        super().__init__(title="Сменить пароль", transient_for=parent, modal=True)
        self.add_button("Отмена", Gtk.ResponseType.CANCEL)
        self.add_button("Изменить", Gtk.ResponseType.OK)
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(16); box.set_margin_bottom(16)
        box.set_margin_start(24); box.set_margin_end(24)
        entries = [("Текущий пароль:", "_old", "Старый"),
                   ("Новый пароль:", "_new1", "Новый"),
                   ("Повторите:", "_new2", "Ещё раз")]
        for lbl, attr, ph in entries:
            box.append(Gtk.Label(label=lbl))
            e = Gtk.Entry(); e.set_visibility(False); e.set_placeholder_text(ph)
            setattr(self, attr, e); box.append(e)
    def get_values(self): return self._old.get_text(), self._new1.get_text(), self._new2.get_text()


# ================================================================
# DIALOG: Properties
# ================================================================
class PropertiesDialog(Gtk.Dialog):
    def __init__(self, parent, path: Path):
        super().__init__(title=f"Свойства: {path.name}",
                         transient_for=parent, modal=True)
        self.add_button("Закрыть", Gtk.ResponseType.CLOSE)
        self.set_default_size(380, -1)
        box = self.get_content_area()
        box.set_spacing(0)
        box.set_margin_top(16); box.set_margin_bottom(16)
        box.set_margin_start(20); box.set_margin_end(20)

        def row(label, value):
            hb = Gtk.Box(spacing=8); hb.set_margin_bottom(6)
            l = Gtk.Label(); l.set_markup(f"<b>{label}</b>")
            l.set_width_chars(14); l.set_halign(Gtk.Align.START)
            v = Gtk.Label(label=value); v.set_halign(Gtk.Align.START)
            v.set_selectable(True); v.set_wrap(True)
            hb.append(l); hb.append(v); box.append(hb)

        try:
            st = path.stat()
            row("Имя:", path.name)
            row("Тип:", "Папка" if path.is_dir() else f"Файл ({path.suffix or '—'})")
            row("Путь:", str(path.parent))
            if path.is_dir():
                sl = Gtk.Label(label="считаем...")
                sl.set_halign(Gtk.Align.START)
                hb = Gtk.Box(spacing=8); hb.set_margin_bottom(6)
                l = Gtk.Label(); l.set_markup("<b>Размер:</b>")
                l.set_width_chars(14); l.set_halign(Gtk.Align.START)
                hb.append(l); hb.append(sl); box.append(hb)
                def calc():
                    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
                    GLib.idle_add(sl.set_text, format_size(total))
                threading.Thread(target=calc, daemon=True).start()
            else:
                row("Размер:", format_size(st.st_size))
            row("Изменён:", datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M:%S"))
            row("Создан:",  datetime.fromtimestamp(st.st_ctime).strftime("%d.%m.%Y %H:%M:%S"))
            row("Права:",   format_perms(st.st_mode))
            import pwd as _pwd, grp as _grp
            try:
                row("Владелец:", f"{_pwd.getpwuid(st.st_uid).pw_name} / {_grp.getgrgid(st.st_gid).gr_name}")
            except: row("UID/GID:", f"{st.st_uid} / {st.st_gid}")

            sep = Gtk.Separator(); sep.set_margin_top(8); sep.set_margin_bottom(6)
            box.append(sep)
            perms_lbl = Gtk.Label(); perms_lbl.set_markup("<b>Права доступа:</b>")
            perms_lbl.set_halign(Gtk.Align.START); box.append(perms_lbl)
            for flag, label in [(stat.S_IRUSR,"Чтение (владелец)"),
                                 (stat.S_IWUSR,"Запись (владелец)"),
                                 (stat.S_IXUSR,"Выполнение (владелец)")]:
                chk = Gtk.CheckButton(label=label)
                chk.set_active(bool(st.st_mode & flag))
                chk._flag = flag; chk._path = path
                chk.connect("toggled", self._perm_toggle)
                box.append(chk)
        except Exception as e:
            box.append(Gtk.Label(label=f"Ошибка: {e}"))

    def _perm_toggle(self, chk):
        try:
            p = chk._path; mode = p.stat().st_mode
            p.chmod(mode | chk._flag if chk.get_active() else mode & ~chk._flag)
        except: pass


# ================================================================
# DIALOG: Search
# ================================================================
class SearchDialog(Gtk.Dialog):
    def __init__(self, parent, start_path: Path):
        super().__init__(title="Поиск файлов", transient_for=parent, modal=True)
        self.add_button("Закрыть", Gtk.ResponseType.CLOSE)
        self.set_default_size(560, 420)
        self._start = start_path
        self._running = False
        self._results: list[Path] = []

        box = self.get_content_area()
        box.set_spacing(6)
        box.set_margin_top(12); box.set_margin_bottom(12)
        box.set_margin_start(16); box.set_margin_end(16)

        sb = Gtk.Box(spacing=6)
        self._entry = Gtk.Entry()
        self._entry.set_placeholder_text("Имя файла (* = любые символы, ? = один)")
        self._entry.set_hexpand(True)
        self._entry.connect("activate", self._on_search)
        sb.append(self._entry)
        self._go_btn = Gtk.Button(label="Найти")
        self._go_btn.add_css_class("suggested-action")
        self._go_btn.connect("clicked", self._on_search)
        sb.append(self._go_btn)
        box.append(sb)

        opts = Gtk.Box(spacing=16)
        self._case_chk = Gtk.CheckButton(label="Учитывать регистр")
        self._dirs_chk = Gtk.CheckButton(label="Искать в папках")
        self._dirs_chk.set_active(True)
        opts.append(self._case_chk); opts.append(self._dirs_chk)
        box.append(opts)

        self._bar = Gtk.ProgressBar(); self._bar.set_pulse_step(0.06)
        self._bar.set_visible(False); box.append(self._bar)

        self._status = Gtk.Label(label="Введите запрос и нажмите «Найти»")
        self._status.set_halign(Gtk.Align.START); box.append(self._status)

        scroll = Gtk.ScrolledWindow(); scroll.set_vexpand(True)
        self._store = Gtk.StringList()
        lv = Gtk.ListView()
        lv.set_model(Gtk.SingleSelection.new(self._store))
        fac = Gtk.SignalListItemFactory()
        fac.connect("setup", self._fac_setup)
        fac.connect("bind",  self._fac_bind)
        lv.set_factory(fac)
        lv.connect("activate", lambda lv, pos: self._open_result(pos))
        scroll.set_child(lv); box.append(scroll)

    def _fac_setup(self, f, item):
        hb = Gtk.Box(spacing=8); hb.set_margin_top(2); hb.set_margin_bottom(2)
        hb.append(Gtk.Label()); hb.append(Gtk.Label()); hb.append(Gtk.Label())
        item.set_child(hb)

    def _fac_bind(self, f, item):
        hb = item.get_child()
        ico = hb.get_first_child()
        nm  = ico.get_next_sibling()
        pt  = nm.get_next_sibling()
        pos = item.get_position()
        if pos < len(self._results):
            p = self._results[pos]
            ico.set_text(get_icon(p))
            nm.set_markup(f"<b>{p.name}</b>")
            nm.set_hexpand(True); nm.set_halign(Gtk.Align.START)
            pt.set_text(str(p.parent)); pt.add_css_class("dim-label")

    def _open_result(self, pos: int):
        if pos < len(self._results):
            try: subprocess.Popen(["xdg-open", str(self._results[pos])])
            except: pass

    def _on_search(self, *_):
        q = self._entry.get_text().strip()
        if not q or self._running: return
        self._results.clear()
        while self._store.get_n_items(): self._store.remove(0)
        self._running = True
        self._go_btn.set_label("Стоп")
        self._go_btn.disconnect_by_func(self._on_search)
        self._go_btn.connect("clicked", self._stop)
        self._bar.set_visible(True)
        self._status.set_text("Поиск...")
        threading.Thread(target=self._worker, args=(q,), daemon=True).start()
        GLib.timeout_add(80, self._pulse)

    def _stop(self, *_): self._running = False

    def _pulse(self):
        if self._running: self._bar.pulse(); return True
        return False

    def _worker(self, q: str):
        case = self._case_chk.get_active()
        dirs = self._dirs_chk.get_active()
        pat = q if case else q.lower()
        found = 0
        try:
            for root, subdirs, files in os.walk(self._start):
                if not self._running: break
                for name in (subdirs + files if dirs else files):
                    if not self._running: break
                    cmp = name if case else name.lower()
                    if ("*" in pat or "?" in pat) and fnmatch.fnmatch(cmp, pat):
                        hit = True
                    elif "*" not in pat and "?" not in pat and pat in cmp:
                        hit = True
                    else:
                        hit = False
                    if hit:
                        p = Path(root) / name
                        self._results.append(p)
                        GLib.idle_add(self._store.append, name)
                        found += 1
                        if found % 20 == 0:
                            GLib.idle_add(self._status.set_text, f"Найдено: {found}...")
        except: pass
        GLib.idle_add(self._done, found)

    def _done(self, count: int):
        self._running = False
        self._bar.set_visible(False)
        self._status.set_text(f"Найдено: {count} объектов")
        self._go_btn.set_label("Найти")
        self._go_btn.disconnect_by_func(self._stop)
        self._go_btn.connect("clicked", self._on_search)


# ================================================================
# DIALOG: Archive
# ================================================================
class ArchiveDialog(Gtk.Dialog):
    def __init__(self, parent, path: Path, mode="create"):
        title = "Создать архив" if mode == "create" else "Распаковать"
        super().__init__(title=title, transient_for=parent, modal=True)
        self.add_button("Отмена", Gtk.ResponseType.CANCEL)
        self.add_button("OK", Gtk.ResponseType.OK)
        self.mode = mode
        box = self.get_content_area()
        box.set_spacing(8); box.set_margin_top(16); box.set_margin_bottom(16)
        box.set_margin_start(20); box.set_margin_end(20)
        if mode == "create":
            box.append(Gtk.Label(label=f"Архивировать: {path.name}"))
            box.append(Gtk.Label(label="Имя архива:"))
            self._name = Gtk.Entry(text=path.name); box.append(self._name)
            box.append(Gtk.Label(label="Формат:"))
            self._fmt = Gtk.DropDown.new_from_strings(["zip","tar.gz","tar.bz2"])
            box.append(self._fmt)
        else:
            box.append(Gtk.Label(label=f"Распаковать: {path.name}"))
            box.append(Gtk.Label(label="Куда:"))
            self._dest = Gtk.Entry(text=str(path.parent)); box.append(self._dest)

    def get_create_params(self):
        fmts = ["zip","tar.gz","tar.bz2"]
        return self._name.get_text(), fmts[self._fmt.get_selected()]

    def get_extract_dest(self): return Path(self._dest.get_text())


# ================================================================
# PREVIEW PANEL
# ================================================================
class PreviewPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_size_request(176, -1)
        hdr = Gtk.Label(); hdr.set_markup("<b>Превью</b>")
        hdr.set_margin_top(6); hdr.set_margin_bottom(6)
        self.append(hdr); self.append(Gtk.Separator())

        self._pic = Gtk.Picture()
        self._pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        self._pic.set_size_request(172, 130); self._pic.set_margin_top(6)
        self.append(self._pic)

        self._info = Gtk.Label(label="")
        self._info.set_wrap(True); self._info.set_halign(Gtk.Align.START)
        self._info.set_margin_top(8); self._info.set_margin_start(6)
        self._info.set_margin_end(6); self._info.set_xalign(0)
        self.append(self._info)

        self._none = Gtk.Label()
        self._none.set_markup('<span foreground="#999999">Нет превью</span>')
        self._none.set_vexpand(True); self._none.set_valign(Gtk.Align.CENTER)
        self._none.set_halign(Gtk.Align.CENTER)
        self.append(self._none)

    def show_file(self, path: Path | None):
        if not path or not path.exists():
            self._pic.set_visible(False); self._none.set_visible(True)
            self._info.set_text(""); return
        try:
            st = path.stat()
            if path.is_dir():
                self._info.set_text(f"Папка\n{path.name}")
            else:
                self._info.set_text(
                    f"{path.name}\n{format_size(st.st_size)}\n"
                    f"{datetime.fromtimestamp(st.st_mtime).strftime('%d.%m.%Y %H:%M')}")
        except: self._info.set_text(path.name)

        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            try:
                self._pic.set_filename(str(path))
                self._pic.set_visible(True); self._none.set_visible(False)
                return
            except: pass
        self._pic.set_visible(False); self._none.set_visible(True)


# ================================================================
# BOOKMARKS
# ================================================================
class BookmarkManager:
    def __init__(self):
        self._items: list[dict] = []
        self._load()

    def _load(self):
        if BOOKMARKS_CFG.exists():
            try: self._items = json.loads(BOOKMARKS_CFG.read_text()); return
            except: pass
        self._items = [
            {"name": "Домашняя",  "path": str(Path.home())},
            {"name": "Документы", "path": str(Path.home() / "Documents")},
            {"name": "Загрузки",  "path": str(Path.home() / "Downloads")},
            {"name": "/ Корень",  "path": "/"},
        ]

    def _save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        BOOKMARKS_CFG.write_text(json.dumps(self._items, indent=2))

    def all(self): return list(self._items)

    def add(self, name: str, path: str):
        if any(b["path"] == path for b in self._items): return
        self._items.append({"name": name, "path": path}); self._save()

    def remove(self, path: str):
        self._items = [b for b in self._items if b["path"] != path]; self._save()


bookmarks = BookmarkManager()


# ================================================================
# FILE PANEL
# ================================================================
class FilePanel(Gtk.Box):
    def __init__(self, window, preview: PreviewPanel,
                 get_other=None, label=""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window = window
        self.preview = preview
        self.get_other = get_other
        self.current_path = Path.home()
        self._clip_path: Path | None = None
        self._clip_mode = ""
        self._history: list[Path] = []
        self._hist_pos = -1
        self._files: list[Path] = []
        self._build(label)

    def _build(self, label: str):
        if label:
            hdr = Gtk.Label(); hdr.set_markup(f"<b> {label} </b>")
            hdr.add_css_class("cry-oobe-header"); hdr.set_size_request(-1, 20)
            self.append(hdr)

        # Адресная строка
        ab = Gtk.Box(spacing=3)
        ab.set_margin_top(3); ab.set_margin_bottom(3)
        ab.set_margin_start(3); ab.set_margin_end(3)
        self._back_btn = Gtk.Button(label="◀"); self._back_btn.set_sensitive(False)
        self._back_btn.connect("clicked", self._on_back); ab.append(self._back_btn)
        self._fwd_btn  = Gtk.Button(label="▶"); self._fwd_btn.set_sensitive(False)
        self._fwd_btn.connect("clicked", self._on_fwd); ab.append(self._fwd_btn)
        up_btn = Gtk.Button(label="▲"); up_btn.connect("clicked", lambda b: self.go_up())
        ab.append(up_btn)
        self.addr = Gtk.Entry(); self.addr.set_hexpand(True)
        self.addr.connect("activate", self._on_addr); ab.append(self.addr)
        self.append(ab)

        # Тулбар
        tb = Gtk.Box(spacing=2); tb.set_margin_bottom(2); tb.set_margin_start(2)
        for icon, tip, cb in [
            ("📁+","Новая папка",     self._new_folder),
            ("📋", "Копировать",      self._do_copy),
            ("✂",  "Вырезать",       self._do_cut),
            ("📌", "Вставить",       self._do_paste),
            ("🗑", "Удалить",        self._delete),
            ("✏",  "Переименовать", self._rename),
            ("🔍", "Поиск",         self._search),
            ("📦", "Архивировать",  self._archive),
            ("★",  "В закладки",   self._add_bookmark),
        ]:
            btn = Gtk.Button(label=icon); btn.set_tooltip_text(tip)
            btn.connect("clicked", cb); tb.append(btn)
        self.append(tb)

        # Список
        scroll = Gtk.ScrolledWindow(); scroll.set_vexpand(True)
        self._store = Gtk.StringList()
        self._lv = Gtk.ListView()
        self._sel = Gtk.SingleSelection.new(self._store)
        self._lv.set_model(self._sel)
        self._lv.connect("activate", self._on_activate)
        self._sel.connect("selection-changed", lambda m, p, n: self._on_sel_changed())
        fac = Gtk.SignalListItemFactory()
        fac.connect("setup", self._fac_setup)
        fac.connect("bind",  self._fac_bind)
        self._lv.set_factory(fac)

        # Drag source
        drag = Gtk.DragSource()
        drag.set_actions(Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drag.connect("prepare",    self._drag_prepare)
        drag.connect("drag-begin", self._drag_begin)
        self._lv.add_controller(drag)

        # Drop target
        drop = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drop.connect("drop",  self._on_drop)
        drop.connect("enter", lambda t, x, y: Gdk.DragAction.COPY)
        self._lv.add_controller(drop)

        # ПКМ
        pkm = Gtk.GestureClick(); pkm.set_button(3)
        pkm.connect("pressed", self._on_pkm)
        self._lv.add_controller(pkm)

        scroll.set_child(self._lv); self.append(scroll)

        self.status = Gtk.Label(label="")
        self.status.add_css_class("statusbar")
        self.status.set_halign(Gtk.Align.START)
        self.status.set_margin_start(4)
        self.append(self.status)

        self.navigate_to(Path.home())

    def _fac_setup(self, f, item):
        hb = Gtk.Box(spacing=6); hb.set_margin_top(2); hb.set_margin_bottom(2)
        hb.append(Gtk.Label()); hb.append(Gtk.Label()); hb.append(Gtk.Label())
        item.set_child(hb)

    def _fac_bind(self, f, item):
        hb = item.get_child()
        ico = hb.get_first_child()
        nm  = ico.get_next_sibling()
        sz  = nm.get_next_sibling()
        pos = item.get_position()
        if pos >= len(self._files): return
        p = self._files[pos]
        ico.set_text(get_icon(p)); nm.set_hexpand(True); nm.set_halign(Gtk.Align.START)
        nm.set_text(p.name)
        if not p.is_dir():
            try: sz.set_text(format_size(p.stat().st_size))
            except: sz.set_text("")
        else: sz.set_text("")
        sz.add_css_class("dim-label")

    def navigate_to(self, path: Path, hist=True):
        self.current_path = path
        self.addr.set_text(str(path))
        if hist:
            self._history = self._history[:self._hist_pos+1]
            self._history.append(path)
            self._hist_pos = len(self._history)-1
        self._back_btn.set_sensitive(self._hist_pos > 0)
        self._fwd_btn.set_sensitive(self._hist_pos < len(self._history)-1)
        self._refresh()

    def _refresh(self):
        self._files.clear()
        while self._store.get_n_items(): self._store.remove(0)
        try:
            items = sorted(self.current_path.iterdir(),
                           key=lambda p: (not p.is_dir(), p.name.lower()))
            for p in items:
                self._files.append(p); self._store.append(p.name)
            self.status.set_text(f"{len(items)} объектов  |  {self.current_path}")
        except PermissionError:
            self.status.set_text("Нет доступа")

    def selected(self) -> Path | None:
        pos = self._sel.get_selected()
        if pos == Gtk.INVALID_LIST_POSITION or pos >= len(self._files): return None
        return self._files[pos]

    def _on_sel_changed(self):
        self.preview.show_file(self.selected())

    def _on_activate(self, lv, pos):
        if pos >= len(self._files): return
        p = self._files[pos]
        if p.is_dir(): self.navigate_to(p)
        elif p.suffix.lower() in ARCHIVE_EXTS: self._extract_archive(p)
        else:
            try: subprocess.Popen(["xdg-open", str(p)], start_new_session=True)
            except: pass

    def _on_addr(self, *_):
        p = Path(self.addr.get_text())
        if p.is_dir(): self.navigate_to(p)

    def _on_back(self, *_):
        if self._hist_pos > 0:
            self._hist_pos -= 1
            self.navigate_to(self._history[self._hist_pos], hist=False)

    def _on_fwd(self, *_):
        if self._hist_pos < len(self._history)-1:
            self._hist_pos += 1
            self.navigate_to(self._history[self._hist_pos], hist=False)

    def go_up(self):
        p = self.current_path.parent
        if p != self.current_path: self.navigate_to(p)

    # Drag
    def _drag_prepare(self, src, x, y):
        sel = self.selected()
        if sel is None: return None
        return Gdk.ContentProvider.new_for_value(Gio.File.new_for_path(str(sel)))

    def _drag_begin(self, src, drag):
        sel = self.selected()
        if sel:
            icon = Gtk.DragIcon.get_for_drag(drag)
            icon.set_child(Gtk.Label(label=f"{get_icon(sel)} {sel.name}"))

    def _on_drop(self, target, value, x, y):
        if not isinstance(value, Gio.File): return False
        src = Path(value.get_path())
        dst = self.current_path / src.name
        if src == dst or src.parent == self.current_path: return False
        try:
            if src.is_dir(): shutil.copytree(src, dst)
            else: shutil.copy2(src, dst)
            self._refresh()
            other = self.get_other() if self.get_other else None
            if other: other._refresh()
            return True
        except Exception as e:
            self._err(str(e)); return False

    # ПКМ
    def _on_pkm(self, gesture, n, x, y):
        sel = self.selected()
        pop = Gtk.Popover(); pop.set_parent(self._lv)
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        items: list = []
        if sel:
            items += [
                (f"Открыть {get_icon(sel)} {sel.name}", lambda s=sel: self._open(s)),
                None,
                ("📋 Копировать", self._do_copy),
                ("✂ Вырезать",   self._do_cut),
            ]
            if self._clip_path:
                items.append(("📌 Вставить", self._do_paste))
            items += [
                None,
                ("✏ Переименовать", self._rename),
                ("🗑 Удалить",      self._delete),
                None,
                ("★ В закладки",   self._add_bookmark),
                ("ℹ Свойства",     self._properties),
            ]
            if sel.is_file():
                items.append(("📦 Архивировать", self._archive))
            if sel.suffix.lower() in ARCHIVE_EXTS:
                items.append(("📂 Распаковать", lambda s=sel: self._extract_archive(s)))
        else:
            if self._clip_path:
                items.append(("📌 Вставить", self._do_paste))
            items += [
                ("📁 Новая папка", self._new_folder),
                ("🔍 Поиск",      self._search),
            ]

        for item in items:
            if item is None:
                vb.append(Gtk.Separator())
            else:
                lbl, cb = item
                btn = Gtk.Button(label=lbl)
                btn.set_has_frame(False); btn.add_css_class("flat")
                btn.set_halign(Gtk.Align.FILL)
                def make(c=cb, p=pop):
                    def h(b): p.popdown(); c()
                    return h
                btn.connect("clicked", make())
                vb.append(btn)

        pop.set_child(vb); pop.set_has_arrow(False)
        r = Gdk.Rectangle(); r.x = int(x); r.y = int(y); r.width = 1; r.height = 1
        pop.set_pointing_to(r); pop.popup()

    def _open(self, path: Path):
        if path.is_dir(): self.navigate_to(path)
        else:
            try: subprocess.Popen(["xdg-open", str(path)], start_new_session=True)
            except: pass

    # Операции
    def _new_folder(self, *_):
        d = Gtk.Dialog(title="Новая папка", transient_for=self.window, modal=True)
        d.add_button("Отмена", Gtk.ResponseType.CANCEL)
        d.add_button("Создать", Gtk.ResponseType.OK)
        e = Gtk.Entry(placeholder_text="Название")
        box = d.get_content_area()
        box.set_margin_top(12); box.set_margin_bottom(12)
        box.set_margin_start(16); box.set_margin_end(16)
        box.append(e); e.connect("activate", lambda _: d.response(Gtk.ResponseType.OK))
        if d.run() == Gtk.ResponseType.OK:
            nm = e.get_text().strip()
            if nm:
                try: (self.current_path / nm).mkdir(exist_ok=True); self._refresh()
                except Exception as ex: self._err(str(ex))
        d.destroy()

    def _do_copy(self, *_):
        sel = self.selected()
        if sel: self._clip_path = sel; self._clip_mode = "copy"
        self.status.set_text(f"Скопировано: {sel.name if sel else ''}")

    def _do_cut(self, *_):
        sel = self.selected()
        if sel: self._clip_path = sel; self._clip_mode = "cut"
        self.status.set_text(f"Вырезано: {sel.name if sel else ''}")

    def _do_paste(self, *_):
        if not self._clip_path or not self._clip_path.exists(): return
        dst = self.current_path / self._clip_path.name
        try:
            if self._clip_mode == "copy":
                if self._clip_path.is_dir(): shutil.copytree(self._clip_path, dst)
                else: shutil.copy2(self._clip_path, dst)
            else:
                shutil.move(str(self._clip_path), dst)
                self._clip_path = None; self._clip_mode = ""
                other = self.get_other() if self.get_other else None
                if other: other._refresh()
            self._refresh()
        except Exception as ex: self._err(str(ex))

    def _delete(self, *_):
        sel = self.selected()
        if not sel: return
        d = Gtk.MessageDialog(transient_for=self.window, modal=True,
                              message_type=Gtk.MessageType.WARNING,
                              buttons=Gtk.ButtonsType.YES_NO,
                              text=f"Удалить «{sel.name}»?")
        d.format_secondary_text("Это действие необратимо.")
        if d.run() == Gtk.ResponseType.YES:
            try:
                shutil.rmtree(sel) if sel.is_dir() else sel.unlink()
                self._refresh()
            except Exception as ex: self._err(str(ex))
        d.destroy()

    def _rename(self, *_):
        sel = self.selected()
        if not sel: return
        d = Gtk.Dialog(title="Переименовать", transient_for=self.window, modal=True)
        d.add_button("Отмена", Gtk.ResponseType.CANCEL)
        d.add_button("OK", Gtk.ResponseType.OK)
        e = Gtk.Entry(text=sel.name)
        box = d.get_content_area()
        box.set_margin_top(12); box.set_margin_bottom(12)
        box.set_margin_start(16); box.set_margin_end(16)
        box.append(e); e.connect("activate", lambda _: d.response(Gtk.ResponseType.OK))
        if d.run() == Gtk.ResponseType.OK:
            nm = e.get_text().strip()
            if nm and nm != sel.name:
                try: sel.rename(self.current_path / nm); self._refresh()
                except Exception as ex: self._err(str(ex))
        d.destroy()

    def _search(self, *_):
        d = SearchDialog(self.window, self.current_path); d.run(); d.destroy()

    def _properties(self, *_):
        sel = self.selected()
        if not sel: return
        d = PropertiesDialog(self.window, sel); d.run(); d.destroy()

    def _add_bookmark(self, *_):
        sel = self.selected()
        p = (sel if sel and sel.is_dir() else self.current_path)
        bookmarks.add(p.name, str(p))
        self.status.set_text(f"Добавлено в закладки: {p.name}")
        if hasattr(self.window, "refresh_bookmarks"):
            self.window.refresh_bookmarks()

    def _archive(self, *_):
        sel = self.selected()
        if not sel: return
        d = ArchiveDialog(self.window, sel, "create")
        if d.run() == Gtk.ResponseType.OK:
            name, fmt = d.get_create_params()
            dst = self.current_path / f"{name}.{fmt}"
            threading.Thread(target=self._do_archive, args=(sel, dst, fmt), daemon=True).start()
        d.destroy()

    def _do_archive(self, src: Path, dst: Path, fmt: str):
        try:
            if fmt == "zip":
                with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
                    if src.is_dir():
                        for f in src.rglob("*"): zf.write(f, f.relative_to(src.parent))
                    else: zf.write(src, src.name)
            else:
                mode = "w:gz" if fmt == "tar.gz" else "w:bz2"
                with tarfile.open(dst, mode) as tf: tf.add(src, arcname=src.name)
            GLib.idle_add(self._refresh)
            GLib.idle_add(self.status.set_text, f"Архив создан: {dst.name}")
        except Exception as e:
            GLib.idle_add(self._err, str(e))

    def _extract_archive(self, path: Path | None = None):
        p = path or self.selected()
        if not p: return
        d = ArchiveDialog(self.window, p, "extract")
        if d.run() == Gtk.ResponseType.OK:
            dest = d.get_extract_dest()
            threading.Thread(target=self._do_extract, args=(p, dest), daemon=True).start()
        d.destroy()

    def _do_extract(self, src: Path, dest: Path):
        try:
            dest.mkdir(parents=True, exist_ok=True)
            if src.suffix == ".zip": 
                with zipfile.ZipFile(src) as zf: zf.extractall(dest)
            else:
                with tarfile.open(src) as tf: tf.extractall(dest)
            GLib.idle_add(self._refresh)
            GLib.idle_add(self.status.set_text, f"Распаковано в: {dest}")
        except Exception as e:
            GLib.idle_add(self._err, str(e))

    def _err(self, msg: str):
        d = Gtk.MessageDialog(transient_for=self.window, modal=True,
                              message_type=Gtk.MessageType.ERROR,
                              buttons=Gtk.ButtonsType.OK, text="Ошибка")
        d.format_secondary_text(msg); d.run(); d.destroy()


# ================================================================
# SIDEBAR
# ================================================================
class Sidebar(Gtk.Box):
    def __init__(self, get_active):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_size_request(152, -1)
        self.get_active = get_active
        self._bm_box = None
        self._build()

    def _build(self):
        lbl = Gtk.Label(); lbl.set_markup('<b> Папки </b>')
        lbl.set_margin_top(6); lbl.set_margin_bottom(4); lbl.set_margin_start(6)
        lbl.set_halign(Gtk.Align.START); self.append(lbl)

        for name, path in ROOTS.items():
            icon = "📁" if path else "🔒"
            btn = Gtk.Button(label=f"{icon} {name}")
            btn.set_has_frame(False); btn.add_css_class("flat")
            btn.set_halign(Gtk.Align.FILL)
            btn.connect("clicked", self._root_click, name, path)
            self.append(btn)

        sep = Gtk.Separator(); sep.set_margin_top(6); sep.set_margin_bottom(6)
        self.append(sep)
        lbl2 = Gtk.Label(); lbl2.set_markup('<b> Закладки </b>')
        lbl2.set_margin_bottom(4); lbl2.set_margin_start(6)
        lbl2.set_halign(Gtk.Align.START); self.append(lbl2)

        self._bm_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.append(self._bm_box)
        self.refresh_bookmarks()

    def refresh_bookmarks(self):
        if not self._bm_box: return
        c = self._bm_box.get_first_child()
        while c:
            n = c.get_next_sibling(); self._bm_box.remove(c); c = n
        for bm in bookmarks.all():
            hb = Gtk.Box(spacing=0)
            btn = Gtk.Button(label=f"📌 {bm['name']}")
            btn.set_has_frame(False); btn.add_css_class("flat")
            btn.set_hexpand(True); btn.set_halign(Gtk.Align.FILL)
            btn.set_tooltip_text(bm["path"])
            _p = bm["path"]
            btn.connect("clicked", lambda b, p=_p: self._nav(p))
            del_btn = Gtk.Button(label="✕")
            del_btn.set_has_frame(False); del_btn.add_css_class("flat")
            del_btn.set_tooltip_text("Удалить")
            del_btn.connect("clicked", lambda b, p=_p: self._del_bm(p))
            hb.append(btn); hb.append(del_btn)
            self._bm_box.append(hb)

    def _nav(self, path_str: str):
        p = Path(path_str)
        if p.exists(): self.get_active().navigate_to(p)

    def _del_bm(self, path_str: str):
        bookmarks.remove(path_str); self.refresh_bookmarks()

    def _root_click(self, btn, name, path):
        if path is None:
            self._open_secret()
        else:
            path.mkdir(parents=True, exist_ok=True)
            self.get_active().navigate_to(path)

    def _open_secret(self):
        win = self.get_ancestor(Gtk.Window)
        panel = self.get_active()

        if secret_mgr.is_destroyed:
            d = Gtk.MessageDialog(transient_for=win, modal=True,
                                  message_type=Gtk.MessageType.ERROR,
                                  buttons=Gtk.ButtonsType.OK,
                                  text="Секретная папка уничтожена")
            d.format_secondary_text("Исчерпаны попытки входа. Данные удалены навсегда.")
            d.run(); d.destroy(); return

        if not secret_mgr.is_setup:
            dlg = SetupSecretDialog(win)
            if dlg.run() == Gtk.ResponseType.OK:
                pw1, pw2 = dlg.get_passwords()
                if not pw1:
                    self._msg_err(win, "Пароль не может быть пустым")
                elif pw1 != pw2:
                    self._msg_err(win, "Пароли не совпадают")
                else:
                    secret_mgr.setup(pw1, str(Path.home() / ".cryos-secret"))
                    panel.navigate_to(secret_mgr.get_path())
            dlg.destroy(); return

        remaining = secret_mgr.remaining_attempts()
        pd = PasswordDialog(win, remaining)
        resp = pd.run(); pw = pd.get_password(); pd.destroy()
        if resp != Gtk.ResponseType.OK: return

        if secret_mgr.verify(pw):
            panel.navigate_to(secret_mgr.get_path())
        else:
            if secret_mgr.is_destroyed:
                d = Gtk.MessageDialog(transient_for=win, modal=True,
                                      message_type=Gtk.MessageType.ERROR,
                                      buttons=Gtk.ButtonsType.OK,
                                      text="Секретная папка уничтожена")
                d.format_secondary_text("Попытки исчерпаны. Все файлы удалены безвозвратно.")
            else:
                rem = secret_mgr.remaining_attempts()
                d = Gtk.MessageDialog(transient_for=win, modal=True,
                                      message_type=Gtk.MessageType.WARNING,
                                      buttons=Gtk.ButtonsType.OK,
                                      text="Неверный пароль")
                d.format_secondary_text(
                    f"Осталось попыток: {rem}\n"
                    "Следующая ошибка = папка будет уничтожена.")
            d.run(); d.destroy()

    def _msg_err(self, win, text):
        d = Gtk.MessageDialog(transient_for=win, modal=True,
                              message_type=Gtk.MessageType.ERROR,
                              buttons=Gtk.ButtonsType.OK, text=text)
        d.run(); d.destroy()


# ================================================================
# MAIN WINDOW
# ================================================================
class FileManagerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CryOS — Файловый менеджер")
        self.set_default_size(1100, 640)
        self._active = 0  # 0=left, 1=right

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Топ-бар режима и смены пароля
        top = Gtk.Box(spacing=6)
        top.set_margin_top(4); top.set_margin_bottom(4)
        top.set_margin_start(8); top.set_margin_end(8)
        self._dual_btn = Gtk.ToggleButton(label="⧉ Две панели")
        self._dual_btn.set_active(True)
        self._dual_btn.connect("toggled", self._toggle_dual)
        top.append(self._dual_btn)
        chpw = Gtk.Button(label="🔒 Сменить пароль секретной папки")
        chpw.connect("clicked", self._change_secret_pw)
        top.append(chpw)
        root.append(top)
        root.append(Gtk.Separator())

        # Основной layout
        hbox = Gtk.Box(spacing=0)

        # Боковая панель
        self._preview = PreviewPanel()
        self._sidebar = Sidebar(lambda: self._panels[self._active])
        ss = Gtk.ScrolledWindow(); ss.set_size_request(156,-1)
        ss.set_hscrollbar_policy(Gtk.PolicyType.NEVER)
        ss.set_child(self._sidebar)
        hbox.append(ss)
        hbox.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Панели
        self._panel_left  = FilePanel(self, self._preview,
                                      lambda: self._panel_right, "Панель 1")
        self._panel_right = FilePanel(self, self._preview,
                                      lambda: self._panel_left,  "Панель 2")
        self._panels = [self._panel_left, self._panel_right]
        self._panel_right.navigate_to(Path.home() / "Downloads")

        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._paned.set_hexpand(True)
        self._paned.set_position(490)
        self._paned.set_start_child(self._panel_left)
        self._paned.set_end_child(self._panel_right)
        hbox.append(self._paned)

        hbox.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        hbox.append(self._preview)

        root.append(hbox)
        self.set_child(root)

        # Клик для выбора активной панели
        for i, panel in enumerate(self._panels):
            gc = Gtk.GestureClick(); _i = i
            gc.connect("pressed", lambda g, n, x, y, idx=_i: setattr(self, "_active", idx))
            panel.add_controller(gc)

    def _toggle_dual(self, btn):
        if btn.get_active():
            self._panel_right.set_visible(True)
            self._paned.set_position(490)
        else:
            self._panel_right.set_visible(False)
            self._paned.set_position(99999)

    def refresh_bookmarks(self):
        self._sidebar.refresh_bookmarks()

    def _change_secret_pw(self, *_):
        if secret_mgr.is_destroyed:
            d = Gtk.MessageDialog(transient_for=self, modal=True,
                                  message_type=Gtk.MessageType.ERROR,
                                  buttons=Gtk.ButtonsType.OK,
                                  text="Секретная папка уничтожена")
            d.run(); d.destroy(); return
        if not secret_mgr.is_setup:
            d = Gtk.MessageDialog(transient_for=self, modal=True,
                                  message_type=Gtk.MessageType.INFO,
                                  buttons=Gtk.ButtonsType.OK,
                                  text="Сначала создайте секретную папку")
            d.run(); d.destroy(); return
        dlg = ChangePasswordDialog(self)
        if dlg.run() == Gtk.ResponseType.OK:
            old, n1, n2 = dlg.get_values()
            if not n1:
                self._err("Новый пароль не может быть пустым")
            elif n1 != n2:
                self._err("Новые пароли не совпадают")
            elif not secret_mgr.change_password(old, n1):
                self._err("Неверный текущий пароль")
            else:
                d = Gtk.MessageDialog(transient_for=self, modal=True,
                                      message_type=Gtk.MessageType.INFO,
                                      buttons=Gtk.ButtonsType.OK,
                                      text="Пароль изменён")
                d.run(); d.destroy()
        dlg.destroy()

    def _err(self, msg: str):
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.ERROR,
                              buttons=Gtk.ButtonsType.OK, text=msg)
        d.run(); d.destroy()


# ================================================================
# APP
# ================================================================
class FileManagerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.cryos.FileManager",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        load_css()
        win = FileManagerWindow(self)
        win.present()


def main():
    app = FileManagerApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
