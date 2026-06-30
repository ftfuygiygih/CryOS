#!/usr/bin/env python3
"""
CryOS Disk Utility  —  apps/disk-utility/main.py
=================================================
Аналог GParted: просмотр, создание, удаление, изменение разделов.
⚠ Перед опасными действиями — предупреждение.
Требует root (запуск через pkexec/sudo).
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gio
import subprocess
import sys
import os
import re
import threading
from pathlib import Path

THEME_CSS = Path(__file__).parent.parent.parent / "system" / "theme" / "gtk.css"


# ── Получение данных о дисках ─────────────────────────────────────
def get_block_devices() -> list[dict]:
    """Возвращает список дисков через lsblk."""
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,LABEL,MODEL"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return []
        data = __import__("json").loads(result.stdout)
        return data.get("blockdevices", [])
    except Exception as e:
        return []


def get_partition_table(device: str) -> str:
    """Возвращает таблицу разделов через parted."""
    try:
        result = subprocess.run(
            ["parted", "-s", f"/dev/{device}", "print"],
            capture_output=True, text=True
        )
        return result.stdout if result.returncode == 0 else result.stderr
    except Exception as e:
        return f"Ошибка: {e}"


def is_root() -> bool:
    return os.geteuid() == 0


# ── Предупреждение перед опасным действием ────────────────────────
def danger_confirm(parent, title: str, msg: str, extra: str = "") -> bool:
    dlg = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.WARNING,
        buttons=Gtk.ButtonsType.NONE,
        text=f"⚠ {title}",
    )
    dlg.add_css_class("cry-warning-dialog")
    dlg.format_secondary_text(
        msg + ("\n\n" + extra if extra else "") +
        "\n\nЭто действие может привести к БЕЗВОЗВРАТНОЙ ПОТЕРЕ ДАННЫХ."
    )
    dlg.add_button("Отмена",       Gtk.ResponseType.CANCEL)
    dlg.add_button("Продолжить ⚠", Gtk.ResponseType.OK)
    resp = dlg.run()
    dlg.destroy()
    return resp == Gtk.ResponseType.OK


# ── Визуализатор диска ────────────────────────────────────────────
class DiskVisualizer(Gtk.DrawingArea):
    """Рисует прямоугольную карту разделов."""

    COLORS = [
        (0.12, 0.47, 0.71),  # синий
        (0.20, 0.63, 0.17),  # зелёный
        (0.89, 0.47, 0.13),  # оранжевый
        (0.55, 0.34, 0.67),  # фиолетовый
        (0.84, 0.15, 0.16),  # красный
    ]

    def __init__(self):
        super().__init__()
        self.partitions = []
        self.total_size = 1
        self.set_content_height(48)
        self.set_draw_func(self._draw)

    def set_device(self, device: dict):
        self.partitions = device.get("children", [])
        self.total_size = max(self._parse_size(device.get("size", "1G")), 1)
        self.queue_draw()

    def _parse_size(self, s: str) -> float:
        s = s.strip().upper()
        try:
            val = float(re.sub(r"[^0-9.]", "", s))
        except ValueError:
            return 1.0
        if "T" in s: return val * 1024
        if "G" in s: return val
        if "M" in s: return val / 1024
        return val

    def _draw(self, area, cr, w, h):
        cr.set_source_rgb(0.9, 0.9, 0.9)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        if not self.partitions:
            cr.set_source_rgb(0.5, 0.5, 0.5)
            cr.rectangle(2, 2, w - 4, h - 4)
            cr.fill()
            return

        x = 2
        available = w - 4
        for i, part in enumerate(self.partitions):
            part_size = self._parse_size(part.get("size", "1G"))
            pw = max(int(available * part_size / self.total_size), 4)
            r, g, b = self.COLORS[i % len(self.COLORS)]
            cr.set_source_rgb(r, g, b)
            cr.rectangle(x, 2, pw - 1, h - 4)
            cr.fill()
            # Метка
            cr.set_source_rgb(1, 1, 1)
            cr.select_font_face("monospace")
            cr.set_font_size(10)
            lbl = part.get("name", "?")
            cr.move_to(x + 4, h / 2 + 4)
            cr.show_text(lbl)
            x += pw


# ── Панель операций ───────────────────────────────────────────────
class OperationsPanel(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.window = window
        self.current_device = None
        self.current_partition = None
        self._build()

    def _build(self):
        lbl = Gtk.Label(label="Операции с разделом")
        lbl.set_markup("<b>Операции с разделом</b>")
        lbl.set_halign(Gtk.Align.START)
        self.append(lbl)

        self.create_btn = Gtk.Button(label="+ Создать раздел")
        self.create_btn.connect("clicked", self._on_create)
        self.append(self.create_btn)

        self.delete_btn = Gtk.Button(label="✗ Удалить раздел")
        self.delete_btn.add_css_class("destructive-action")
        self.delete_btn.connect("clicked", self._on_delete)
        self.append(self.delete_btn)

        self.resize_btn = Gtk.Button(label="↔ Изменить размер")
        self.resize_btn.connect("clicked", self._on_resize)
        self.append(self.resize_btn)

        self.format_btn = Gtk.Button(label="⚡ Форматировать")
        self.format_btn.add_css_class("destructive-action")
        self.format_btn.connect("clicked", self._on_format)
        self.append(self.format_btn)

        sep = Gtk.Separator()
        self.append(sep)

        self.info_lbl = Gtk.Label(label="Выберите устройство и раздел")
        self.info_lbl.set_wrap(True)
        self.info_lbl.set_max_width_chars(28)
        self.append(self.info_lbl)

    def set_device(self, device):
        self.current_device = device
        self.current_partition = None
        self.info_lbl.set_text(f"Устройство: /dev/{device.get('name','?')}\nРазмер: {device.get('size','?')}")

    def set_partition(self, part):
        self.current_partition = part
        name = part.get("name", "?")
        size = part.get("size", "?")
        fs   = part.get("fstype") or "—"
        mp   = part.get("mountpoint") or "не смонтирован"
        self.info_lbl.set_text(f"/dev/{name}\nРазмер: {size}\nФС: {fs}\nТочка: {mp}")

    def _require_root(self):
        if not is_root():
            dlg = Gtk.MessageDialog(
                transient_for=self.window, modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Требуются права root",
            )
            dlg.format_secondary_text(
                "Запустите утилиту диска от имени root:\n"
                "pkexec cryos-disk"
            )
            dlg.run(); dlg.destroy()
            return False
        return True

    def _require_device(self):
        if not self.current_device:
            dlg = Gtk.MessageDialog(
                transient_for=self.window, modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Выберите устройство"
            )
            dlg.run(); dlg.destroy()
            return False
        return True

    def _on_create(self, *_):
        if not self._require_root() or not self._require_device():
            return
        dev = f"/dev/{self.current_device['name']}"
        if not danger_confirm(self.window, "Создание раздела",
                              f"Создать новый раздел на {dev}?",
                              "Убедитесь, что на диске есть свободное место."):
            return
        dlg = Gtk.Dialog(title="Создать раздел", transient_for=self.window, modal=True)
        dlg.add_button("Отмена", Gtk.ResponseType.CANCEL)
        dlg.add_button("Создать", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_spacing(8); box.set_margin_top(12); box.set_margin_bottom(12)
        box.set_margin_start(16); box.set_margin_end(16)
        box.append(Gtk.Label(label="Размер (например: 10G, 500M):"))
        size_entry = Gtk.Entry(placeholder_text="10G")
        box.append(size_entry)
        box.append(Gtk.Label(label="Тип файловой системы:"))
        fs_combo = Gtk.DropDown.new_from_strings(["ext4", "ext3", "fat32", "ntfs", "btrfs", "xfs"])
        box.append(fs_combo)
        if dlg.run() == Gtk.ResponseType.OK:
            size = size_entry.get_text().strip()
            fs_names = ["ext4", "ext3", "fat32", "ntfs", "btrfs", "xfs"]
            fs = fs_names[fs_combo.get_selected()]
            if size:
                self._exec_create(dev, size, fs)
        dlg.destroy()

    def _exec_create(self, dev: str, size: str, fs: str):
        def run():
            cmd = ["parted", "-s", dev, "mkpart", "primary", fs, "0%", size]
            result = subprocess.run(cmd, capture_output=True, text=True)
            GLib.idle_add(self._show_result, result.returncode, result.stdout + result.stderr)
        threading.Thread(target=run, daemon=True).start()

    def _on_delete(self, *_):
        if not self._require_root():
            return
        if not self.current_partition:
            dlg = Gtk.MessageDialog(
                transient_for=self.window, modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Выберите раздел для удаления"
            )
            dlg.run(); dlg.destroy()
            return
        name = self.current_partition.get("name", "?")
        if not danger_confirm(self.window, "Удаление раздела",
                              f"Удалить раздел /dev/{name}?",
                              "ВСЕ ДАННЫЕ НА РАЗДЕЛЕ БУДУТ УНИЧТОЖЕНЫ БЕЗВОЗВРАТНО!"):
            return

        def run():
            # Определяем номер раздела
            num = re.sub(r"[^0-9]", "", name)
            dev_base = re.sub(r"[0-9]", "", f"/dev/{name}")
            cmd = ["parted", "-s", dev_base, "rm", num]
            result = subprocess.run(cmd, capture_output=True, text=True)
            GLib.idle_add(self._show_result, result.returncode, result.stdout + result.stderr)
        threading.Thread(target=run, daemon=True).start()

    def _on_resize(self, *_):
        if not self._require_root() or not self.current_partition:
            return
        name = self.current_partition.get("name", "?")
        if not danger_confirm(self.window, "Изменение размера раздела",
                              f"Изменить размер /dev/{name}?",
                              "Обязательно сделайте резервную копию данных."):
            return
        dlg = Gtk.Dialog(title="Изменить размер", transient_for=self.window, modal=True)
        dlg.add_button("Отмена", Gtk.ResponseType.CANCEL)
        dlg.add_button("Применить", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_spacing(8); box.set_margin_top(12); box.set_margin_bottom(12)
        box.set_margin_start(16); box.set_margin_end(16)
        box.append(Gtk.Label(label="Новый конечный размер (например: 20G):"))
        size_entry = Gtk.Entry(placeholder_text="20G")
        box.append(size_entry)
        if dlg.run() == Gtk.ResponseType.OK:
            new_end = size_entry.get_text().strip()
            if new_end:
                num = re.sub(r"[^0-9]", "", name)
                dev_base = re.sub(r"[0-9]", "", f"/dev/{name}")
                def run():
                    cmd = ["parted", "-s", dev_base, "resizepart", num, new_end]
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    GLib.idle_add(self._show_result, result.returncode, result.stdout + result.stderr)
                threading.Thread(target=run, daemon=True).start()
        dlg.destroy()

    def _on_format(self, *_):
        if not self._require_root() or not self.current_partition:
            return
        name = self.current_partition.get("name", "?")
        if not danger_confirm(self.window, "Форматирование раздела",
                              f"Форматировать /dev/{name}?",
                              "ВСЕ ДАННЫЕ БУДУТ СТЁРТЫ БЕЗВОЗВРАТНО!"):
            return
        dlg = Gtk.Dialog(title="Форматировать", transient_for=self.window, modal=True)
        dlg.add_button("Отмена", Gtk.ResponseType.CANCEL)
        dlg.add_button("Форматировать ⚠", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_spacing(8); box.set_margin_top(12); box.set_margin_bottom(12)
        box.set_margin_start(16); box.set_margin_end(16)
        box.append(Gtk.Label(label="Тип файловой системы:"))
        fs_combo = Gtk.DropDown.new_from_strings(["ext4", "ext3", "fat32", "ntfs", "btrfs"])
        box.append(fs_combo)
        if dlg.run() == Gtk.ResponseType.OK:
            fs_names = ["ext4", "ext3", "fat32", "ntfs", "btrfs"]
            fs = fs_names[fs_combo.get_selected()]
            def run():
                fs_cmd = {"ext4":"mkfs.ext4","ext3":"mkfs.ext3","fat32":"mkfs.vfat",
                          "ntfs":"mkfs.ntfs","btrfs":"mkfs.btrfs"}.get(fs, "mkfs.ext4")
                result = subprocess.run([fs_cmd, f"/dev/{name}"], capture_output=True, text=True)
                GLib.idle_add(self._show_result, result.returncode, result.stdout + result.stderr)
            threading.Thread(target=run, daemon=True).start()
        dlg.destroy()

    def _show_result(self, code, output):
        icon = "✅" if code == 0 else "❌"
        dlg = Gtk.MessageDialog(
            transient_for=self.window, modal=True,
            message_type=Gtk.MessageType.INFO if code == 0 else Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=f"{icon} {'Успешно' if code == 0 else 'Ошибка'}"
        )
        dlg.format_secondary_text(output or f"Код завершения: {code}")
        dlg.run(); dlg.destroy()
        self.window.reload_devices()


# ── Главное окно ──────────────────────────────────────────────────
class DiskUtilityWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CryOS — Утилита диска")
        self.set_default_size(820, 520)
        self._build_ui()
        self.reload_devices()

    def _build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Заголовок
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("cry-oobe-header")
        header.set_margin_bottom(0)
        title = Gtk.Label()
        title.set_markup('<span foreground="white" font="13" weight="bold">💿 Утилита диска</span>')
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        title.set_margin_start(8)
        header.append(title)

        refresh_btn = Gtk.Button(label="↺")
        refresh_btn.add_css_class("flat")
        refresh_btn.connect("clicked", lambda b: self.reload_devices())
        header.append(refresh_btn)
        vbox.append(header)

        # Предупреждение если не root
        if not is_root():
            warn_box = Gtk.Box(spacing=8)
            warn_box.set_margin_top(4)
            warn_box.set_margin_bottom(4)
            warn_box.set_margin_start(8)
            warn = Gtk.Label()
            warn.set_markup(
                '<span foreground="#CC0000" weight="bold">'
                '⚠ Запущено без прав root. Операции с разделами недоступны.</span>'
            )
            warn_box.append(warn)
            vbox.append(warn_box)

        # Основной layout
        hpaned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        hpaned.set_position(520)
        hpaned.set_vexpand(True)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Список устройств
        dev_lbl = Gtk.Label(label="Устройства")
        dev_lbl.set_markup("<b>Устройства</b>")
        dev_lbl.set_halign(Gtk.Align.START)
        dev_lbl.set_margin_start(8)
        dev_lbl.set_margin_top(6)
        left.append(dev_lbl)

        dev_scroll = Gtk.ScrolledWindow()
        dev_scroll.set_size_request(-1, 140)
        dev_scroll.set_vexpand(False)
        self.dev_list = Gtk.ListBox()
        self.dev_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.dev_list.connect("row-selected", self._on_device_selected)
        dev_scroll.set_child(self.dev_list)
        left.append(dev_scroll)

        # Визуализатор
        self.visualizer = DiskVisualizer()
        self.visualizer.set_margin_top(4)
        self.visualizer.set_margin_bottom(4)
        self.visualizer.set_margin_start(4)
        self.visualizer.set_margin_end(4)
        left.append(self.visualizer)

        # Таблица разделов
        part_lbl = Gtk.Label(label="Разделы")
        part_lbl.set_markup("<b>Разделы</b>")
        part_lbl.set_halign(Gtk.Align.START)
        part_lbl.set_margin_start(8)
        left.append(part_lbl)

        part_scroll = Gtk.ScrolledWindow()
        part_scroll.set_vexpand(True)
        self.part_list = Gtk.ListBox()
        self.part_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.part_list.connect("row-selected", self._on_partition_selected)
        part_scroll.set_child(self.part_list)
        left.append(part_scroll)

        hpaned.set_start_child(left)

        # Панель операций
        ops_scroll = Gtk.ScrolledWindow()
        self.ops_panel = OperationsPanel(self)
        ops_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        ops_box.set_margin_top(12)
        ops_box.set_margin_start(12)
        ops_box.set_margin_end(12)
        ops_box.set_spacing(6)
        ops_box.append(self.ops_panel)
        ops_scroll.set_child(ops_box)
        hpaned.set_end_child(ops_scroll)
        hpaned.set_resize_end_child(False)

        vbox.append(hpaned)
        self.set_child(vbox)

    def reload_devices(self):
        while row := self.dev_list.get_row_at_index(0):
            self.dev_list.remove(row)
        self.devices = get_block_devices()
        for dev in self.devices:
            if dev.get("type") != "disk":
                continue
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=8)
            box.set_margin_top(4); box.set_margin_bottom(4)
            box.set_margin_start(8); box.set_margin_end(8)
            icon = Gtk.Label(label="💾")
            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            name_lbl = Gtk.Label(label=f"/dev/{dev['name']}")
            name_lbl.set_markup(f'<b>/dev/{dev["name"]}</b>')
            name_lbl.set_halign(Gtk.Align.START)
            model = dev.get("model") or ""
            size  = dev.get("size", "?")
            sub_lbl = Gtk.Label(label=f"{model}  {size}")
            sub_lbl.set_halign(Gtk.Align.START)
            info.append(name_lbl)
            info.append(sub_lbl)
            box.append(icon)
            box.append(info)
            row.set_child(box)
            row._device = dev
            self.dev_list.append(row)

    def _on_device_selected(self, lb, row):
        if row is None:
            return
        dev = row._device
        self.ops_panel.set_device(dev)
        self.visualizer.set_device(dev)
        # Заполняем разделы
        while r := self.part_list.get_row_at_index(0):
            self.part_list.remove(r)
        for part in dev.get("children", []):
            prow = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=8)
            box.set_margin_top(3); box.set_margin_bottom(3)
            box.set_margin_start(8); box.set_margin_end(8)
            cols = [
                f"/dev/{part.get('name','?')}",
                part.get("size","?"),
                part.get("fstype") or "—",
                part.get("mountpoint") or "—",
            ]
            for col in cols:
                lbl = Gtk.Label(label=col)
                lbl.set_halign(Gtk.Align.START)
                lbl.set_width_chars(12)
                box.append(lbl)
            prow.set_child(box)
            prow._partition = part
            self.part_list.append(prow)

    def _on_partition_selected(self, lb, row):
        if row is None:
            return
        self.ops_panel.set_partition(row._partition)


class DiskUtilityApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.cryos.DiskUtility",
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
        win = DiskUtilityWindow(self)
        win.present()

def main():
    app = DiskUtilityApp()
    app.run(sys.argv)

if __name__ == "__main__":
    main()
