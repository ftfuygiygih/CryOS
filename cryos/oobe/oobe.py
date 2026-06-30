#!/usr/bin/env python3
"""
CryOS OOBE  —  oobe/oobe.py
============================
Полный приветственный опыт первого запуска:
  1. Слайд-шоу из 10 PNG (assets/slideshow/01.png … 10.png)
  2. Создание учётной записи пользователя с sudo
  3. Выбор обоев (assets/wallpapers/w01.png, w02.png, w03.png)
  4. Итоговый экран «Готово»

Маскот: Коната — синий SVG-силуэт во всех заголовках.
Стиль: белый фон, тёмно-синие акценты, минимализм 90-х.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio, GdkPixbuf
import subprocess, sys, os, hashlib, json, threading, time, grp
from pathlib import Path

# ── Пути ─────────────────────────────────────────────────────────
CRYOS_ROOT   = Path(__file__).parent.parent
ASSETS       = CRYOS_ROOT / "assets"
SLIDESHOW_DIR= ASSETS / "slideshow"
WALLPAPER_DIR= ASSETS / "wallpapers"
CONFIG_DIR   = Path.home() / ".config" / "cryos"
OOBE_FLAG    = CONFIG_DIR / ".oobe_done"
WALLPAPER_CFG= CONFIG_DIR / "wallpaper.conf"
USER_CFG     = CONFIG_DIR / "user.json"
THEME_CSS    = CRYOS_ROOT / "system" / "theme" / "gtk.css"

# ── SVG маскот Коната ─────────────────────────────────────────────
KONATA_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 130" width="60" height="100">
  <circle cx="40" cy="20" r="15" fill="#000080"/>
  <path d="M25 17 Q8 28 6 75 Q11 77 13 72 Q15 52 20 40 Z" fill="#000080"/>
  <path d="M55 17 Q72 28 74 75 Q69 77 67 72 Q65 52 60 40 Z" fill="#000080"/>
  <path d="M25 19 Q4 8 3 34 Q8 36 10 31 Q14 19 23 23 Z" fill="#000080"/>
  <rect x="27" y="34" width="26" height="30" rx="4" fill="#000080"/>
  <rect x="14" y="36" width="13" height="9" rx="4" fill="#000080"/>
  <rect x="53" y="36" width="13" height="9" rx="4" fill="#000080"/>
  <path d="M27 64 L21 100 L31 100 L40 82 L49 100 L59 100 L53 64 Z" fill="#000080"/>
  <text x="60" y="13" font-size="11" fill="#1084D0">&#9733;</text>
  <text x="3"  y="13" font-size="7"  fill="#1084D0">&#10022;</text>
  <circle cx="35" cy="18" r="2" fill="white"/>
  <circle cx="45" cy="18" r="2" fill="white"/>
</svg>""".encode("utf-8")


# ── Вспомогательные функции ───────────────────────────────────────
def load_css():
    if THEME_CSS.exists():
        p = Gtk.CssProvider()
        p.load_from_path(str(THEME_CSS))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), p,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

def make_konata(width=52, height=86):
    """Создаёт виджет Gtk.Picture с SVG-силуэтом Конаты."""
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
    tmp.write(KONATA_SVG)
    tmp.close()
    pic = Gtk.Picture()
    pic.set_filename(tmp.name)
    pic.set_content_fit(Gtk.ContentFit.CONTAIN)
    pic.set_size_request(width, height)
    GLib.timeout_add(8000, lambda: os.unlink(tmp.name) or False)
    return pic

def make_header(title: str, subtitle: str = "") -> Gtk.Box:
    """Синяя шапка с Конатой."""
    bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    bar.add_css_class("cry-oobe-header")
    bar.set_size_request(-1, 80)

    konata = make_konata()
    konata.set_margin_start(12)
    konata.set_margin_end(12)
    konata.set_margin_top(6)
    konata.set_margin_bottom(6)
    bar.append(konata)

    sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
    sep.set_margin_top(12)
    sep.set_margin_bottom(12)
    sep.set_margin_end(14)
    bar.append(sep)

    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    texts.set_valign(Gtk.Align.CENTER)

    t = Gtk.Label()
    t.set_markup(f'<span foreground="white" font="15" weight="bold">{title}</span>')
    t.set_halign(Gtk.Align.START)
    texts.append(t)

    if subtitle:
        s = Gtk.Label()
        s.set_markup(f'<span foreground="#9EC8FF" font="10">{subtitle}</span>')
        s.set_halign(Gtk.Align.START)
        texts.append(s)

    bar.append(texts)
    return bar

