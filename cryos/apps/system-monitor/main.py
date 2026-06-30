#!/usr/bin/env python3
"""
CryOS System Monitor  —  apps/system-monitor/main.py
=====================================================
CPU, RAM, Swap — графики в реальном времени.
Список процессов (PID, имя, CPU%, MEM%).
Завершение процесса, дискстат, сетевой трафик.
Стиль: Win98 Task Manager.
Зависимости: python3-gi, python3-psutil
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio
import sys, time
from pathlib import Path
from collections import deque

CRYOS_ROOT = Path(__file__).parent.parent.parent
THEME_CSS  = CRYOS_ROOT / "system" / "theme" / "gtk.css"

try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    HAVE_PSUTIL = False

HISTORY = 60   # точек в графике
REFRESH = 1500 # мс

# Цвета графиков
COLOR_CPU  = "#000080"
COLOR_RAM  = "#008000"
COLOR_SWAP = "#800000"
COLOR_NET  = "#800080"


# ── Мини-график (холст) ───────────────────────────────────────────
class SparkGraph(Gtk.DrawingArea):
    """Маленький линейный график истории значений."""

    def __init__(self, color: str, label: str, max_val: float = 100.0):
        super().__init__()
        self.set_size_request(200, 60)
        self.set_vexpand(False)
        self._data: deque[float] = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._color = self._parse_color(color)
        self._label = label
        self._max   = max_val
        self.set_draw_func(self._draw)

    @staticmethod
    def _parse_color(hex_color: str):
        h = hex_color.lstrip("#")
        return tuple(int(h[i:i+2], 16)/255 for i in (0, 2, 4))

    def push(self, val: float):
        self._data.append(val)
        self.queue_draw()

    def _draw(self, area, cr, w, h):
        # Фон — белый с рамкой
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.set_source_rgb(0.5, 0.5, 0.5)
        cr.rectangle(0, 0, w, h)
        cr.stroke()

        # Сетка
        cr.set_source_rgba(0.8, 0.8, 0.8, 0.5)
        cr.set_line_width(0.5)
        for pct in (25, 50, 75):
            y = h - h * pct / 100
            cr.move_to(0, y); cr.line_to(w, y)
        cr.stroke()

        # Линия данных
        data = list(self._data)
        if not data:
            return
        cr.set_source_rgb(*self._color)
        cr.set_line_width(1.5)
        step = w / max(len(data) - 1, 1)
        for i, val in enumerate(data):
            x = i * step
            y = h - (val / max(self._max, 1)) * h
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()

        # Подпись
        cr.set_source_rgb(0, 0, 0)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(9)
        last = data[-1] if data else 0
        cr.move_to(4, 12)
        cr.show_text(f"{self._label}: {last:.1f}%")


# ── Вкладка производительности ────────────────────────────────────
class PerfTab(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        self.set_margin_start(8)
        self.set_margin_end(8)

        # Заголовок
        hdr = Gtk.Label()
        hdr.set_markup('<b>Производительность системы</b>')
        hdr.set_halign(Gtk.Align.START)
        self.append(hdr)

        # Графики
        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(8)

        self.cpu_graph  = SparkGraph(COLOR_CPU,  "CPU",  100)
        self.ram_graph  = SparkGraph(COLOR_RAM,  "RAM",  100)
        self.swap_graph = SparkGraph(COLOR_SWAP, "Swap", 100)
        self.net_graph  = SparkGraph(COLOR_NET,  "Сеть", 100)

        graph_data = [
            ("ЦП (CPU)", self.cpu_graph,  0, 0),
            ("Память",   self.ram_graph,  0, 1),
            ("Своп",     self.swap_graph, 1, 0),
            ("Сеть",     self.net_graph,  1, 1),
        ]
        for label, graph, col, row in graph_data:
            frame = Gtk.Frame(label=label)
            frame.set_child(graph)
            grid.attach(frame, col, row, 1, 1)

        self.append(grid)

        # Числовые метки
        nums = Gtk.Grid()
        nums.set_column_spacing(20)
        nums.set_row_spacing(4)

        self.cpu_lbl  = self._stat_label("ЦП:", nums, 0)
        self.ram_lbl  = self._stat_label("ОЗУ:", nums, 1)
        self.swap_lbl = self._stat_label("Своп:", nums, 2)
        self.up_lbl   = self._stat_label("Аптайм:", nums, 3)
        self.append(nums)

        self._net_prev = (0, 0)
        self._net_prev_time = time.time()

    def _stat_label(self, text: str, grid: Gtk.Grid, row: int) -> Gtk.Label:
        key = Gtk.Label(label=text)
        key.set_halign(Gtk.Align.START)
        val = Gtk.Label(label="—")
        val.set_halign(Gtk.Align.START)
        grid.attach(key, 0, row, 1, 1)
        grid.attach(val, 1, row, 1, 1)
        return val

    def update(self):
        if not HAVE_PSUTIL:
            return
        # CPU
        cpu = psutil.cpu_percent()
        self.cpu_graph.push(cpu)
        self.cpu_lbl.set_text(f"{cpu:.1f}%  ({psutil.cpu_count()} ядер)")

        # RAM
        mem = psutil.virtual_memory()
        ram_pct = mem.percent
        self.ram_graph.push(ram_pct)
        used = mem.used // (1024**2)
        total = mem.total // (1024**2)
        self.ram_lbl.set_text(f"{used} МБ / {total} МБ ({ram_pct:.1f}%)")

        # Swap
        swap = psutil.swap_memory()
        self.swap_graph.push(swap.percent)
        su = swap.used // (1024**2)
        st = swap.total // (1024**2)
        self.swap_lbl.set_text(f"{su} МБ / {st} МБ ({swap.percent:.1f}%)")

        # Сеть
        net = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._net_prev_time
        if dt > 0 and self._net_prev != (0, 0):
            rx_speed = (net.bytes_recv - self._net_prev[0]) / dt / 1024
            tx_speed = (net.bytes_sent - self._net_prev[1]) / dt / 1024
            pct = min(rx_speed / 1000 * 100, 100)
            self.net_graph.push(pct)
        self._net_prev = (net.bytes_recv, net.bytes_sent)
        self._net_prev_time = now

        # Аптайм
        boot = psutil.boot_time()
        up = int(time.time() - boot)
        h, m = divmod(up // 60, 60)
        d, h = divmod(h, 24)
        self.up_lbl.set_text(f"{d}д {h}ч {m}м")


# ── Вкладка процессов ────────────────────────────────────────────
class ProcessTab(Gtk.Box):
    COLS = ["PID", "Имя", "CPU%", "MEM%", "Статус"]

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Тулбар
        tb = Gtk.Box(spacing=4)
        tb.set_margin_start(4)
        tb.set_margin_top(4)
        tb.set_margin_bottom(4)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Фильтр по имени…")
        self.search.set_hexpand(True)
        self.search.connect("changed", lambda *_: self._filter())
        tb.append(self.search)

        kill_btn = Gtk.Button(label="⛔ Завершить")
        kill_btn.add_css_class("destructive-action")
        kill_btn.connect("clicked", self._kill_selected)
        tb.append(kill_btn)

        refresh_btn = Gtk.Button(label="🔄")
        refresh_btn.connect("clicked", lambda *_: self.refresh())
        tb.append(refresh_btn)

        self.append(tb)

        # TreeView
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        self.store = Gtk.ListStore(int, str, float, float, str)
        self.view  = Gtk.TreeView(model=self.store)
        self.view.set_rules_hint(True)

        for i, (col_name, col_type) in enumerate(zip(
            self.COLS, [int, str, float, float, str]
        )):
            if col_type in (int, float):
                renderer = Gtk.CellRendererText()
                renderer.set_property("xalign", 1.0)
            else:
                renderer = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(col_name, renderer, text=i)
            col.set_sort_column_id(i)
            col.set_resizable(True)
            self.view.append_column(col)

        scroll.set_child(self.view)
        self.append(scroll)

        # Фильтрованная модель
        self._filter_model = self.store.filter_new()
        self._filter_model.set_visible_func(self._row_visible)
        self.view.set_model(Gtk.TreeModelSort(model=self._filter_model))

        self.refresh()

    def refresh(self):
        self.store.clear()
        if not HAVE_PSUTIL:
            return
        procs = []
        for proc in psutil.process_iter(["pid","name","cpu_percent","memory_percent","status"]):
            try:
                info = proc.info
                procs.append((
                    info["pid"],
                    info["name"][:40],
                    round(info["cpu_percent"] or 0, 1),
                    round(info["memory_percent"] or 0, 2),
                    info["status"],
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x[2], reverse=True)
        for row in procs:
            self.store.append(row)

    def _filter(self):
        self._filter_model.refilter()

    def _row_visible(self, model, iter, data):
        text = self.search.get_text().lower()
        if not text:
            return True
        name = model.get_value(iter, 1).lower()
        return text in name

    def _kill_selected(self, *_):
        sel = self.view.get_selection()
        model, it = sel.get_selected()
        if it is None:
            return
        pid = model.get_value(it, 0)
        name = model.get_value(it, 1)
        dlg = Gtk.MessageDialog(
            transient_for=self.get_ancestor(Gtk.Window),
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Завершить процесс '{name}' (PID {pid})?"
        )
        if dlg.run() == Gtk.ResponseType.YES:
            try:
                psutil.Process(pid).terminate()
            except Exception as e:
                pass
            GLib.timeout_add(500, self.refresh)
        dlg.destroy()


# ── Вкладка дисков ───────────────────────────────────────────────
class DiskTab(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        self.store = Gtk.ListStore(str, str, str, str, str, str)
        view = Gtk.TreeView(model=self.store)
        for i, name in enumerate(["Устройство","Точка монтирования",
                                   "Файловая система","Всего","Использовано","Свободно"]):
            col = Gtk.TreeViewColumn(name, Gtk.CellRendererText(), text=i)
            col.set_resizable(True)
            view.append_column(col)
        scroll.set_child(view)
        self.append(scroll)
        self.refresh()

    def _fmt(self, n: int) -> str:
        for unit in ("Б","КБ","МБ","ГБ","ТБ"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} ПБ"

    def refresh(self):
        self.store.clear()
        if not HAVE_PSUTIL:
            return
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                self.store.append([
                    part.device, part.mountpoint, part.fstype,
                    self._fmt(usage.total),
                    self._fmt(usage.used),
                    self._fmt(usage.free),
                ])
            except PermissionError:
                pass


# ── Главное окно ─────────────────────────────────────────────────
class SysMonWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CryOS Системный монитор")
        self.set_default_size(820, 560)
        self.add_css_class("cry-window")

        notebook = Gtk.Notebook()

        self.perf_tab = PerfTab()
        notebook.append_page(self.perf_tab, Gtk.Label(label="Производительность"))

        self.proc_tab = ProcessTab()
        notebook.append_page(self.proc_tab, Gtk.Label(label="Процессы"))

        self.disk_tab = DiskTab()
        notebook.append_page(self.disk_tab, Gtk.Label(label="Диски"))

        self.set_child(notebook)

        if not HAVE_PSUTIL:
            bar = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING)
            bar.add_child(Gtk.Label(label="Установите python3-psutil для данных в реальном времени"))
            # InfoBar не мешает работе — данные просто не будут обновляться

        # Таймер обновления
        GLib.timeout_add(REFRESH, self._tick)
        notebook.connect("switch-page", self._on_switch)
        self._notebook = notebook

    def _tick(self):
        page = self._notebook.get_current_page()
        if page == 0:
            self.perf_tab.update()
        elif page == 1:
            self.proc_tab.refresh()
        elif page == 2:
            self.disk_tab.refresh()
        return True

    def _on_switch(self, nb, page, idx):
        pass


class SysMonApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="org.cryos.SysMon",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )

    def do_activate(self):
        if THEME_CSS.exists():
            p = Gtk.CssProvider()
            p.load_from_path(str(THEME_CSS))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), p,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        win = SysMonWindow(self)
        win.present()


def main():
    app = SysMonApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
