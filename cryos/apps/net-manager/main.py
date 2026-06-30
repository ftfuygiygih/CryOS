#!/usr/bin/env python3
"""
CryOS Network Manager  —  apps/net-manager/main.py
====================================================
Список Wi-Fi сетей, подключение с паролем,
статус Ethernet, VPN, IP/шлюз/DNS.
Зависимости: python3-gi, NetworkManager (nmcli)
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio
import subprocess, sys, re
from pathlib import Path

CRYOS_ROOT = Path(__file__).parent.parent.parent
THEME_CSS  = CRYOS_ROOT / "system" / "theme" / "gtk.css"


def nmcli(*args) -> str:
    try:
        return subprocess.check_output(
            ["nmcli", *args], text=True, stderr=subprocess.DEVNULL
        )
    except Exception:
        return ""


def get_wifi_list() -> list[dict]:
    out = nmcli("-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list")
    networks = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if not parts:
            continue
        in_use = "*" in line
        ssid = parts[0] if parts[0] != "--" else "(скрытая)"
        signal = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        security = parts[2] if len(parts) > 2 else "Открытая"
        networks.append({
            "ssid": ssid, "signal": signal,
            "security": security, "in_use": in_use
        })
    return networks


def get_connection_info() -> dict:
    out = nmcli("-f", "IP4.ADDRESS,IP4.GATEWAY,IP4.DNS", "connection", "show", "--active")
    info = {}
    for line in out.splitlines():
        if "IP4.ADDRESS" in line:
            info["ip"] = line.split(":", 1)[1].strip()
        elif "IP4.GATEWAY" in line:
            info["gateway"] = line.split(":", 1)[1].strip()
        elif "IP4.DNS" in line and "dns" not in info:
            info["dns"] = line.split(":", 1)[1].strip()
    return info


def signal_icon(sig: int) -> str:
    if sig >= 75: return "▂▄▆█"
    if sig >= 50: return "▂▄▆░"
    if sig >= 25: return "▂▄░░"
    return "▂░░░"


class WifiRow(Gtk.Box):
    def __init__(self, net: dict, connect_cb):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.set_margin_top(3); self.set_margin_bottom(3)
        self.net = net

        active_mark = "✓ " if net["in_use"] else "   "
        ssid_lbl = Gtk.Label(label=f"{active_mark}{net['ssid']}")
        ssid_lbl.set_hexpand(True)
        ssid_lbl.set_halign(Gtk.Align.START)
        self.append(ssid_lbl)

        sig_lbl = Gtk.Label(label=signal_icon(net["signal"]))
        sig_lbl.set_markup(
            f'<span font="Monospace 9" foreground="#000080">'
            f'{signal_icon(net["signal"])}</span>'
        )
        self.append(sig_lbl)

        lock = "🔒" if net["security"] not in ("--", "Открытая") else "🔓"
        self.append(Gtk.Label(label=lock))

        if not net["in_use"]:
            btn = Gtk.Button(label="Подключить")
            btn.set_has_frame(False)
            btn.add_css_class("flat")
            btn.connect("clicked", lambda *_: connect_cb(net))
            self.append(btn)
        else:
            disc_btn = Gtk.Button(label="Отключить")
            disc_btn.set_has_frame(False)
            disc_btn.connect("clicked", lambda *_: nmcli("device", "disconnect", "wifi"))
            self.append(disc_btn)


class NetManagerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CryOS Сетевой менеджер")
        self.set_default_size(580, 500)
        self.add_css_class("cry-window")

        notebook = Gtk.Notebook()

        # ── Wi-Fi вкладка ─────────────────────────────────────────
        wifi_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        wifi_tb = Gtk.Box(spacing=4)
        wifi_tb.set_margin_start(8); wifi_tb.set_margin_top(6); wifi_tb.set_margin_bottom(4)

        self.wifi_switch = Gtk.Switch()
        self.wifi_switch.set_active(True)
        self.wifi_switch.connect("notify::active", self._toggle_wifi)
        wifi_tb.append(Gtk.Label(label="Wi-Fi:"))
        wifi_tb.append(self.wifi_switch)

        refresh_btn = Gtk.Button(label="🔄 Обновить")
        refresh_btn.connect("clicked", lambda *_: self._refresh_wifi())
        wifi_tb.append(refresh_btn)
        wifi_outer.append(wifi_tb)

        scroll_wifi = Gtk.ScrolledWindow()
        scroll_wifi.set_vexpand(True)
        self._wifi_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._wifi_list_box.set_margin_start(8); self._wifi_list_box.set_margin_end(8)
        scroll_wifi.set_child(self._wifi_list_box)
        wifi_outer.append(scroll_wifi)

        notebook.append_page(wifi_outer, Gtk.Label(label="📶 Wi-Fi"))

        # ── Статус вкладка ────────────────────────────────────────
        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        status_box.set_margin_top(12); status_box.set_margin_start(16); status_box.set_margin_end(16)

        lbl = Gtk.Label(); lbl.set_markup('<b>Статус подключения</b>')
        lbl.set_halign(Gtk.Align.START); status_box.append(lbl)

        self._status_grid = Gtk.Grid()
        self._status_grid.set_column_spacing(12)
        self._status_grid.set_row_spacing(6)
        status_box.append(self._status_grid)

        refresh_status = Gtk.Button(label="🔄 Обновить")
        refresh_status.connect("clicked", lambda *_: self._refresh_status())
        status_box.append(refresh_status)

        notebook.append_page(status_box, Gtk.Label(label="📊 Статус"))

        # ── VPN вкладка ───────────────────────────────────────────
        vpn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vpn_box.set_margin_top(12); vpn_box.set_margin_start(16)

        vpn_lbl = Gtk.Label(); vpn_lbl.set_markup('<b>VPN подключения</b>')
        vpn_lbl.set_halign(Gtk.Align.START); vpn_box.append(vpn_lbl)

        self._vpn_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vpn_box.append(self._vpn_list)

        add_vpn_btn = Gtk.Button(label="+ Добавить VPN")
        add_vpn_btn.connect("clicked", self._add_vpn)
        vpn_box.append(add_vpn_btn)

        notebook.append_page(vpn_box, Gtk.Label(label="🔐 VPN"))

        self.set_child(notebook)
        self._refresh_wifi()
        self._refresh_status()
        self._refresh_vpn()

    def _refresh_wifi(self):
        # Очищаем список
        child = self._wifi_list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._wifi_list_box.remove(child)
            child = next_child

        nets = get_wifi_list()
        if not nets:
            self._wifi_list_box.append(
                Gtk.Label(label="Wi-Fi недоступен или nmcli не найден")
            )
            return
        for net in nets:
            row = WifiRow(net, self._connect_wifi)
            self._wifi_list_box.append(row)
            self._wifi_list_box.append(
                Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            )

    def _connect_wifi(self, net: dict):
        if net["security"] not in ("--", "Открытая", ""):
            dlg = Gtk.Dialog(
                title=f"Подключение к {net['ssid']}",
                transient_for=self, modal=True
            )
            dlg.add_button("Отмена", Gtk.ResponseType.CANCEL)
            dlg.add_button("Подключить", Gtk.ResponseType.OK)
            box = dlg.get_content_area()
            box.set_margin_top(12); box.set_margin_bottom(12)
            box.set_margin_start(16); box.set_margin_end(16)
            box.set_spacing(8)
            box.append(Gtk.Label(label=f"Пароль для сети «{net['ssid']}»:"))
            pw_entry = Gtk.Entry()
            pw_entry.set_visibility(False)
            pw_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            pw_entry.connect("activate", lambda e: dlg.response(Gtk.ResponseType.OK))
            box.append(pw_entry)
            if dlg.run() == Gtk.ResponseType.OK:
                password = pw_entry.get_text()
                dlg.destroy()
                self._do_connect(net["ssid"], password)
            else:
                dlg.destroy()
        else:
            self._do_connect(net["ssid"], None)

    def _do_connect(self, ssid: str, password: str | None):
        cmd = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            cmd += ["password", password]
        subprocess.Popen(cmd)
        GLib.timeout_add(2000, self._refresh_wifi)

    def _toggle_wifi(self, switch, param):
        state = "on" if switch.get_active() else "off"
        nmcli("radio", "wifi", state)

    def _refresh_status(self):
        # Очищаем грид
        child = self._status_grid.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._status_grid.remove(child)
            child = next_child

        info = get_connection_info()
        rows = [
            ("IP адрес:", info.get("ip", "—")),
            ("Шлюз:",     info.get("gateway", "—")),
            ("DNS:",      info.get("dns", "—")),
        ]
        # Ethernet статус
        eth_out = nmcli("-f", "DEVICE,STATE", "device")
        eth_status = "—"
        for line in eth_out.splitlines():
            if "eth" in line.lower() or "enp" in line.lower():
                eth_status = "Подключён" if "connected" in line else "Отключён"
                break
        rows.append(("Ethernet:", eth_status))

        for i, (key, val) in enumerate(rows):
            k = Gtk.Label(); k.set_markup(f'<b>{key}</b>')
            k.set_halign(Gtk.Align.START)
            v = Gtk.Label(label=val)
            v.set_halign(Gtk.Align.START)
            self._status_grid.attach(k, 0, i, 1, 1)
            self._status_grid.attach(v, 1, i, 1, 1)

    def _refresh_vpn(self):
        out = nmcli("-f", "NAME,TYPE,STATE", "connection", "show")
        child = self._vpn_list.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._vpn_list.remove(child)
            child = next_child

        found = False
        for line in out.splitlines():
            if "vpn" in line.lower() or "wireguard" in line.lower():
                parts = line.split()
                name  = parts[0] if parts else "VPN"
                state = "активен" if "activated" in line else "отключён"
                row = Gtk.Box(spacing=8)
                row.append(Gtk.Label(label=f"🔐 {name} ({state})"))
                toggle = Gtk.Button(
                    label="Отключить" if state == "активен" else "Подключить"
                )
                toggle.connect("clicked", lambda b, n=name: self._toggle_vpn(n))
                row.append(toggle)
                self._vpn_list.append(row)
                found = True

        if not found:
            self._vpn_list.append(Gtk.Label(label="Нет настроенных VPN подключений"))

    def _toggle_vpn(self, name: str):
        nmcli("connection", "up", name)
        GLib.timeout_add(1500, self._refresh_vpn)

    def _add_vpn(self, *_):
        dlg = Gtk.Dialog(title="Добавить VPN", transient_for=self, modal=True)
        dlg.add_button("Отмена", Gtk.ResponseType.CANCEL)
        dlg.add_button("Добавить", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_margin_top(12); box.set_margin_bottom(12)
        box.set_margin_start(16); box.set_margin_end(16)
        box.set_spacing(8)
        box.append(Gtk.Label(label="Тип:"))
        vpn_type = Gtk.ComboBoxText()
        for t in ["OpenVPN", "WireGuard", "L2TP", "PPTP"]:
            vpn_type.append_text(t)
        vpn_type.set_active(0)
        box.append(vpn_type)
        box.append(Gtk.Label(label="Название:"))
        name_e = Gtk.Entry(placeholder_text="Моё VPN")
        box.append(name_e)
        box.append(Gtk.Label(label="Сервер:"))
        host_e = Gtk.Entry(placeholder_text="vpn.example.com")
        box.append(host_e)
        if dlg.run() == Gtk.ResponseType.OK:
            pass  # TODO: nmcli connection add
        dlg.destroy()


class NetManagerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.cryos.NetManager",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        if THEME_CSS.exists():
            p = Gtk.CssProvider(); p.load_from_path(str(THEME_CSS))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        NetManagerWindow(self).present()


def main():
    NetManagerApp().run(sys.argv)

if __name__ == "__main__":
    main()