def progress_dots(current_id: str, ids: list[str]) -> Gtk.Box:
    box = Gtk.Box(spacing=6)
    box.set_hexpand(True)
    for sid in ids:
        lbl = Gtk.Label()
        if sid == current_id:
            lbl.set_markup('<span foreground="#000080" font="14">●</span>')
        else:
            lbl.set_markup('<span foreground="#AAAAAA" font="14">○</span>')
        box.append(lbl)
    return box


# ════════════════════════════════════════════════════════════════════
# ЭТАП 1 — Слайд-шоу (10 PNG)
# ════════════════════════════════════════════════════════════════════
class SlideshowWindow(Gtk.ApplicationWindow):
    """
    Полноэкранное слайд-шоу из файлов assets/slideshow/01.png … 10.png.
    Автопереход каждые 5 сек, кнопки «Назад» / «Далее» / «Пропустить».
    """
    TOTAL = 10
    INTERVAL_MS = 5000

    def __init__(self, app, on_done):
        super().__init__(application=app, title="CryOS — Добро пожаловать")
        self.on_done = on_done
        self.current = 0
        self._timer_id = None
        self.set_default_size(900, 620)
        self.set_resizable(False)
        self._build()
        self._show_slide(0)

    def _build(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Изображение слайда
        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.set_vexpand(True)
        self.picture.set_hexpand(True)
        self.picture.add_css_class("cry-oobe-bg")
        root.append(self.picture)

        # Fallback-label если нет PNG
        self.fallback = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.fallback.set_vexpand(True)
        self.fallback.set_halign(Gtk.Align.CENTER)
        self.fallback.set_valign(Gtk.Align.CENTER)
        self.fallback.set_visible(False)
        self.slide_num_lbl = Gtk.Label()
        self.slide_num_lbl.set_markup('<span font="48" foreground="#000080">★</span>')
        self.slide_title_lbl = Gtk.Label()
        self.fallback.append(self.slide_num_lbl)
        self.fallback.append(self.slide_title_lbl)
        root.append(self.fallback)

        sep = Gtk.Separator()
        root.append(sep)

        # Нижняя панель навигации
        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        nav.set_margin_top(10)
        nav.set_margin_bottom(10)
        nav.set_margin_start(20)
        nav.set_margin_end(20)

        skip_btn = Gtk.Button(label="Пропустить")
        skip_btn.connect("clicked", lambda b: self.on_done())
        nav.append(skip_btn)

        # Прогресс-бар
        self.progress = Gtk.ProgressBar()
        self.progress.set_hexpand(True)
        self.progress.set_valign(Gtk.Align.CENTER)
        nav.append(self.progress)

        # Счётчик
        self.counter_lbl = Gtk.Label()
        nav.append(self.counter_lbl)

        self.back_btn = Gtk.Button(label="◀ Назад")
        self.back_btn.connect("clicked", self._on_back)
        nav.append(self.back_btn)

        self.next_btn = Gtk.Button(label="Далее ▶")
        self.next_btn.add_css_class("suggested-action")
        self.next_btn.connect("clicked", self._on_next)
        nav.append(self.next_btn)

        root.append(nav)
        self.set_child(root)

    def _show_slide(self, index: int):
        self.current = max(0, min(index, self.TOTAL - 1))

        # Пробуем загрузить PNG
        png_path = SLIDESHOW_DIR / f"{self.current + 1:02d}.png"
        if png_path.exists():
            self.picture.set_filename(str(png_path))
            self.picture.set_visible(True)
            self.fallback.set_visible(False)
        else:
            # Красивый fallback с номером слайда и Конатой
            self.picture.set_visible(False)
            self.fallback.set_visible(True)
            titles = [
                "Добро пожаловать в CryOS",
                "Быстро и легко",
                "Ваш рабочий стол",
                "Файловый менеджер",
                "Git Manager",
                "Утилита диска",
                "Установка приложений",
                "Секретная папка",
                "Маскот — Коната",
                "Готово к работе",
            ]
            t = titles[self.current] if self.current < len(titles) else f"Слайд {self.current+1}"
            self.slide_num_lbl.set_markup(
                f'<span font="64" foreground="#000080">{self.current+1:02d}</span>'
            )
            self.slide_title_lbl.set_markup(
                f'<span font="18" foreground="#000080">{t}</span>'
            )

        # Счётчик и прогресс
        self.counter_lbl.set_text(f"{self.current + 1} / {self.TOTAL}")
        self.progress.set_fraction((self.current + 1) / self.TOTAL)

        # Кнопки
        self.back_btn.set_sensitive(self.current > 0)
        is_last = (self.current == self.TOTAL - 1)
        self.next_btn.set_label("Начать настройку ▶" if is_last else "Далее ▶")
        if is_last:
            self.next_btn.add_css_class("suggested-action")

        # Таймер автоперехода
        if self._timer_id:
            GLib.source_remove(self._timer_id)
        if not is_last:
            self._timer_id = GLib.timeout_add(self.INTERVAL_MS, self._auto_next)

    def _auto_next(self):
        if self.current < self.TOTAL - 1:
            self._show_slide(self.current + 1)
        return False  # не повторять

    def _on_next(self, *_):
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
        if self.current < self.TOTAL - 1:
            self._show_slide(self.current + 1)
        else:
            self.on_done()

    def _on_back(self, *_):
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
        if self.current > 0:
            self._show_slide(self.current - 1)


# ════════════════════════════════════════════════════════════════════
# ЭТАП 2 — Создание пользователя
# ════════════════════════════════════════════════════════════════════
class UserSetupWindow(Gtk.ApplicationWindow):
    """
    Полноценная форма создания пользователя:
    - Логин, полное имя, пароль (×2)
    - Автоматически добавляется в sudo/wheel
    - Настройка автологина
    - Конфиг сохраняется в ~/.config/cryos/user.json
    """
    PAGE_IDS = ["user", "wallpaper", "done"]

    def __init__(self, app, on_done):
        super().__init__(application=app, title="CryOS — Настройка системы")
        self.on_done = on_done
        self.set_default_size(640, 500)
        self.set_resizable(False)
        self._created_user = None
        self._chosen_wallpaper = None
        self._build()

    def _build(self):
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        self._stack.set_transition_duration(220)

        self._stack.add_named(self._page_user(),      "user")
        self._stack.add_named(self._page_wallpaper(), "wallpaper")
        self._stack.add_named(self._page_done(),      "done")

        self.set_child(self._stack)
        self._stack.set_visible_child_name("user")

    # ── Страница 1: Пользователь ─────────────────────────────────
    def _page_user(self) -> Gtk.Box:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.append(make_header("Создание учётной записи",
                                "Настройте своего первого пользователя CryOS"))

        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        form.set_margin_top(24)
        form.set_margin_bottom(8)
        form.set_margin_start(48)
        form.set_margin_end(48)

        # Поля формы
        form.append(self._lbl("Имя пользователя <small>(только a-z, 0-9, _)</small>"))
        self._user_entry = Gtk.Entry()
        self._user_entry.set_placeholder_text("cryuser")
        self._user_entry.set_max_length(32)
        form.append(self._user_entry)

        form.append(self._lbl("Полное имя (отображаемое)"))
        self._fullname_entry = Gtk.Entry()
        self._fullname_entry.set_placeholder_text("Иванов Иван")
        form.append(self._fullname_entry)

        form.append(self._lbl("Пароль"))
        self._pw1_entry = Gtk.Entry()
        self._pw1_entry.set_visibility(False)
        self._pw1_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        form.append(self._pw1_entry)

        form.append(self._lbl("Повторите пароль"))
        self._pw2_entry = Gtk.Entry()
        self._pw2_entry.set_visibility(False)
        self._pw2_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        form.append(self._pw2_entry)

        # Переключатели
        opts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        opts.set_margin_top(8)

        self._sudo_chk = Gtk.CheckButton(label="Выдать права администратора (sudo)")
        self._sudo_chk.set_active(True)
        opts.append(self._sudo_chk)

        self._autologin_chk = Gtk.CheckButton(label="Автоматический вход (без пароля при старте)")
        self._autologin_chk.set_active(True)
        opts.append(self._autologin_chk)

        form.append(opts)

        # Индикатор силы пароля
        pw_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pw_box.set_margin_top(4)
        self._pw_strength_bar = Gtk.LevelBar()
        self._pw_strength_bar.set_min_value(0)
        self._pw_strength_bar.set_max_value(4)
        self._pw_strength_bar.set_hexpand(True)
        self._pw_strength_lbl = Gtk.Label(label="")
        pw_box.append(Gtk.Label(label="Надёжность:"))
        pw_box.append(self._pw_strength_bar)
        pw_box.append(self._pw_strength_lbl)
        form.append(pw_box)

        self._pw1_entry.connect("changed", self._on_pw_changed)
        self._pw2_entry.connect("changed", self._on_pw_changed)

        # Статус-метка
        self._user_status = Gtk.Label(label="")
        self._user_status.set_halign(Gtk.Align.START)
        form.append(self._user_status)

        root.append(form)

        # Нижняя навигация
        root.append(self._nav_bar("user", back=False,
                                  next_label="Далее →",
                                  next_cb=self._on_user_next))
        return root

    def _on_pw_changed(self, *_):
        pw = self._pw1_entry.get_text()
        score = self._pw_score(pw)
        self._pw_strength_bar.set_value(score)
        labels = ["", "Слабый", "Средний", "Хороший", "Сильный"]
        self._pw_strength_lbl.set_text(labels[score])

    def _pw_score(self, pw: str) -> int:
        if len(pw) < 4: return 0
        s = 0
        if len(pw) >= 8:   s += 1
        if any(c.isupper() for c in pw): s += 1
        if any(c.isdigit() for c in pw): s += 1
        if any(c in "!@#$%^&*_-+=?<>" for c in pw): s += 1
        return s

    def _on_user_next(self, *_):
        username = self._user_entry.get_text().strip()
        fullname = self._fullname_entry.get_text().strip()
        pw1 = self._pw1_entry.get_text()
        pw2 = self._pw2_entry.get_text()

        # Валидация
        import re
        if not re.match(r'^[a-z][a-z0-9_]{1,31}$', username):
            self._set_status("⚠ Логин: только строчные латинские буквы, цифры и _, от 2 символов", "red")
            return
        if len(pw1) < 4:
            self._set_status("⚠ Пароль слишком короткий (минимум 4 символа)", "red")
            return
        if pw1 != pw2:
            self._set_status("⚠ Пароли не совпадают", "red")
            return

        self._set_status("", "")

        # Сохраняем данные
        self._created_user = {
            "username": username,
            "fullname": fullname or username,
            "password": pw1,
            "sudo":     self._sudo_chk.get_active(),
            "autologin":self._autologin_chk.get_active(),
        }

        # Запускаем реальное создание пользователя в фоне
        self._set_status("⏳ Создание пользователя...", "blue")
        threading.Thread(target=self._do_create_user, daemon=True).start()

    def _do_create_user(self):
        u = self._created_user
        errors = []

        # Сохраняем конфиг OOBE
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = {
            "username": u["username"],
            "fullname": u["fullname"],
            "pw_hash":  hashlib.sha256(u["password"].encode()).hexdigest(),
            "sudo":     u["sudo"],
            "autologin":u["autologin"],
        }
        USER_CFG.write_text(json.dumps(cfg, indent=2))

        # Пробуем создать системного пользователя (если есть root)
        if os.geteuid() == 0:
            errors = self._create_system_user(u)
        else:
            # Не root — попробуем через pkexec
            script = CRYOS_ROOT / "system" / "auth" / "setup_user.py"
            if script.exists():
                result = subprocess.run(
                    ["pkexec", "python3", str(script), "--from-config"],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode != 0:
                    errors.append(f"pkexec: {result.stderr.strip()}")

        GLib.idle_add(self._user_created, errors)

    def _create_system_user(self, u: dict) -> list:
        errs = []
        username = u["username"]

        # Создаём пользователя
        groups = "audio,video,plugdev,input,netdev,cdrom,dialout"
        if u["sudo"]:
            groups += ",sudo"

        r = subprocess.run(
            ["useradd", "-m", "-s", "/bin/bash",
             "-c", u["fullname"],
             "-G", groups, username],
            capture_output=True, text=True
        )
        if r.returncode != 0 and "already exists" not in r.stderr:
            errs.append(f"useradd: {r.stderr.strip()}")
            return errs

        # Устанавливаем пароль
        proc = subprocess.Popen(["chpasswd"], stdin=subprocess.PIPE, capture_output=True)
        proc.communicate(f"{username}:{u['password']}".encode())

        # sudoers
        if u["sudo"]:
            sudoers = Path(f"/etc/sudoers.d/cryos-{username}")
            try:
                sudoers.write_text(
                    f"# CryOS auto-generated\n"
                    f"{username} ALL=(ALL:ALL) ALL\n"
                    f"{username} ALL=(ALL) NOPASSWD: /usr/bin/parted,/usr/sbin/mkfs.*,"
                    f"/usr/bin/flatpak\n"
                )
                sudoers.chmod(0o440)
            except Exception as e:
                errs.append(f"sudoers: {e}")

        # Автологин LightDM
        if u["autologin"]:
            self._setup_autologin(username)

        # .xinitrc для пользователя
        xinitrc_src = CRYOS_ROOT / "system" / "init" / "xinitrc"
        user_home = Path(f"/home/{username}")
        if xinitrc_src.exists() and user_home.exists():
            import shutil
            shutil.copy2(xinitrc_src, user_home / ".xinitrc")
            (user_home / ".xinitrc").chmod(0o755)
            subprocess.run(["chown", f"{username}:{username}",
                            str(user_home / ".xinitrc")])

        # ~/.config/cryos для нового пользователя
        new_cfg = user_home / ".config" / "cryos"
        new_cfg.mkdir(parents=True, exist_ok=True)
        subprocess.run(["chown", "-R", f"{username}:{username}", str(new_cfg)])

        return errs

    def _setup_autologin(self, username: str):
        # LightDM
        ldm = Path("/etc/lightdm/lightdm.conf")
        if ldm.parent.exists():
            content = (
                "[Seat:*]\n"
                f"autologin-user={username}\n"
                "autologin-user-timeout=0\n"
                "user-session=cryos\n"
            )
            try: ldm.write_text(content)
            except: pass

        # GDM3
        gdm = Path("/etc/gdm3/daemon.conf")
        if gdm.exists():
            try:
                text = gdm.read_text()
                if "AutomaticLogin" not in text:
                    text = text.replace(
                        "[daemon]",
                        f"[daemon]\nAutomaticLoginEnable=true\nAutomaticLogin={username}"
                    )
                    gdm.write_text(text)
            except: pass

    def _user_created(self, errors: list):
        if errors:
            msg = "⚠ Конфиг сохранён, но системный аккаунт создан с ошибками:\n" + "\n".join(errors[:3])
            self._set_status(msg, "orange")
            # Всё равно продолжаем — пользователь мог уже существовать
            GLib.timeout_add(2000, lambda: self._goto("wallpaper") or False)
        else:
            self._set_status("✅ Пользователь создан!", "green")
            GLib.timeout_add(800, lambda: self._goto("wallpaper") or False)

    def _set_status(self, msg: str, color: str):
        colors = {"red": "#CC0000", "green": "#007700",
                  "blue": "#000080", "orange": "#BB6600", "": "#000000"}
        c = colors.get(color, "#000000")
        self._user_status.set_markup(f'<span foreground="{c}">{msg}</span>')

    # ── Страница 2: Выбор обоев ──────────────────────────────────
    def _page_wallpaper(self) -> Gtk.Box:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.append(make_header("Выбор обоев рабочего стола",
                                "Выберите один из трёх вариантов"))

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_vexpand(True)
        content.set_margin_top(20)
        content.set_margin_bottom(8)
        content.set_margin_start(32)
        content.set_margin_end(32)

        wall_lbl = Gtk.Label()
        wall_lbl.set_markup('<span foreground="#000080">Нажмите на обои, чтобы выбрать их:</span>')
        wall_lbl.set_halign(Gtk.Align.START)
        content.append(wall_lbl)

        # Три превью в ряд
        grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        grid.set_halign(Gtk.Align.CENTER)
        grid.set_vexpand(True)
        grid.set_valign(Gtk.Align.CENTER)

        self._wallpaper_btns = []
        self._chosen_wallpaper = "w01.png"  # по умолчанию

        for i, name in enumerate(["w01.png", "w02.png", "w03.png"], 1):
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            vbox.set_halign(Gtk.Align.CENTER)

            btn = Gtk.Button()
            btn.set_size_request(220, 140)
            btn.set_has_frame(True)
            btn.set_tooltip_text(f"Обои {i}")

            wall_path = WALLPAPER_DIR / name
            if wall_path.exists():
                pic = Gtk.Picture()
                pic.set_filename(str(wall_path))
                pic.set_content_fit(Gtk.ContentFit.COVER)
                pic.set_size_request(216, 136)
                btn.set_child(pic)
            else:
                # Placeholder если файл не положен
                placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                placeholder.set_halign(Gtk.Align.CENTER)
                placeholder.set_valign(Gtk.Align.CENTER)
                emoji_map = {1: "🖼", 2: "🎨", 3: "✨"}
                ico = Gtk.Label()
                ico.set_markup(f'<span font="36">{emoji_map[i]}</span>')
                lbl_ph = Gtk.Label()
                lbl_ph.set_markup(f'<span foreground="#888888" font="10">{name}\n(не загружен)</span>')
                lbl_ph.set_justify(Gtk.Justification.CENTER)
                placeholder.append(ico)
                placeholder.append(lbl_ph)
                btn.set_child(placeholder)

            btn.connect("clicked", self._on_wallpaper_click, name)
            self._wallpaper_btns.append((name, btn))

            lbl = Gtk.Label()
            lbl.set_markup(f'<b>Обои {i}</b>')
            vbox.append(btn)
            vbox.append(lbl)
            grid.append(vbox)

        content.append(grid)

        self._wall_status = Gtk.Label(label="Выбрано: w01.png")
        self._wall_status.set_halign(Gtk.Align.CENTER)
        content.append(self._wall_status)

        # Отмечаем первую по умолчанию
        self._highlight_wall("w01.png")

        root.append(content)
        root.append(self._nav_bar("wallpaper", back=True,
                                  back_cb=lambda: self._goto("user"),
                                  next_label="Далее →",
                                  next_cb=lambda *_: self._save_wallpaper()))
        return root

    def _on_wallpaper_click(self, btn, name: str):
        self._chosen_wallpaper = name
        self._highlight_wall(name)
        self._wall_status.set_text(f"Выбрано: {name}")

    def _highlight_wall(self, chosen: str):
        for name, btn in self._wallpaper_btns:
            ctx = btn.get_style_context()
            if name == chosen:
                ctx.add_class("suggested-action")
            else:
                ctx.remove_class("suggested-action")

    def _save_wallpaper(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        WALLPAPER_CFG.write_text(
            json.dumps({"wallpaper": self._chosen_wallpaper or "w01.png"}, indent=2)
        )
        # Применяем обои немедленно через xsetroot или feh
        wall_path = WALLPAPER_DIR / (self._chosen_wallpaper or "w01.png")
        if wall_path.exists():
            for cmd in [["feh", "--bg-scale", str(wall_path)],
                        ["nitrogen", "--set-scaled", str(wall_path)]]:
                try:
                    subprocess.Popen(cmd)
                    break
                except FileNotFoundError:
                    continue
        self._goto("done")

    # ── Страница 3: Готово ───────────────────────────────────────
    def _page_done(self) -> Gtk.Box:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.append(make_header("Всё готово!", "CryOS настроена и готова к работе"))

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_vexpand(True)
        content.set_halign(Gtk.Align.CENTER)
        content.set_valign(Gtk.Align.CENTER)
        content.set_margin_top(32)
        content.set_margin_bottom(32)
        content.set_margin_start(48)
        content.set_margin_end(48)

        # Большая Коната по центру
        big_konata = make_konata(80, 130)
        big_konata.set_halign(Gtk.Align.CENTER)
        content.append(big_konata)

        msg = Gtk.Label()
        msg.set_markup(
            '<span font="14" weight="bold" foreground="#000080">CryOS настроена!</span>\n\n'
            '<span font="11">'
            'На рабочем столе вы найдёте все приложения.\n\n'
            '<b>Cry</b> → меню в нижнем левом углу\n'
            '<b>ПКМ на рабочем столе</b> → смена обоев\n'
            '<b>📁 Файлы</b> → файловый менеджер\n'
            '<b>🌿 Git</b> → управление репозиториями\n'
            '</span>'
        )
        msg.set_justify(Gtk.Justification.CENTER)
        msg.set_halign(Gtk.Align.CENTER)
        content.append(msg)

        root.append(content)

        # Финальная кнопка
        btn_box = Gtk.Box(spacing=8)
        btn_box.set_halign(Gtk.Align.END)
        btn_box.set_margin_top(8)
        btn_box.set_margin_bottom(16)
        btn_box.set_margin_end(24)

        finish_btn = Gtk.Button(label="Начать работу ✓")
        finish_btn.add_css_class("suggested-action")
        finish_btn.set_size_request(180, 36)
        finish_btn.connect("clicked", lambda b: self.on_done())
        btn_box.append(finish_btn)
        root.append(btn_box)
        return root

    # ── Универсальная навигационная полоса ───────────────────────
    def _nav_bar(self, page_id: str, back=True, next_label="Далее →",
                 back_cb=None, next_cb=None) -> Gtk.Box:
        sep = Gtk.Separator()

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.append(sep)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.set_margin_top(10)
        bar.set_margin_bottom(12)
        bar.set_margin_start(24)
        bar.set_margin_end(24)

        dots = progress_dots(page_id, self.PAGE_IDS)
        bar.append(dots)

        if back:
            back_btn = Gtk.Button(label="◀ Назад")
            back_btn.connect("clicked", lambda b: back_cb() if back_cb else None)
            bar.append(back_btn)

        next_btn = Gtk.Button(label=next_label)
        next_btn.add_css_class("suggested-action")
        next_btn.connect("clicked", next_cb if next_cb else lambda b: None)
        bar.append(next_btn)

        outer.append(bar)
        return outer

    def _goto(self, page_id: str):
        self._stack.set_visible_child_name(page_id)

    @staticmethod
    def _lbl(markup: str) -> Gtk.Label:
        l = Gtk.Label()
        l.set_markup(markup)
        l.set_halign(Gtk.Align.START)
        l.set_margin_top(4)
        return l


# ════════════════════════════════════════════════════════════════════
# Главное приложение OOBE
# ════════════════════════════════════════════════════════════════════
class OOBEApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="org.cryos.OOBE",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )
        self._slideshow_win = None
        self._setup_win = None

    def do_activate(self):
        if OOBE_FLAG.exists():
            self.quit()
            return

        load_css()

        # Фаза 1: слайд-шоу
        self._slideshow_win = SlideshowWindow(self, self._after_slideshow)
        self._slideshow_win.present()

    def _after_slideshow(self):
        """После слайд-шоу открываем настройку пользователя."""
        if self._slideshow_win:
            self._slideshow_win.close()
            self._slideshow_win = None

        self._setup_win = UserSetupWindow(self, self._finish)
        self._setup_win.present()

    def _finish(self):
        """Завершение OOBE — записываем флаг и выходим."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        OOBE_FLAG.write_text("done\n")
        if self._setup_win:
            self._setup_win.close()
        self.quit()


def main():
    app = OOBEApp()
    sys.exit(app.run(sys.argv))

if __name__ == "__main__":
    main()
