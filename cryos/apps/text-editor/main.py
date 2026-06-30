#!/usr/bin/env python3
"""
CryOS Text Editor  —  apps/text-editor/main.py
================================================
Простой редактор в стиле Notepad.
Функции: подсветка синтаксиса (Python/Bash/JSON),
         поиск и замена, нумерация строк,
         открытие/сохранение файлов.
Зависимости: python3-gi, gir1.2-gtksource-5 (опционально)
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio
import sys, re
from pathlib import Path

CRYOS_ROOT = Path(__file__).parent.parent.parent
THEME_CSS  = CRYOS_ROOT / "system" / "theme" / "gtk.css"

# Пробуем GtkSourceView для подсветки
try:
    gi.require_version("GtkSource", "5")
    from gi.repository import GtkSource
    HAVE_SOURCE = True
except (ValueError, ImportError):
    try:
        gi.require_version("GtkSource", "4")
        from gi.repository import GtkSource
        HAVE_SOURCE = True
    except (ValueError, ImportError):
        HAVE_SOURCE = False


# ── Подсветка синтаксиса (fallback без GtkSource) ────────────────
SYNTAX_PATTERNS = {
    "python": [
        (r"\b(def|class|import|from|return|if|elif|else|for|while|"
         r"in|not|and|or|is|None|True|False|pass|break|continue|"
         r"try|except|finally|with|as|raise|lambda|yield|async|await)\b",
         "#000080", True),   # ключевые слова — синий жирный
        (r"#[^\n]*",              "#008000", False),  # комментарии — зелёный
        (r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "#800000", False),  # docstring
        (r'"[^"\n]*"|\'[^\'\n]*\'',  "#800000", False),  # строки — тёмно-красный
        (r"\b\d+\.?\d*\b",           "#800080", False),  # числа — фиолетовый
    ],
    "bash": [
        (r"\b(if|then|else|elif|fi|for|do|done|while|case|esac|"
         r"function|return|exit|echo|source|export|local|shift)\b",
         "#000080", True),
        (r"#[^\n]*",             "#008000", False),
        (r'"[^"\n]*"|\'[^\'\n]*\'', "#800000", False),
        (r"\$\{?\w+\}?",         "#800080", False),
    ],
    "json": [
        (r'"[^"\\]*(?:\\.[^"\\]*)*"\s*:',  "#000080", True),  # ключ
        (r':\s*"[^"\\]*(?:\\.[^"\\]*)*"',  "#800000", False), # строка-значение
        (r"\b(true|false|null)\b",          "#008080", False),
        (r"\b-?\d+\.?\d*([eE][+-]?\d+)?\b","#800080", False),
    ],
}

EXT_TO_LANG = {
    ".py": "python", ".pyw": "python",
    ".sh": "bash", ".bash": "bash",
    ".json": "json",
}


class SyntaxHighlighter:
    """Простая подсветка через Pango markup."""

    def __init__(self, lang: str):
        self.patterns = SYNTAX_PATTERNS.get(lang, [])

    def highlight(self, text: str) -> str:
        """Возвращает текст с pango-разметкой."""
        if not self.patterns:
            return GLib.markup_escape_text(text)
        # Находим все совпадения со всеми паттернами
        matches = []
        for pattern, color, bold in self.patterns:
            for m in re.finditer(pattern, text, re.MULTILINE):
                matches.append((m.start(), m.end(), color, bold))
        matches.sort(key=lambda x: x[0])

        result = []
        pos = 0
        for start, end, color, bold in matches:
            if start < pos:
                continue
            result.append(GLib.markup_escape_text(text[pos:start]))
            chunk = GLib.markup_escape_text(text[start:end])
            tag = f'<span foreground="{color}">'
            if bold:
                tag += "<b>"
            result.append(tag + chunk + ("</b>" if bold else "") + "</span>")
            pos = end
        result.append(GLib.markup_escape_text(text[pos:]))
        return "".join(result)


# ── Диалог поиска и замены ────────────────────────────────────────
class FindReplaceBar(Gtk.Box):
    def __init__(self, editor):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.editor = editor
        self.set_margin_start(4)
        self.set_margin_end(4)
        self.set_margin_top(2)
        self.set_margin_bottom(2)

        Gtk.Label(label="Найти:").set_parent(self)
        self.append(Gtk.Label(label="Найти:"))

        self.find_entry = Gtk.SearchEntry()
        self.find_entry.set_placeholder_text("Текст для поиска…")
        self.find_entry.set_size_request(160, -1)
        self.find_entry.connect("activate", self._find)
        self.append(self.find_entry)

        self.append(Gtk.Label(label="Заменить:"))

        self.replace_entry = Gtk.Entry()
        self.replace_entry.set_placeholder_text("Замена…")
        self.replace_entry.set_size_request(120, -1)
        self.append(self.replace_entry)

        for label, cb in [("▼ Найти", self._find),
                           ("Заменить", self._replace),
                           ("Заменить всё", self._replace_all),
                           ("✕", self._close)]:
            btn = Gtk.Button(label=label)
            btn.connect("clicked", cb)
            self.append(btn)

        self.result_lbl = Gtk.Label(label="")
        self.result_lbl.set_hexpand(True)
        self.append(self.result_lbl)

    def _get_text(self) -> str:
        buf = self.editor.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)

    def _find(self, *_):
        needle = self.find_entry.get_text()
        if not needle:
            return
        text = self._get_text()
        buf  = self.editor.get_buffer()
        cur  = buf.get_iter_at_mark(buf.get_insert())
        pos  = text.find(needle, cur.get_offset())
        if pos < 0:
            pos = text.find(needle)  # wrap
        if pos < 0:
            self.result_lbl.set_text("Не найдено")
            return
        start = buf.get_iter_at_offset(pos)
        end   = buf.get_iter_at_offset(pos + len(needle))
        buf.select_range(start, end)
        self.editor.scroll_to_iter(start, 0.1, False, 0, 0)
        self.result_lbl.set_text("")

    def _replace(self, *_):
        buf = self.editor.get_buffer()
        if buf.get_has_selection():
            buf.delete_selection(True, True)
            buf.insert_at_cursor(self.replace_entry.get_text())
        self._find()

    def _replace_all(self, *_):
        needle = self.find_entry.get_text()
        repl   = self.replace_entry.get_text()
        if not needle:
            return
        buf  = self.editor.get_buffer()
        text = self._get_text()
        new_text = text.replace(needle, repl)
        count = text.count(needle)
        buf.set_text(new_text)
        self.result_lbl.set_text(f"Заменено: {count}")

    def _close(self, *_):
        self.set_visible(False)


# ── Редактор ──────────────────────────────────────────────────────
class EditorWindow(Gtk.ApplicationWindow):
    def __init__(self, app, filepath: Path | None = None):
        super().__init__(application=app)
        self.set_default_size(900, 650)
        self.add_css_class("cry-window")
        self._filepath: Path | None = None
        self._modified = False
        self._lang = ""

        self._build_ui()
        self._setup_shortcuts()

        if filepath and filepath.exists():
            self._open_file(filepath)
        else:
            self._update_title()

    def _build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Меню-бар
        vbox.append(self._build_menubar())

        # Поиск/замена (скрыт по умолчанию)
        if HAVE_SOURCE:
            self.textview = GtkSource.View()
            self.textview.set_show_line_numbers(True)
            self.textview.set_highlight_current_line(True)
            self.textview.set_auto_indent(True)
            self.textview.set_tab_width(4)
            self.textview.set_insert_spaces_instead_of_tabs(True)
            self._buf = self.textview.get_buffer()
            self._buf.connect("changed", self._on_changed)
        else:
            self.textview = Gtk.TextView()
            self.textview.set_monospace(True)
            self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self._buf = self.textview.get_buffer()
            self._buf.connect("changed", self._on_changed)

        self.find_bar = FindReplaceBar(self.textview)
        self.find_bar.set_visible(False)
        vbox.append(self.find_bar)

        # Основная область
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        # Нумерация строк (если нет GtkSource)
        if not HAVE_SOURCE:
            self._line_nums = Gtk.Label()
            self._line_nums.set_markup('<span font="Monospace 10" foreground="#888">1</span>')
            self._line_nums.set_valign(Gtk.Align.START)
            self._line_nums.set_margin_start(4)
            self._line_nums.set_margin_end(8)
            self._line_nums.set_margin_top(4)
            main_box.append(self._line_nums)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        scroll.set_child(self.textview)
        main_box.append(scroll)
        vbox.append(main_box)

        # Статус-бар
        self.status = Gtk.Label(label="Готово")
        self.status.add_css_class("statusbar")
        self.status.set_halign(Gtk.Align.START)
        self.status.set_margin_start(8)
        vbox.append(self.status)

        self.set_child(vbox)

    def _build_menubar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bar.add_css_class("cry-menubar")

        menus = [
            ("Файл", [
                ("Новый         Ctrl+N", self._new),
                ("Открыть…     Ctrl+O", self._open_dialog),
                ("Сохранить    Ctrl+S", self._save),
                ("Сохранить как…", self._save_as),
                (None, None),
                ("Выход", lambda *_: self.close()),
            ]),
            ("Правка", [
                ("Отменить      Ctrl+Z", lambda *_: self._buf.undo() if HAVE_SOURCE else None),
                ("Повторить   Ctrl+Y", lambda *_: self._buf.redo() if HAVE_SOURCE else None),
                (None, None),
                ("Найти/Заменить  Ctrl+H", self._toggle_find),
            ]),
            ("Вид", [
                ("Перенос строк", self._toggle_wrap),
            ]),
        ]

        for menu_label, items in menus:
            btn = Gtk.MenuButton(label=menu_label)
            btn.set_has_frame(False)
            btn.add_css_class("flat")
            popover = Gtk.Popover()
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            for label, cb in items:
                if label is None:
                    vbox.append(Gtk.Separator())
                else:
                    item = Gtk.Button(label=label)
                    item.set_has_frame(False)
                    item.add_css_class("flat")
                    item.set_halign(Gtk.Align.FILL)
                    item.connect("clicked", lambda b, c=cb: (popover.popdown(), c()))
                    vbox.append(item)
            popover.set_child(vbox)
            btn.set_popover(popover)
            bar.append(btn)

        # Индикатор языка
        self.lang_btn = Gtk.Button(label="Текст")
        self.lang_btn.set_has_frame(False)
        self.lang_btn.add_css_class("flat")
        self.lang_btn.set_hexpand(True)
        self.lang_btn.set_halign(Gtk.Align.END)
        self.lang_btn.connect("clicked", self._pick_language)
        bar.append(self.lang_btn)

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
        shortcut(Gdk.KEY_n, M.CONTROL_MASK, self._new)
        shortcut(Gdk.KEY_o, M.CONTROL_MASK, self._open_dialog)
        shortcut(Gdk.KEY_s, M.CONTROL_MASK, self._save)
        shortcut(Gdk.KEY_h, M.CONTROL_MASK, self._toggle_find)
        shortcut(Gdk.KEY_f, M.CONTROL_MASK, self._toggle_find)

    # ── Файловые операции ─────────────────────────────────────────

    def _new(self):
        if self._modified:
            if not self._ask_save():
                return
        self._buf.set_text("")
        self._filepath = None
        self._modified = False
        self._set_lang("")
        self._update_title()

    def _open_dialog(self):
        dialog = Gtk.FileDialog()
        dialog.open(self, None, self._on_open_response)

    def _on_open_response(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                self._open_file(Path(file.get_path()))
        except GLib.Error:
            pass

    def _open_file(self, path: Path):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            self._buf.set_text(text)
            self._filepath = path
            self._modified = False
            self._set_lang(EXT_TO_LANG.get(path.suffix.lower(), ""))
            self._update_title()
            self.status.set_text(f"Открыт: {path}")
        except Exception as e:
            self.status.set_text(f"Ошибка: {e}")

    def _save(self):
        if self._filepath:
            self._write(self._filepath)
        else:
            self._save_as()

    def _save_as(self):
        dialog = Gtk.FileDialog()
        dialog.save(self, None, self._on_save_response)

    def _on_save_response(self, dialog, result):
        try:
            file = dialog.save_finish(result)
            if file:
                self._write(Path(file.get_path()))
        except GLib.Error:
            pass

    def _write(self, path: Path):
        buf = self._buf
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        try:
            path.write_text(text, encoding="utf-8")
            self._filepath = path
            self._modified = False
            self._set_lang(EXT_TO_LANG.get(path.suffix.lower(), self._lang))
            self._update_title()
            self.status.set_text(f"Сохранено: {path}")
        except Exception as e:
            self.status.set_text(f"Ошибка сохранения: {e}")

    def _ask_save(self) -> bool:
        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Сохранить изменения?"
        )
        resp = dlg.run()
        dlg.destroy()
        if resp == Gtk.ResponseType.YES:
            self._save()
        return True

    # ── Язык / подсветка ──────────────────────────────────────────

    def _set_lang(self, lang: str):
        self._lang = lang
        self.lang_btn.set_label(lang.capitalize() or "Текст")
        if HAVE_SOURCE and lang:
            mgr = GtkSource.LanguageManager.get_default()
            src_lang = mgr.get_language(lang)
            self._buf.set_language(src_lang)
            self._buf.set_highlight_syntax(True)

    def _pick_language(self, *_):
        langs = ["", "python", "bash", "json"]
        names = ["Текст", "Python", "Bash", "JSON"]
        popover = Gtk.Popover()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        for lang, name in zip(langs, names):
            btn = Gtk.Button(label=name)
            btn.set_has_frame(False)
            btn.add_css_class("flat")
            btn.connect("clicked", lambda b, l=lang: (popover.popdown(), self._set_lang(l)))
            vbox.append(btn)
        popover.set_child(vbox)
        popover.set_parent(self.lang_btn)
        popover.popup()

    # ── Утилиты ───────────────────────────────────────────────────

    def _on_changed(self, buf):
        self._modified = True
        self._update_title()
        if not HAVE_SOURCE:
            self._update_line_numbers(buf)

    def _update_line_numbers(self, buf):
        lines = buf.get_line_count()
        markup = "\n".join(
            f'<span font="Monospace 10" foreground="#888">{i}</span>'
            for i in range(1, lines + 1)
        )
        self._line_nums.set_markup(markup)

    def _update_title(self):
        name = self._filepath.name if self._filepath else "Новый документ"
        mod  = " •" if self._modified else ""
        self.set_title(f"{name}{mod} — CryOS Редактор")

    def _toggle_find(self):
        visible = not self.find_bar.is_visible()
        self.find_bar.set_visible(visible)
        if visible:
            self.find_bar.find_entry.grab_focus()

    def _toggle_wrap(self, *_):
        mode = self.textview.get_wrap_mode()
        if mode == Gtk.WrapMode.NONE:
            self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        else:
            self.textview.set_wrap_mode(Gtk.WrapMode.NONE)


class EditorApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="org.cryos.TextEditor",
            flags=Gio.ApplicationFlags.HANDLES_OPEN
        )
        self.connect("open", self._on_open)

    def do_activate(self):
        self._load_css()
        EditorWindow(self).present()

    def _on_open(self, app, files, n_files, hint):
        self._load_css()
        for f in files:
            EditorWindow(self, filepath=Path(f.get_path())).present()

    def _load_css(self):
        if THEME_CSS.exists():
            p = Gtk.CssProvider()
            p.load_from_path(str(THEME_CSS))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), p,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )


def main():
    app = EditorApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
