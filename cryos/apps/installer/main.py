#!/usr/bin/env python3
"""
CryOS Installer  —  apps/installer/main.py
==========================================
Графический установщик CryOS.

Экраны:
  1. Приветствие
  2. Сеть (Wi-Fi / Ethernet)
  3. Проверка системы (RAM, питание, место, интернет, UEFI/BIOS)
  4. Режим установки (рядом с ОС / весь диск / вручную)
  5. Выбор диска / свободного места
  6. Создание пользователя
  7. Подтверждение + предупреждение
  8. Установка с прогресс-баром
  9. Готово — перезагрузка

GRUB:
  - Автоопределение UEFI vs BIOS
  - os-prober находит Mint / Arch / Windows / другие ОС
  - update-grub добавляет CryOS в общее меню
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio

import subprocess, sys, os, json, threading, shutil, re, time
from pathlib import Path

CRYOS_SRC = Path("/usr/share/cryos")
CRYOS_DST = "/mnt/cryos_install"
THEME_CSS  = Path(__file__).parent.parent.parent / "system" / "theme" / "gtk.css"

KONATA_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 130" width="52" height="86">
  <circle cx="40" cy="20" r="15" fill="#000080"/>
  <path d="M25 17 Q8 28 6 75 Q11 77 13 72 Q15 52 20 40 Z" fill="#000080"/>
  <path d="M55 17 Q72 28 74 75 Q69 77 67 72 Q65 52 60 40 Z" fill="#000080"/>
  <path d="M25 19 Q4 8 3 34 Q8 36 10 31 Q14 19 23 23 Z" fill="#000080"/>
  <rect x="27" y="34" width="26" height="30" rx="4" fill="#000080"/>
  <rect x="14" y="36" width="13" height="9" rx="4" fill="#000080"/>
  <rect x="53" y="36" width="13" height="9" rx="4" fill="#000080"/>
  <path d="M27 64 L21 100 L31 100 L40 82 L49 100 L59 100 L53 64 Z" fill="#000080"/>
  <circle cx="35" cy="18" r="2" fill="white"/>
  <circle cx="45" cy="18" r="2" fill="white"/>
</svg>""".encode()


# ── Утилиты ─────────────────────────────────────────────────────
def load_css():
    if THEME_CSS.exists():
        p = Gtk.CssProvider()
        p.load_from_path(str(THEME_CSS))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), p,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

def make_konata():
    import tempfile
    t = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
    t.write(KONATA_SVG); t.close()
    pic = Gtk.Picture()
    pic.set_filename(t.name)
    pic.set_content_fit(Gtk.ContentFit.CONTAIN)
    pic.set_size_request(52, 86)
    GLib.timeout_add(8000, lambda: os.unlink(t.name) or False)
    return pic

def make_header(title: str, subtitle: str = "") -> Gtk.Box:
    bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    bar.add_css_class("cry-oobe-header")
    bar.set_size_request(-1, 72)
    k = make_konata()
    k.set_margin_start(12); k.set_margin_end(12)
    k.set_margin_top(6);    k.set_margin_bottom(6)
    bar.append(k)
    sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
    sep.set_margin_top(12); sep.set_margin_bottom(12); sep.set_margin_end(12)
    bar.append(sep)
    tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    tb.set_valign(Gtk.Align.CENTER)
    t = Gtk.Label()
    t.set_markup(f'<span foreground="white" font="14" weight="bold">{title}</span>')
    t.set_halign(Gtk.Align.START); tb.append(t)
    if subtitle:
        s = Gtk.Label()
        s.set_markup(f'<span foreground="#9EC8FF" font="10">{subtitle}</span>')
        s.set_halign(Gtk.Align.START); tb.append(s)
    bar.append(tb)
    return bar

def nav_bar(on_back=None, on_next=None, next_label="Далее →",
            next_sensitive=True) -> tuple[Gtk.Box, Gtk.Button | None]:
    """Возвращает (box, next_btn)."""
    box = Gtk.Box(spacing=8)
    box.set_margin_top(10); box.set_margin_bottom(12)
    box.set_margin_start(24); box.set_margin_end(24)
    if on_back:
        b = Gtk.Button(label="◀ Назад")
        b.connect("clicked", lambda _: on_back())
        box.append(b)
    sp = Gtk.Box(); sp.set_hexpand(True); box.append(sp)
    nxt = None
    if on_next is not None:
        nxt = Gtk.Button(label=next_label)
        nxt.add_css_class("suggested-action")
        nxt.set_size_request(150, 34)
        nxt.set_sensitive(next_sensitive)
        nxt.connect("clicked", lambda _: on_next())
        box.append(nxt)
    return box, nxt

def fmt_mb(mb: int) -> str:
    if mb >= 1024: return f"{mb/1024:.1f} ГБ"
    return f"{mb} МБ"

def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kw)

def is_uefi() -> bool:
    return Path("/sys/firmware/efi").exists()

def get_ram_mb() -> int:
    try:
        r = run(["free", "-m"])
        for line in r.stdout.splitlines():
            if line.startswith("Mem:"):
                return int(line.split()[1])
    except: pass
    return 0

def on_battery() -> bool:
    for p in Path("/sys/class/power_supply").glob("AC*"):
        try:
            return (p / "online").read_text().strip() == "0"
        except: pass
    return False

def has_internet() -> bool:
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "2", "8.8.8.8"],
                           capture_output=True, timeout=5)
        return r.returncode == 0
    except: return False

def get_wifi_networks() -> list[str]:
    try:
        r = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY",
                 "device", "wifi", "list"])
        nets = []
        for line in r.stdout.splitlines():
            parts = line.split(":")
            if parts and parts[0].strip():
                ssid   = parts[0].strip()
                signal = parts[1] if len(parts) > 1 else "?"
                sec    = parts[2] if len(parts) > 2 else ""
                nets.append({"ssid": ssid, "signal": signal, "secured": bool(sec)})
        return nets
    except: return []

def get_interfaces() -> list[str]:
    try:
        r = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"])
        ifaces = []
        for line in r.stdout.splitlines():
            p = line.split(":")
            if len(p) >= 3 and p[2] == "connected":
                ifaces.append(f"{p[0]} ({p[1]})")
        return ifaces
    except: return []

def get_disks() -> list[dict]:
    disks = []
    try:
        r = run(["lsblk", "-J", "-b",
                 "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL,LABEL"])
        data = json.loads(r.stdout)
        for dev in data.get("blockdevices", []):
            if dev.get("type") != "disk": continue
            name       = dev["name"]
            size       = int(dev.get("size") or 0)
            model      = (dev.get("model") or name).strip()
            used_bytes = 0
            partitions = []
            for p in dev.get("children", []):
                ps = int(p.get("size") or 0)
                used_bytes += ps
                partitions.append({
                    "name":  p["name"],
                    "size":  ps,
                    "fs":    p.get("fstype") or "—",
                    "mount": p.get("mountpoint") or "",
                    "label": p.get("label") or "",
                })
            free_mb = (size - used_bytes) // (1024*1024)
            disks.append({
                "name":       name,
                "dev":        f"/dev/{name}",
                "model":      model,
                "size":       size,
                "size_mb":    size // (1024*1024),
                "free_mb":    free_mb,
                "partitions": partitions,
                "has_space":  free_mb >= 10*1024,
            })
    except: pass
    return disks

