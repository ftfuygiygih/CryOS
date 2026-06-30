#!/usr/bin/env python3
"""
CryOS Session Manager  —  system/session/session.py
====================================================
Запускает минимальный набор процессов для сессии:
  1. Настройка X/Wayland
  2. Загрузка темы
  3. Звук входа в систему (assets/sounds/hi.ogg)
  4. Рабочий стол CryOS
Заменяет тяжёлые DE (GNOME, KDE, etc.)
"""

import subprocess
import os
import sys
import signal
import time
import logging
from pathlib import Path

LOG_DIR = Path.home() / ".local" / "share" / "cryos" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "session.log"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("cryos-session")

CRYOS_ROOT = Path(__file__).parent.parent.parent


class SessionManager:
    def __init__(self):
        self.processes: dict[str, subprocess.Popen] = {}
        self._running = True
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT,  self._on_signal)

    def _on_signal(self, signum, frame):
        log.info(f"Получен сигнал {signum}, завершение сессии...")
        self._running = False
        self.stop_all()

    def start(self, name: str, cmd: list, restart: bool = True) -> subprocess.Popen:
        log.info(f"Запуск: {name} -> {' '.join(cmd)}")
        try:
            proc = subprocess.Popen(cmd, start_new_session=False)
            self.processes[name] = proc
            return proc
        except FileNotFoundError:
            log.error(f"Не найдено: {cmd[0]}")
            return None

    def stop_all(self):
        for name, proc in self.processes.items():
            log.info(f"Завершение: {name} (PID {proc.pid})")
            try:
                proc.terminate()
            except Exception:
                pass
        time.sleep(1)
        for proc in self.processes.values():
            try:
                proc.kill()
            except Exception:
                pass

    def run_session(self):
        log.info("=== CryOS Session Start ===")
        log.info(f"User: {os.getenv('USER')}")
        log.info(f"Display: {os.getenv('DISPLAY')}")

        # Шаг 1: Compositor / Display Server
        # Используем openbox как лёгкий WM (опционально — заменяется на Wayland compositor)
        wm = self._pick_wm()
        if wm:
            self.start("wm", wm, restart=True)
            time.sleep(0.3)

        # Шаг 2: Применяем обои (базовый xsetroot)
        self._set_wallpaper()

        # Шаг 3: Звук входа в систему
        self._play_login_sound()

        # Шаг 4: Рабочий стол CryOS
        desktop_py = CRYOS_ROOT / "desktop" / "desktop.py"
        if desktop_py.exists():
            self.start("desktop", ["python3", str(desktop_py)])
        else:
            self.start("desktop", ["cryos-desktop"])

        log.info("Сессия запущена. Ожидание завершения...")

        # Мониторинг процессов
        while self._running:
            for name, proc in list(self.processes.items()):
                ret = proc.poll()
                if ret is not None:
                    log.warning(f"Процесс {name} завершился (код {ret})")
                    if name == "desktop":
                        log.info("Рабочий стол завершён — выход из сессии")
                        self._running = False
                        break
            time.sleep(1)

        self.stop_all()
        log.info("=== CryOS Session End ===")

    def _pick_wm(self) -> list | None:
        """Выбирает доступный лёгкий оконный менеджер."""
        candidates = [
            ["openbox", "--sm-disable"],
            ["icewm"],
            ["fluxbox"],
            ["matchbox-window-manager"],
        ]
        for cmd in candidates:
            if self._which(cmd[0]):
                log.info(f"Оконный менеджер: {cmd[0]}")
                return cmd
        log.warning("Оконный менеджер не найден. Рабочий стол запустится без WM.")
        return None

    def _set_wallpaper(self):
        """Устанавливает цвет фона (бирюзовый, стиль Win95)."""
        try:
            subprocess.run(["xsetroot", "-solid", "#008080"], check=False)
        except FileNotFoundError:
            pass

    def _play_login_sound(self):
        """Воспроизводит звук приветствия после входа в систему."""
        sound_path = CRYOS_ROOT / "assets" / "sounds" / "hi.ogg"
        if not sound_path.exists():
            log.warning(f"Звук входа не найден: {sound_path}")
            return

        # Пробуем доступные плееры по порядку предпочтения
        players = [
            ["paplay", str(sound_path)],                      # PulseAudio (встроен)
            ["pw-play", str(sound_path)],                     # PipeWire
            ["aplay", "-q", str(sound_path)],                 # ALSA (fallback)
            ["ffplay", "-nodisp", "-autoexit", "-loglevel",
             "quiet", str(sound_path)],                       # ffmpeg (универсальный)
            ["mpg123", "-q", str(sound_path)],                # mpg123
        ]
        for cmd in players:
            if self._which(cmd[0]):
                log.info(f"Звук входа: {cmd[0]} {sound_path.name}")
                try:
                    subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,   # не блокирует сессию
                    )
                except Exception as e:
                    log.warning(f"Ошибка воспроизведения ({cmd[0]}): {e}")
                return

        log.warning("Ни один аудиоплеер не найден (paplay/pw-play/aplay/ffplay/mpg123)")

    @staticmethod
    def _which(cmd: str) -> bool:
        import shutil
        return shutil.which(cmd) is not None


def main():
    mgr = SessionManager()
    mgr.run_session()


if __name__ == "__main__":
    main()