def detect_other_os() -> list[str]:
    """
    Находит другие ОС на дисках через os-prober.
    Возвращает список строк типа ['Windows Boot Manager', 'Linux Mint 21']
    """
    found = []
    try:
        r = subprocess.run(["os-prober"], capture_output=True, text=True,
                           timeout=30)
        # Формат: /dev/sda1:Windows Boot Manager:Windows:chain
        for line in r.stdout.strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 2:
                found.append(parts[1].strip())
    except FileNotFoundError:
        # os-prober не установлен — пробуем вручную через lsblk + labels
        try:
            r = run(["lsblk", "-o", "LABEL,FSTYPE", "-J"])
            data = json.loads(r.stdout)
            for dev in data.get("blockdevices", []):
                for child in dev.get("children", []):
                    label = (child.get("label") or "").lower()
                    if any(k in label for k in ["windows","mint","ubuntu","arch","fedora"]):
                        found.append(child.get("label","Unknown OS"))
        except: pass
    except: pass
    return found


# ════════════════════════════════════════════════════════════════════
# ЭКРАН 1 — ПРИВЕТСТВИЕ
# ════════════════════════════════════════════════════════════════════
class PageWelcome(Gtk.Box):
    def __init__(self, on_next):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.append(make_header("Установка CryOS",
                                "Мастер установки на ваш компьютер"))
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_vexpand(True)
        content.set_margin_top(32); content.set_margin_bottom(16)
        content.set_margin_start(48); content.set_margin_end(48)
        msg = Gtk.Label()
        msg.set_markup(
            '<span font="12">'
            'Добро пожаловать в установщик <b>CryOS</b>!\n\n'
            'Мастер поможет установить систему:\n'
            '  • Подключится к сети\n'
            '  • Проверит совместимость компьютера\n'
            '  • Найдёт свободное место на диске\n'
            '  • Установит CryOS рядом с другими ОС\n'
            '  • Настроит GRUB (Mint / Arch / Windows сохранятся)\n\n'
            '<span foreground="#CC0000">'
            '⚠ Сделайте резервную копию важных данных!</span></span>')
        msg.set_halign(Gtk.Align.START); msg.set_xalign(0)
        content.append(msg)
        self.append(content)
        self.append(Gtk.Separator())
        nb, _ = nav_bar(on_next=on_next, next_label="Начать →")
        self.append(nb)


# ════════════════════════════════════════════════════════════════════
# ЭКРАН 2 — СЕТЬ
# ════════════════════════════════════════════════════════════════════
class PageNetwork(Gtk.Box):
    def __init__(self, on_next, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._on_next = on_next
        self.append(make_header("Подключение к сети",
                                "Wi-Fi или Ethernet"))

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_vexpand(True)
        content.set_margin_top(16); content.set_margin_bottom(8)
        content.set_margin_start(32); content.set_margin_end(32)

        # Статус подключения
        self._status_lbl = Gtk.Label()
        self._status_lbl.set_halign(Gtk.Align.START)
        content.append(self._status_lbl)

        # Подключенные интерфейсы
        ifaces = get_interfaces()
        if ifaces:
            iface_lbl = Gtk.Label()
            iface_lbl.set_markup(
                '<span foreground="#007700">Подключено: '
                + ", ".join(ifaces) + '</span>')
            iface_lbl.set_halign(Gtk.Align.START)
            content.append(iface_lbl)

        sep = Gtk.Separator(); sep.set_margin_top(8); sep.set_margin_bottom(8)
        content.append(sep)

        # Wi-Fi список
        wifi_lbl = Gtk.Label()
        wifi_lbl.set_markup('<b>Доступные Wi-Fi сети:</b>')
        wifi_lbl.set_halign(Gtk.Align.START)
        content.append(wifi_lbl)

        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(-1, 180)
        self._wifi_list = Gtk.ListBox()
        self._wifi_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        scroll.set_child(self._wifi_list)
        content.append(scroll)

        # Кнопки Wi-Fi
        btn_box = Gtk.Box(spacing=8)
        refresh_btn = Gtk.Button(label="↺ Обновить")
        refresh_btn.connect("clicked", lambda b: self._scan_wifi())
        btn_box.append(refresh_btn)
        connect_btn = Gtk.Button(label="🔗 Подключиться")
        connect_btn.add_css_class("suggested-action")
        connect_btn.connect("clicked", self._on_connect)
        btn_box.append(connect_btn)
        content.append(btn_box)

        # Ethernet-подсказка
        eth_lbl = Gtk.Label()
        eth_lbl.set_markup(
            '<span foreground="#555555" size="small">'
            'Ethernet подключается автоматически.\n'
            'Можно пропустить этот шаг если нет Wi-Fi.</span>')
        eth_lbl.set_halign(Gtk.Align.START)
        content.append(eth_lbl)

        self.append(content)
        self.append(Gtk.Separator())

        nav, self._next_btn = nav_bar(
            on_back=on_back,
            on_next=on_next,
            next_label="Далее →")
        self.append(nav)

        self._scan_wifi()
        self._check_connection()

    def _scan_wifi(self):
        self._wifi_list.remove_all() if hasattr(self._wifi_list, 'remove_all') else None
        # Очищаем вручную
        while row := self._wifi_list.get_row_at_index(0):
            self._wifi_list.remove(row)

        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        nets = get_wifi_networks()
        GLib.idle_add(self._fill_wifi, nets)

    def _fill_wifi(self, nets: list):
        while row := self._wifi_list.get_row_at_index(0):
            self._wifi_list.remove(row)
        if not nets:
            row = Gtk.ListBoxRow()
            row.set_child(Gtk.Label(label="Wi-Fi сети не найдены"))
            self._wifi_list.append(row)
            return
        for net in nets:
            row = Gtk.ListBoxRow()
            hb  = Gtk.Box(spacing=8)
            hb.set_margin_top(4); hb.set_margin_bottom(4)
            hb.set_margin_start(8)
            lock = "🔒" if net["secured"] else "🔓"
            sig  = int(net["signal"]) if str(net["signal"]).isdigit() else 0
            bars = "▂▄▆█"[:max(1, sig // 25)]
            lbl  = Gtk.Label(label=f"{lock} {net['ssid']}  {bars}")
            lbl.set_halign(Gtk.Align.START); lbl.set_hexpand(True)
            hb.append(lbl)
            row.set_child(hb)
            row._ssid    = net["ssid"]
            row._secured = net["secured"]
            self._wifi_list.append(row)

    def _on_connect(self, *_):
        row = self._wifi_list.get_selected_row()
        if row is None: return
        ssid    = row._ssid
        secured = row._secured
        if secured:
            dlg = Gtk.Dialog(title=f"Пароль для {ssid}",
                             transient_for=self.get_ancestor(Gtk.Window),
                             modal=True)
            dlg.add_button("Отмена", Gtk.ResponseType.CANCEL)
            dlg.add_button("Подключить", Gtk.ResponseType.OK)
            box = dlg.get_content_area()
            box.set_margin_top(12); box.set_margin_bottom(12)
            box.set_margin_start(16); box.set_margin_end(16)
            box.set_spacing(8)
            box.append(Gtk.Label(label=f"Пароль Wi-Fi «{ssid}»:"))
            entry = Gtk.Entry(); entry.set_visibility(False)
            box.append(entry)
            if dlg.run() == Gtk.ResponseType.OK:
                pw = entry.get_text()
                dlg.destroy()
                self._do_connect(ssid, pw)
            else:
                dlg.destroy()
        else:
            self._do_connect(ssid, None)

    def _do_connect(self, ssid: str, password: str | None):
        self._status_lbl.set_markup(
            f'<span foreground="#000080">Подключаемся к {ssid}...</span>')
        def work():
            if password:
                r = run(["nmcli", "device", "wifi", "connect",
                         ssid, "password", password])
            else:
                r = run(["nmcli", "device", "wifi", "connect", ssid])
            GLib.idle_add(self._connect_done, r.returncode, ssid)
        threading.Thread(target=work, daemon=True).start()

    def _connect_done(self, code: int, ssid: str):
        if code == 0:
            self._status_lbl.set_markup(
                f'<span foreground="#007700">✅ Подключено: {ssid}</span>')
            if self._next_btn:
                self._next_btn.set_sensitive(True)
        else:
            self._status_lbl.set_markup(
                '<span foreground="#CC0000">❌ Ошибка подключения. '
                'Проверьте пароль.</span>')

    def _check_connection(self):
        def work():
            ok = has_internet()
            GLib.idle_add(self._set_status, ok)
        threading.Thread(target=work, daemon=True).start()

    def _set_status(self, ok: bool):
        if ok:
            self._status_lbl.set_markup(
                '<span foreground="#007700">✅ Интернет доступен</span>')
            if self._next_btn:
                self._next_btn.set_sensitive(True)
        else:
            self._status_lbl.set_markup(
                '<span foreground="#CC0000">⚠ Нет подключения к интернету</span>')


# ════════════════════════════════════════════════════════════════════
# ЭКРАН 3 — ПРОВЕРКА СИСТЕМЫ
# ════════════════════════════════════════════════════════════════════
class PageCheck(Gtk.Box):
    CHECKS = [
        ("RAM ≥ 512 МБ",         "ram"),
        ("Место на диске ≥ 10 ГБ","disk"),
        ("Интернет",              "net"),
        ("Питание (ноутбук)",     "power"),
        ("UEFI / BIOS",           "boot"),
    ]

    def __init__(self, on_next, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._on_next = on_next
        self.append(make_header("Проверка системы",
                                "Убедимся, что всё готово к установке"))

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.set_vexpand(True)
        content.set_margin_top(24); content.set_margin_bottom(8)
        content.set_margin_start(48); content.set_margin_end(48)

        self._rows: dict[str, Gtk.Label] = {}
        for label, key in self.CHECKS:
            hb = Gtk.Box(spacing=12); hb.set_margin_bottom(4)
            icon = Gtk.Label(label="⏳")
            icon.set_width_chars(3)
            lbl  = Gtk.Label(label=label)
            lbl.set_halign(Gtk.Align.START); lbl.set_hexpand(True)
            val  = Gtk.Label(label="проверяем...")
            val.set_halign(Gtk.Align.END)
            hb.append(icon); hb.append(lbl); hb.append(val)
            content.append(hb)
            self._rows[key] = (icon, val)

        self._summary = Gtk.Label(label="")
        self._summary.set_margin_top(16)
        self._summary.set_halign(Gtk.Align.START)
        content.append(self._summary)

        # Другие ОС
        sep = Gtk.Separator(); sep.set_margin_top(12); sep.set_margin_bottom(8)
        content.append(sep)
        os_lbl = Gtk.Label()
        os_lbl.set_markup('<b>Обнаруженные ОС на дисках:</b>')
        os_lbl.set_halign(Gtk.Align.START)
        content.append(os_lbl)
        self._os_lbl = Gtk.Label(label="Поиск...")
        self._os_lbl.set_halign(Gtk.Align.START)
        self._os_lbl.set_wrap(True)
        content.append(self._os_lbl)
        compat_note = Gtk.Label()
        compat_note.set_markup(
            '<span foreground="#007700" size="small">'
            '✅ CryOS устанавливается рядом с другими ОС.\n'
            'GRUB добавит все системы в меню загрузки.</span>')
        compat_note.set_halign(Gtk.Align.START)
        content.append(compat_note)

        self.append(content)
        self.append(Gtk.Separator())
        nav, self._next_btn = nav_bar(
            on_back=on_back,
            on_next=on_next,
            next_label="Далее →",
            next_sensitive=False)
        self.append(nav)

        threading.Thread(target=self._run_checks, daemon=True).start()

    def _run_checks(self):
        results = {}

        # RAM
        ram = get_ram_mb()
        results["ram"] = (ram >= 512, f"{ram} МБ")

        # Диск
        disks = get_disks()
        max_free = max((d["free_mb"] for d in disks), default=0)
        results["disk"] = (max_free >= 10*1024, fmt_mb(max_free) + " свободно")

        # Интернет
        net = has_internet()
        results["net"] = (net, "Есть" if net else "Нет")

        # Питание
        bat = on_battery()
        results["power"] = (not bat,
            "Питание от сети" if not bat else "⚠ Работает от батареи")

        # UEFI / BIOS
        uefi = is_uefi()
        results["boot"] = (True, "UEFI" if uefi else "BIOS (Legacy)")

        GLib.idle_add(self._show_results, results)

        # Другие ОС
        other_os = detect_other_os()
        GLib.idle_add(self._show_os, other_os)

    def _show_results(self, results: dict):
        ok_count = 0
        critical_fail = False
        for key, (ok, detail) in results.items():
            icon_w, val_w = self._rows[key]
            icon_w.set_text("✅" if ok else "⚠")
            val_w.set_markup(
                f'<span foreground="{"#007700" if ok else "#CC0000"}">'
                f'{detail}</span>')
            if ok: ok_count += 1
            if not ok and key in ("ram", "disk"):
                critical_fail = True

        if critical_fail:
            self._summary.set_markup(
                '<span foreground="#CC0000" weight="bold">'
                '❌ Критические требования не выполнены.\n'
                'Установка может завершиться с ошибкой.</span>')
            if self._next_btn:
                self._next_btn.set_sensitive(True)  # всё равно разрешаем попробовать
        else:
            self._summary.set_markup(
                '<span foreground="#007700" weight="bold">'
                f'✅ Система готова к установке CryOS ({ok_count}/{len(results)})</span>')
            if self._next_btn:
                self._next_btn.set_sensitive(True)

    def _show_os(self, os_list: list):
        if os_list:
            self._os_lbl.set_markup(
                '<span foreground="#000080">'
                + "\n".join(f"• {o}" for o in os_list)
                + '</span>')
        else:
            self._os_lbl.set_text("Другие ОС не обнаружены (или os-prober не установлен)")


# ════════════════════════════════════════════════════════════════════
# ЭКРАН 4 — РЕЖИМ УСТАНОВКИ
# ════════════════════════════════════════════════════════════════════
class PageInstallMode(Gtk.Box):
    MODES = [
        ("alongside",
         "Установить рядом с другой ОС",
         "CryOS займёт свободное место на диске.\n"
         "Все существующие ОС сохранятся.\n"
         "GRUB покажет меню выбора при загрузке.",
         "🟢 Рекомендуется"),
        ("whole",
         "Занять весь диск",
         "Весь выбранный диск будет отформатирован.\n"
         "⚠ ВСЕ ДАННЫЕ НА ДИСКЕ БУДУТ УДАЛЕНЫ!\n"
         "Подходит для нового или пустого диска.",
         "🔴 Удаляет данные"),
        ("manual",
         "Ручная разметка",
         "Вы сами выбираете разделы для монтирования.\n"
         "Для опытных пользователей.\n"
         "Требует знания разметки дисков.",
         "🟡 Для опытных"),
    ]

    def __init__(self, on_next, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._selected_mode = "alongside"
        self._on_next = on_next

        self.append(make_header("Режим установки",
                                "Как установить CryOS на этот компьютер"))

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_vexpand(True)
        content.set_margin_top(20); content.set_margin_bottom(8)
        content.set_margin_start(32); content.set_margin_end(32)

        self._btns: list[tuple[str, Gtk.Button]] = []

        for mode_id, title, desc, badge in self.MODES:
            btn = Gtk.Button()
            btn.set_has_frame(True)

            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            inner.set_margin_top(12); inner.set_margin_bottom(12)
            inner.set_margin_start(16); inner.set_margin_end(16)

            title_box = Gtk.Box(spacing=8)
            title_lbl = Gtk.Label()
            title_lbl.set_markup(f'<b>{title}</b>')
            title_lbl.set_halign(Gtk.Align.START); title_lbl.set_hexpand(True)
            badge_lbl = Gtk.Label(label=badge)
            badge_lbl.set_halign(Gtk.Align.END)
            title_box.append(title_lbl); title_box.append(badge_lbl)
            inner.append(title_box)

            desc_lbl = Gtk.Label(label=desc)
            desc_lbl.set_halign(Gtk.Align.START)
            desc_lbl.set_xalign(0); desc_lbl.set_wrap(True)
            inner.append(desc_lbl)

            btn.set_child(inner)
            btn.connect("clicked", self._on_mode_click, mode_id)
            content.append(btn)
            self._btns.append((mode_id, btn))

        self.append(content)
        self.append(Gtk.Separator())
        nav, self._next_btn = nav_bar(
            on_back=on_back,
            on_next=self._go_next,
            next_label="Далее →")
        self.append(nav)

        # Выделяем первый режим
        self._highlight("alongside")

    def _on_mode_click(self, btn, mode_id: str):
        if mode_id == "manual":
            d = Gtk.MessageDialog(
                transient_for=self.get_ancestor(Gtk.Window),
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Ручная разметка")
            d.format_secondary_text(
                "Для ручной разметки используйте утилиту диска CryOS\n"
                "(cryos-disk) или GParted, затем вернитесь к установщику.")
            d.run(); d.destroy()
            return
        self._selected_mode = mode_id
        self._highlight(mode_id)

    def _highlight(self, active_id: str):
        for mode_id, btn in self._btns:
            ctx = btn.get_style_context()
            if mode_id == active_id:
                ctx.add_class("suggested-action")
            else:
                ctx.remove_class("suggested-action")
                ctx.remove_class("destructive-action")
        if active_id == "whole":
            for mode_id, btn in self._btns:
                if mode_id == "whole":
                    btn.get_style_context().remove_class("suggested-action")
                    btn.get_style_context().add_class("destructive-action")

    def _go_next(self):
        self._on_next(self._selected_mode)

    def get_mode(self) -> str:
        return self._selected_mode


# ════════════════════════════════════════════════════════════════════
# ЭКРАН 5 — ВЫБОР ДИСКА
# ════════════════════════════════════════════════════════════════════
class PageDisk(Gtk.Box):
    def __init__(self, on_next, on_back, mode: str = "alongside"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._on_next  = on_next
        self._mode     = mode
        self._selected = None
        self._size_mb  = 0

        subtitle = {
            "alongside": "Выберите диск со свободным местом",
            "whole":     "⚠ Выбранный диск будет полностью отформатирован",
        }.get(mode, "Выбор диска")

        self.append(make_header("Выбор диска", subtitle))

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_vexpand(True)
        content.set_margin_top(16); content.set_margin_bottom(8)
        content.set_margin_start(24); content.set_margin_end(24)

        disks = get_disks()
        if mode == "alongside":
            available = [d for d in disks if d["has_space"]]
        else:
            available = disks  # «весь диск» — любой

        if not available:
            warn = Gtk.Label()
            warn.set_markup(
                '<span foreground="#CC0000" font="12">'
                '⚠ Не найдено подходящих дисков.\n\n'
                'Освободите место (минимум 10 ГБ) и повторите.</span>')
            warn.set_vexpand(True); warn.set_valign(Gtk.Align.CENTER)
            content.append(warn)
            self.append(content)
            nb, _ = nav_bar(on_back=on_back)
            self.append(Gtk.Separator()); self.append(nb)
            return

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list.connect("row-selected", self._on_selected)

        for disk in available:
            row  = Gtk.ListBoxRow()
            box  = Gtk.Box(spacing=10)
            box.set_margin_top(8); box.set_margin_bottom(8)
            box.set_margin_start(12)
            icon = Gtk.Label()
            icon.set_markup('<span font="22">💾</span>')
            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            info.set_hexpand(True)
            nm = Gtk.Label()
            nm.set_markup(f'<b>{disk["dev"]}</b>  {disk["model"]}')
            nm.set_halign(Gtk.Align.START)
            detail = Gtk.Label()

            if mode == "alongside":
                detail.set_markup(
                    f'Итого: {fmt_mb(disk["size_mb"])}  |  '
                    f'<span foreground="#007700">Свободно: {fmt_mb(disk["free_mb"])}</span>')
            else:
                detail.set_markup(
                    f'<span foreground="#CC0000">Весь диск: {fmt_mb(disk["size_mb"])}'
                    f' будет отформатирован</span>')
            detail.set_halign(Gtk.Align.START)

            # Карта разделов
            bar = Gtk.Box(spacing=1); bar.set_margin_top(4)
            total = disk["size_mb"] or 1
            for part in disk["partitions"]:
                pct = max(int(160 * part["size"] // (1024*1024) / total), 6)
                pb = Gtk.ProgressBar()
                pb.set_fraction(1.0); pb.set_size_request(pct, 10)
                pb.set_tooltip_text(
                    f"{part['name']} {fmt_mb(part['size']//(1024*1024))} "
                    f"{part['fs']} {part['label']}")
                bar.append(pb)
            if disk["free_mb"] > 0:
                pct = max(int(160 * disk["free_mb"] / total), 6)
                free_bar = Gtk.ProgressBar()
                css = Gtk.CssProvider()
                css.load_from_data(b"progressbar progress{background:#00AA00;}")
                free_bar.get_style_context().add_provider(
                    css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
                free_bar.set_fraction(1.0)
                free_bar.set_size_request(pct, 10)
                free_bar.set_tooltip_text(f"Свободно: {fmt_mb(disk['free_mb'])}")
                bar.append(free_bar)

            info.append(nm); info.append(detail); info.append(bar)
            box.append(icon); box.append(info)
            row.set_child(box)
            row._disk = disk
            self._list.append(row)

        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(-1, 200); scroll.set_vexpand(True)
        scroll.set_child(self._list)
        content.append(scroll)

        # Слайдер размера (только для режима alongside)
        if mode == "alongside":
            sz_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            sz_box.set_margin_top(10)
            sz_box.append(Gtk.Label(label="Размер раздела для CryOS:"))
            sl_box = Gtk.Box(spacing=10)
            self._slider = Gtk.Scale.new_with_range(
                Gtk.Orientation.HORIZONTAL, 10, 200, 1)
            self._slider.set_hexpand(True)
            self._slider.set_value(50)
            self._slider.set_draw_value(False)
            self._slider.connect("value-changed", self._on_slider)
            sl_box.append(self._slider)
            self._size_lbl = Gtk.Label(label="50 ГБ")
            self._size_lbl.set_width_chars(8)
            sl_box.append(self._size_lbl)
            sz_box.append(sl_box)
            content.append(sz_box)
        else:
            self._slider = None

        self.append(content)
        self.append(Gtk.Separator())
        nav, self._next_btn = nav_bar(
            on_back=on_back,
            on_next=lambda: self._on_next(self._selected, self._size_mb),
            next_label="Далее →",
            next_sensitive=False)
        self.append(nav)

        # Автовыбор первого
        first = self._list.get_row_at_index(0)
        if first: self._list.select_row(first)

    def _on_selected(self, lb, row):
        if row is None: return
        self._selected = row._disk
        if self._slider:
            free_gb = self._selected["free_mb"] / 1024
            self._slider.set_range(10, max(10, min(free_gb, 500)))
            self._slider.set_value(min(50, free_gb))
            self._on_slider(self._slider)
        else:
            self._size_mb = self._selected["size_mb"]
        if self._next_btn: self._next_btn.set_sensitive(True)

    def _on_slider(self, slider):
        val = int(slider.get_value())
        self._size_mb = val * 1024
        self._size_lbl.set_text(f"{val} ГБ")


# ════════════════════════════════════════════════════════════════════
# ЭКРАН 6 — СОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ
# ════════════════════════════════════════════════════════════════════
class PageUser(Gtk.Box):
    def __init__(self, on_next, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.append(make_header("Создание пользователя",
                                "Аккаунт с правами администратора"))

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_vexpand(True)
        content.set_margin_top(20); content.set_margin_bottom(8)
        content.set_margin_start(48); content.set_margin_end(48)

        fields = [
            ("Имя пользователя (a-z, 0-9, _):", "_user", "cryuser",  False),
            ("Полное имя:",                      "_full", "Ваше имя", False),
            ("Пароль:",                          "_pw1",  "Пароль",   True),
            ("Повторите пароль:",                "_pw2",  "Ещё раз",  True),
            ("Имя компьютера:",                  "_host", "cryos-pc", False),
        ]
        for lbl, attr, ph, hide in fields:
            content.append(Gtk.Label(label=lbl))
            e = Gtk.Entry(); e.set_placeholder_text(ph)
            if hide: e.set_visibility(False)
            setattr(self, attr, e)
            content.append(e)

        self._sudo = Gtk.CheckButton(label="Права администратора (sudo)")
        self._sudo.set_active(True)
        content.append(self._sudo)

        self._status = Gtk.Label(label="")
        self._status.set_halign(Gtk.Align.START)
        content.append(self._status)

        self.append(content)
        self.append(Gtk.Separator())
        nav, _ = nav_bar(on_back=on_back,
                         on_next=lambda: self._validate(on_next))
        self.append(nav)

    def _validate(self, on_next):
        user = self._user.get_text().strip()
        pw1  = self._pw1.get_text()
        pw2  = self._pw2.get_text()
        if not re.match(r'^[a-z][a-z0-9_]{1,31}$', user):
            self._status.set_markup(
                '<span foreground="#CC0000">Логин: только a-z, 0-9, _ (2+ символа)</span>')
            return
        if len(pw1) < 4:
            self._status.set_markup(
                '<span foreground="#CC0000">Пароль слишком короткий (≥ 4 символа)</span>')
            return
        if pw1 != pw2:
            self._status.set_markup(
                '<span foreground="#CC0000">Пароли не совпадают</span>')
            return
        on_next({"username": user,
                 "fullname": self._full.get_text().strip() or user,
                 "password": pw1,
                 "hostname": self._host.get_text().strip() or "cryos-pc",
                 "sudo":     self._sudo.get_active()})


# ════════════════════════════════════════════════════════════════════
# ЭКРАН 7 — ПОДТВЕРЖДЕНИЕ
# ════════════════════════════════════════════════════════════════════
class PageConfirm(Gtk.Box):
    def __init__(self, disk, size_mb, user, mode, on_install, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.append(make_header("Подтверждение",
                                "Проверьте параметры перед установкой"))

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.set_vexpand(True)
        content.set_margin_top(20); content.set_margin_bottom(8)
        content.set_margin_start(48); content.set_margin_end(48)

        def row(label, value, color="#000000"):
            hb = Gtk.Box(spacing=8); hb.set_margin_bottom(4)
            l = Gtk.Label(); l.set_markup(f"<b>{label}</b>")
            l.set_width_chars(18); l.set_halign(Gtk.Align.START)
            v = Gtk.Label()
            v.set_markup(f'<span foreground="{color}">{value}</span>')
            v.set_halign(Gtk.Align.START)
            hb.append(l); hb.append(v); content.append(hb)

        mode_names = {"alongside":"Рядом с другой ОС",
                      "whole":"Весь диск (стереть)"}
        row("Режим:",          mode_names.get(mode, mode))
        row("Диск:",           f"{disk['dev']}  ({disk['model']})")
        row("Размер раздела:", fmt_mb(size_mb))
        row("UEFI / BIOS:",    "UEFI" if is_uefi() else "BIOS")
        row("Пользователь:",   user["username"])
        row("Компьютер:",      user["hostname"])
        row("sudo:",           "Да" if user["sudo"] else "Нет")

        # Другие ОС — сохранятся
        other = detect_other_os()
        if other:
            row("Другие ОС:", ", ".join(other), "#007700")
            row("После установки:", "Все ОС в меню GRUB", "#007700")

        sep = Gtk.Separator(); sep.set_margin_top(12); sep.set_margin_bottom(8)
        content.append(sep)

        color = "#CC0000" if mode == "whole" else "#885500"
        warn_text = (
            f'⚠ На диске {disk["dev"]} будет создан раздел {fmt_mb(size_mb)}.\n'
            if mode == "alongside" else
            f'⚠⚠ ДИСК {disk["dev"]} БУДЕТ ПОЛНОСТЬЮ ОТФОРМАТИРОВАН!\n'
            'ВСЕ ДАННЫЕ НА НЁМ БУДУТ УНИЧТОЖЕНЫ!\n'
        )
        warn = Gtk.Label()
        warn.set_markup(f'<span foreground="{color}">{warn_text}\n'
                        'После нажатия «Установить» отменить невозможно!</span>')
        warn.set_halign(Gtk.Align.START); warn.set_xalign(0)
        content.append(warn)
        self.append(content)
        self.append(Gtk.Separator())

        nav, _ = nav_bar(
            on_back=on_back,
            on_next=on_install,
            next_label="Установить ▶")
        # Красная кнопка для деструктивного режима
        if mode == "whole":
            for child in nav:
                if isinstance(child, Gtk.Button) and "Установить" in child.get_label():
                    child.get_style_context().remove_class("suggested-action")
                    child.get_style_context().add_class("destructive-action")
        self.append(nav)


# ════════════════════════════════════════════════════════════════════
# ЭКРАН 8 — ПРОГРЕСС УСТАНОВКИ
# ════════════════════════════════════════════════════════════════════
class PageInstalling(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.append(make_header("Установка CryOS...", "Пожалуйста, подождите"))

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_vexpand(True)
        content.set_margin_top(40); content.set_margin_bottom(16)
        content.set_margin_start(64); content.set_margin_end(64)
        content.set_valign(Gtk.Align.CENTER)

        self._step = Gtk.Label()
        self._step.set_markup('<span font="12">Подготовка...</span>')
        self._step.set_halign(Gtk.Align.START)
        content.append(self._step)

        self._bar = Gtk.ProgressBar()
        self._bar.set_show_text(True)
        self._bar.set_size_request(-1, 28)
        content.append(self._bar)

        self._log = Gtk.TextView()
        self._log.set_editable(False); self._log.set_monospace(True)
        scroll = Gtk.ScrolledWindow(); scroll.set_size_request(-1, 150)
        scroll.set_child(self._log)
        content.append(scroll)

        self.append(content)

    def set_step(self, text: str, frac: float):
        self._step.set_markup(f'<span font="12">{text}</span>')
        self._bar.set_fraction(frac)
        self._bar.set_text(f"{int(frac*100)}%")

    def log(self, text: str):
        buf = self._log.get_buffer()
        buf.insert(buf.get_end_iter(), text + "\n")
        mark = buf.create_mark(None, buf.get_end_iter(), False)
        self._log.scroll_to_mark(mark, 0, False, 0, 0)


# ════════════════════════════════════════════════════════════════════
# ЭКРАН 9 — ГОТОВО
# ════════════════════════════════════════════════════════════════════
class PageDone(Gtk.Box):
    def __init__(self, success: bool, msg: str = "", other_os: list = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title = "CryOS установлена!" if success else "Ошибка установки"
        self.append(make_header(title, ""))

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_vexpand(True)
        content.set_halign(Gtk.Align.CENTER); content.set_valign(Gtk.Align.CENTER)
        icon = Gtk.Label()
        icon.set_markup(f'<span font="56">{"✅" if success else "❌"}</span>')
        content.append(icon)

        if success:
            os_note = ""
            if other_os:
                os_note = (
                    f"\n\nВ меню GRUB будут доступны:\n"
                    + "\n".join(f"  • {o}" for o in other_os)
                    + "\n  • CryOS"
                )
            lbl = Gtk.Label()
            lbl.set_markup(
                '<span font="11">'
                'CryOS успешно установлена!\n\n'
                'Извлеките флешку и нажмите «Перезагрузить».\n'
                'При загрузке появится меню GRUB —\n'
                'выберите <b>CryOS</b>.'
                + os_note + '</span>')
            lbl.set_justify(Gtk.Justification.CENTER)
            content.append(lbl)
        else:
            lbl = Gtk.Label()
            lbl.set_markup(
                f'<span foreground="#CC0000">{msg}\n\n'
                'Попробуйте запустить установщик заново.\n'
                'Проверьте подключение и свободное место.</span>')
            lbl.set_justify(Gtk.Justification.CENTER)
            content.append(lbl)

        self.append(content)
        self.append(Gtk.Separator())
        nb = Gtk.Box(spacing=8)
        nb.set_halign(Gtk.Align.END)
        nb.set_margin_top(10); nb.set_margin_bottom(12); nb.set_margin_end(24)
        if success:
            btn = Gtk.Button(label="🔄 Перезагрузить")
            btn.add_css_class("suggested-action")
            btn.set_size_request(160, 34)
            btn.connect("clicked", lambda b: os.system("reboot"))
        else:
            btn = Gtk.Button(label="Закрыть")
            btn.set_size_request(120, 34)
            btn.connect("clicked", lambda b: Gtk.main_quit())
        nb.append(btn)
        self.append(nb)


# ════════════════════════════════════════════════════════════════════
# ДВИЖОК УСТАНОВКИ
# ════════════════════════════════════════════════════════════════════
class InstallerEngine:
    def __init__(self, disk, size_mb, user, mode,
                 on_step, on_log, on_done):
        self.disk    = disk
        self.size_mb = size_mb
        self.user    = user
        self.mode    = mode
        self.on_step = on_step
        self.on_log  = on_log
        self.on_done = on_done
        self._tgt    = CRYOS_DST
        self._uefi   = is_uefi()

    def run(self):
        threading.Thread(target=self._install, daemon=True).start()

    def _install(self):
        try:
            self._step("Создание раздела...", 0.05)
            part_dev, efi_dev = self._partition()

            self._step("Форматирование...", 0.15)
            self._format(part_dev, efi_dev)

            self._step("Монтирование...", 0.20)
            self._mount(part_dev, efi_dev)

            self._step("Копирование системы...", 0.25)
            self._copy()

            self._step("Настройка системы...", 0.75)
            self._configure(part_dev)

            self._step("Создание пользователя...", 0.82)
            self._create_user()

            self._step("Установка GRUB...", 0.90)
            self._install_grub(efi_dev)

            self._step("Финальная настройка...", 0.97)
            self._unmount()

            other = detect_other_os()
            GLib.idle_add(self.on_done, True, "", other)

        except Exception as e:
            self._log(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
            try: self._unmount()
            except: pass
            GLib.idle_add(self.on_done, False, str(e), [])

    def _step(self, text, frac):
        self._log(text)
        GLib.idle_add(self.on_step, text, frac)

    def _log(self, text):
        GLib.idle_add(self.on_log, text)

    def _run(self, cmd, **kw) -> str:
        self._log("$ " + " ".join(str(c) for c in cmd))
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=600, **kw)
        if r.stdout.strip(): self._log(r.stdout.strip())
        if r.stderr.strip(): self._log(r.stderr.strip())
        if r.returncode != 0:
            raise RuntimeError(f"{cmd[0]} вернул код {r.returncode}: {r.stderr.strip()}")
        return r.stdout.strip()

    def _partition(self) -> tuple[str, str | None]:
        dev = self.disk["dev"]
        efi_dev = None

        if self.mode == "whole":
            # Стереть и создать GPT / MBR
            table = "gpt" if self._uefi else "msdos"
            self._run(["parted", "-s", dev, "mklabel", table])
            if self._uefi:
                # EFI раздел 512 МБ + основной
                self._run(["parted", "-s", dev, "mkpart", "primary",
                           "fat32", "1MiB", "513MiB"])
                self._run(["parted", "-s", dev, "set", "1", "esp", "on"])
                self._run(["parted", "-s", dev, "mkpart", "primary",
                           "ext4", "513MiB", f"{self.size_mb}MiB"])
                parts = self._get_parts(dev)
                efi_dev  = f"/dev/{parts[0]}"
                part_dev = f"/dev/{parts[1]}"
            else:
                self._run(["parted", "-s", dev, "mkpart", "primary",
                           "ext4", "1MiB", f"{self.size_mb}MiB"])
                parts    = self._get_parts(dev)
                part_dev = f"/dev/{parts[-1]}"
        else:
            # alongside — найти свободное место
            r = subprocess.run(
                ["parted", "-s", dev, "unit", "MiB", "print", "free"],
                capture_output=True, text=True)
            self._log(r.stdout)
            start = end = None
            for line in r.stdout.splitlines():
                if "Free Space" in line:
                    p = line.split()
                    try:
                        start = int(float(p[0].replace("MiB","")))
                        end   = start + self.size_mb
                        break
                    except: pass
            if start is None:
                start = 1; end = self.size_mb

            if self._uefi:
                # Проверяем есть ли уже EFI раздел
                efi_dev = self._find_efi(dev)
                if not efi_dev:
                    # Создаём EFI раздел
                    self._run(["parted", "-s", dev, "mkpart", "primary",
                               "fat32", f"{start}MiB", f"{start+512}MiB"])
                    self._run(["parted", "-s", dev, "set",
                               str(len(self._get_parts(dev))), "esp", "on"])
                    efi_dev = f"/dev/{self._get_parts(dev)[-1]}"
                    start  += 512

                self._run(["parted", "-s", dev, "mkpart", "primary",
                           "ext4", f"{start}MiB", f"{end}MiB"])
            else:
                self._run(["parted", "-s", dev, "mkpart", "primary",
                           "ext4", f"{start}MiB", f"{end}MiB"])

            parts    = self._get_parts(dev)
            part_dev = f"/dev/{parts[-1]}"

        self._log(f"Основной раздел: {part_dev}")
        if efi_dev: self._log(f"EFI раздел: {efi_dev}")
        # Даём ядру обновить таблицу
        subprocess.run(["partprobe", dev], capture_output=True)
        time.sleep(1)
        return part_dev, efi_dev

    def _find_efi(self, dev: str) -> str | None:
        r = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,PARTTYPE", dev],
            capture_output=True, text=True)
        try:
            data = json.loads(r.stdout)
            for child in data["blockdevices"][0].get("children", []):
                pt = (child.get("parttype") or "").lower()
                if "ef00" in pt or "efi" in pt:
                    return f"/dev/{child['name']}"
        except: pass
        return None

    def _get_parts(self, dev: str) -> list[str]:
        r = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,TYPE", dev],
            capture_output=True, text=True)
        data = json.loads(r.stdout)
        return [c["name"] for c in data["blockdevices"][0].get("children", [])
                if c["type"] == "part"]

    def _format(self, part_dev: str, efi_dev: str | None):
        self._run(["mkfs.ext4", "-L", "CryOS", "-F", part_dev])
        if efi_dev and self._uefi:
            self._run(["mkfs.fat", "-F32", efi_dev])

    def _mount(self, part_dev: str, efi_dev: str | None):
        os.makedirs(self._tgt, exist_ok=True)
        self._run(["mount", part_dev, self._tgt])
        if efi_dev and self._uefi:
            efi_mnt = f"{self._tgt}/boot/efi"
            os.makedirs(efi_mnt, exist_ok=True)
            self._run(["mount", efi_dev, efi_mnt])

    def _copy(self):
        live = "/run/live/medium"
        if Path(live).exists():
            self._log("Копируем live-систему...")
            self._run([
                "rsync", "-aAX",
                "--exclude=/proc", "--exclude=/sys",
                "--exclude=/dev",  "--exclude=/run",
                "--exclude=/mnt",  "--exclude=/media",
                "--exclude=/tmp",  "--exclude=/swapfile",
                f"{live}/", self._tgt])
        else:
            self._log("Копируем CryOS (dev-режим)...")
            dst = f"{self._tgt}/usr/share/cryos"
            os.makedirs(dst, exist_ok=True)
            self._run(["rsync", "-a",
                       str(CRYOS_SRC) + "/", dst])

    def _configure(self, part_dev: str):
        tgt  = self._tgt
        hostname = self.user["hostname"]

        Path(f"{tgt}/etc/hostname").write_text(hostname + "\n")
        Path(f"{tgt}/etc/hosts").write_text(
            f"127.0.0.1   localhost\n127.0.1.1   {hostname}\n::1   localhost\n")

        # UUID для fstab
        r = subprocess.run(["blkid", "-s", "UUID", "-o", "value", part_dev],
                           capture_output=True, text=True)
        uuid = r.stdout.strip()
        fstab = f"UUID={uuid}  /  ext4  defaults,noatime  0  1\n"
        if self._uefi:
            r2 = subprocess.run(
                ["findmnt", "-n", "-o", "SOURCE", f"{tgt}/boot/efi"],
                capture_output=True, text=True)
            efi_src = r2.stdout.strip()
            if efi_src:
                r3 = subprocess.run(["blkid", "-s", "UUID", "-o", "value", efi_src],
                                    capture_output=True, text=True)
                efi_uuid = r3.stdout.strip()
                fstab += f"UUID={efi_uuid}  /boot/efi  vfat  umask=0077  0  1\n"
        fstab += "tmpfs  /tmp  tmpfs  defaults  0  0\n"
        Path(f"{tgt}/etc/fstab").write_text(fstab)
        self._log(f"fstab: UUID={uuid}")

        # XSession
        xsess = Path(f"{tgt}/usr/share/xsessions")
        xsess.mkdir(parents=True, exist_ok=True)
        (xsess / "cryos.desktop").write_text(
            "[Desktop Entry]\nName=CryOS\n"
            "Exec=python3 /usr/share/cryos/system/session/session.py\n"
            "Type=XSession\n")

        # LightDM
        ldm = Path(f"{tgt}/etc/lightdm")
        ldm.mkdir(parents=True, exist_ok=True)
        (ldm / "lightdm.conf").write_text(
            f"[Seat:*]\nautologin-user={self.user['username']}\n"
            "autologin-user-timeout=0\nuser-session=cryos\n")

        # locale
        Path(f"{tgt}/etc/locale.conf").write_text("LANG=ru_RU.UTF-8\n")

        # os-prober включаем
        grub_default = Path(f"{tgt}/etc/default/grub")
        if grub_default.exists():
            txt = grub_default.read_text()
            if "GRUB_DISABLE_OS_PROBER" not in txt:
                txt += "\nGRUB_DISABLE_OS_PROBER=false\n"
            grub_default.write_text(txt)
        else:
            grub_default.parent.mkdir(parents=True, exist_ok=True)
            grub_default.write_text(
                'GRUB_DEFAULT=0\nGRUB_TIMEOUT=10\n'
                'GRUB_DISTRIBUTOR="CryOS"\n'
                'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n'
                'GRUB_DISABLE_OS_PROBER=false\n')

        self._log("Конфигурация завершена")

    def _create_user(self):
        u   = self.user
        tgt = self._tgt
        grp = "sudo,audio,video,plugdev,input,netdev,cdrom,dialout,users"
        self._run(["chroot", tgt,
                   "useradd", "-m", "-s", "/bin/bash",
                   "-c", u["fullname"], "-G", grp, u["username"]])
        proc = subprocess.Popen(["chroot", tgt, "chpasswd"],
                                stdin=subprocess.PIPE, capture_output=True)
        proc.communicate(f"{u['username']}:{u['password']}".encode())
        sd = Path(f"{tgt}/etc/sudoers.d")
        sd.mkdir(parents=True, exist_ok=True)
        sf = sd / f"cryos-{u['username']}"
        sf.write_text(f"{u['username']} ALL=(ALL:ALL) ALL\n")
        sf.chmod(0o440)
        self._log(f"Пользователь {u['username']} создан")

    def _install_grub(self, efi_dev: str | None):
        tgt = self._tgt
        dev = self.disk["dev"]
        # Bind mounts для chroot
        for src, dst in [("/proc","/proc"),("/sys","/sys"),("/dev","/dev"),
                         ("/dev/pts","/dev/pts"),("/run","/run")]:
            subprocess.run(["mount","--bind",src,f"{tgt}{dst}"],
                           capture_output=True, check=False)
        try:
            if self._uefi:
                self._run(["chroot", tgt,
                           "grub-install",
                           "--target=x86_64-efi",
                           "--efi-directory=/boot/efi",
                           "--bootloader-id=CryOS",
                           "--recheck"])
            else:
                self._run(["chroot", tgt,
                           "grub-install",
                           "--target=i386-pc",
                           "--recheck", dev])
            # os-prober найдёт Mint / Arch / Windows
            subprocess.run(["chroot", tgt, "apt-get", "install",
                            "-y", "os-prober"],
                           capture_output=True, timeout=120)
            self._run(["chroot", tgt, "update-grub"])
            self._log("GRUB установлен. Другие ОС добавлены в меню.")
        finally:
            for mp in ["/dev/pts","/dev","/run","/sys","/proc"]:
                subprocess.run(["umount", f"{tgt}{mp}"],
                               check=False, capture_output=True)

    def _unmount(self):
        subprocess.run(["umount", "-R", self._tgt],
                       check=False, capture_output=True)


# ════════════════════════════════════════════════════════════════════
# ГЛАВНОЕ ОКНО
# ════════════════════════════════════════════════════════════════════
class InstallerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Установка CryOS")
        self.set_default_size(700, 540)
        self.set_resizable(False)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        self._stack.set_transition_duration(200)

        self._disk    = None
        self._size_mb = 0
        self._user    = {}
        self._mode    = "alongside"
        self._other_os: list[str] = []

        self._page_installing = PageInstalling()

        pages = [
            ("welcome",    PageWelcome(on_next=lambda: self._go("network"))),
            ("installing", self._page_installing),
        ]
        for name, page in pages:
            self._stack.add_named(page, name)

        self.set_child(self._stack)
        self._build_network()
        self._go("welcome")

    def _build_network(self):
        p = PageNetwork(
            on_next=lambda: self._go("check"),
            on_back=lambda: self._go("welcome"))
        self._stack.add_named(p, "network")

        p2 = PageCheck(
            on_next=lambda: self._go("mode"),
            on_back=lambda: self._go("network"))
        self._stack.add_named(p2, "check")

        self._page_mode = PageInstallMode(
            on_next=self._from_mode,
            on_back=lambda: self._go("check"))
        self._stack.add_named(self._page_mode, "mode")

    def _from_mode(self, mode: str):
        self._mode = mode
        p = PageDisk(
            on_next=self._from_disk,
            on_back=lambda: self._go("mode"),
            mode=mode)
        self._stack.add_named(p, "disk")
        self._go("disk")

    def _from_disk(self, disk, size_mb):
        self._disk    = disk
        self._size_mb = size_mb
        p = PageUser(
            on_next=self._from_user,
            on_back=lambda: self._go("disk"))
        self._stack.add_named(p, "user")
        self._go("user")

    def _from_user(self, user):
        self._user = user
        p = PageConfirm(
            disk=self._disk,
            size_mb=self._size_mb,
            user=self._user,
            mode=self._mode,
            on_install=self._start_install,
            on_back=lambda: self._go("user"))
        self._stack.add_named(p, "confirm")
        self._go("confirm")

    def _start_install(self):
        self._go("installing")
        engine = InstallerEngine(
            disk    = self._disk,
            size_mb = self._size_mb,
            user    = self._user,
            mode    = self._mode,
            on_step = self._page_installing.set_step,
            on_log  = self._page_installing.log,
            on_done = self._install_done)
        engine.run()

    def _install_done(self, success: bool, msg: str, other_os: list):
        done = PageDone(success, msg, other_os)
        self._stack.add_named(done, "done")
        self._go("done")

    def _go(self, name: str):
        self._stack.set_visible_child_name(name)


# ════════════════════════════════════════════════════════════════════
# ЗАПУСК
# ════════════════════════════════════════════════════════════════════
class InstallerApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="org.cryos.Installer",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        load_css()
        win = InstallerWindow(self)
        win.present()


def main():
    if os.geteuid() != 0:
        if shutil.which("pkexec"):
            os.execvp("pkexec", ["pkexec", sys.executable] + sys.argv)
        else:
            print("Требуются права root: sudo python3 main.py", file=sys.stderr)
            sys.exit(1)
    app = InstallerApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
