#!/usr/bin/env python3
"""
CryOS Auth / User Setup  —  system/auth/setup_user.py
=======================================================
Создание системного пользователя CryOS.
Запускается от root (через pkexec или sudo).

Режимы:
  --from-config        Читает ~/.config/cryos/user.json (из OOBE)
  --interactive        Интерактивный мастер в терминале
  --username USER      Прямое указание имени (вместе с --password)
  --password PASS
  --autologin          Включить автологин
  --no-sudo            Не добавлять в sudo
"""

import subprocess, sys, os, json, hashlib, getpass, argparse, re
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "cryos"
USER_CFG   = CONFIG_DIR / "user.json"
CRYOS_ROOT = Path(__file__).parent.parent.parent

SUDOERS_TMPL = """\
# CryOS auto-generated — не редактировать вручную
# Создан: cryos-setup-user
{username} ALL=(ALL:ALL) ALL
{username} ALL=(ALL) NOPASSWD: /usr/bin/parted,/usr/sbin/mkfs.ext4,\
/usr/sbin/mkfs.ext3,/usr/sbin/mkfs.vfat,/usr/sbin/mkfs.ntfs,\
/usr/sbin/mkfs.btrfs,/usr/bin/flatpak
"""

LIGHTDM_TMPL = """\
[Seat:*]
autologin-user={username}
autologin-user-timeout=0
user-session=cryos
greeter-session=lightdm-gtk-greeter
"""


def check_root():
    if os.geteuid() != 0:
        print("Ошибка: требуются права root.", file=sys.stderr)
        print("Запустите: sudo python3 setup_user.py ...", file=sys.stderr)
        sys.exit(1)


def validate_username(name: str) -> str | None:
    """None = ok, иначе сообщение об ошибке."""
    if not re.match(r'^[a-z][a-z0-9_]{1,31}$', name):
        return "Логин: только строчные a-z, цифры, _, 2-32 символа"
    forbidden = {"root", "daemon", "bin", "sys", "sync", "nobody"}
    if name in forbidden:
        return f"Имя '{name}' зарезервировано системой"
    return None


def user_exists(username: str) -> bool:
    r = subprocess.run(["id", username], capture_output=True)
    return r.returncode == 0


def create_system_user(username: str, password: str, fullname: str,
                       add_sudo: bool, autologin: bool) -> list[str]:
    """Создаёт пользователя. Возвращает список предупреждений/ошибок."""
    warnings = []

    # ── Группы ──────────────────────────────────────────────────
    base_groups = ["audio", "video", "plugdev", "input", "netdev",
                   "cdrom", "dialout", "bluetooth", "users"]
    if add_sudo:
        base_groups.append("sudo")

    # Фильтруем: оставляем только существующие группы
    existing_groups = []
    for g in base_groups:
        r = subprocess.run(["getent", "group", g], capture_output=True)
        if r.returncode == 0:
            existing_groups.append(g)
        else:
            warnings.append(f"Группа '{g}' не существует — пропущена")

    groups_str = ",".join(existing_groups)

    # ── Создаём или обновляем пользователя ──────────────────────
    if user_exists(username):
        print(f"Пользователь {username} уже существует — обновляем...")
        r = subprocess.run(
            ["usermod", "-c", fullname, "-G", groups_str, "-s", "/bin/bash", username],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            warnings.append(f"usermod: {r.stderr.strip()}")
    else:
        r = subprocess.run(
            ["useradd", "-m", "-s", "/bin/bash",
             "-c", fullname,
             "-G", groups_str,
             username],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            return [f"useradd завершился с ошибкой: {r.stderr.strip()}"]
        print(f"✓ Пользователь {username} создан")

    # ── Пароль ──────────────────────────────────────────────────
    proc = subprocess.Popen(
        ["chpasswd"], stdin=subprocess.PIPE, capture_output=True
    )
    _, err = proc.communicate(f"{username}:{password}".encode())
    if proc.returncode != 0:
        warnings.append(f"chpasswd: {err.decode().strip()}")
    else:
        print("✓ Пароль установлен")

    # ── Создаём домашнюю структуру ──────────────────────────────
    home = Path(f"/home/{username}")
    for d in ["Documents", "Downloads", "Projects", "Applications", "Pictures"]:
        (home / d).mkdir(exist_ok=True)
    subprocess.run(["chown", "-R", f"{username}:{username}", str(home)],
                   capture_output=True)
    print("✓ Домашние папки созданы")

    # ── .xinitrc ────────────────────────────────────────────────
    xinitrc_src = CRYOS_ROOT / "system" / "init" / "xinitrc"
    xinitrc_dst = home / ".xinitrc"
    if xinitrc_src.exists():
        import shutil
        shutil.copy2(xinitrc_src, xinitrc_dst)
        xinitrc_dst.chmod(0o755)
        subprocess.run(["chown", f"{username}:{username}", str(xinitrc_dst)])
        print("✓ .xinitrc установлен")
    else:
        warnings.append(".xinitrc не найден — рабочий стол не запустится из startx")

    # ── Конфиг CryOS для нового пользователя ────────────────────
    new_cfg = home / ".config" / "cryos"
    new_cfg.mkdir(parents=True, exist_ok=True)
    # Копируем user.json если есть
    if USER_CFG.exists():
        import shutil
        shutil.copy2(USER_CFG, new_cfg / "user.json")
    # Копируем wallpaper.conf если есть
    wc = Path.home() / ".config" / "cryos" / "wallpaper.conf"
    if wc.exists():
        import shutil
        shutil.copy2(wc, new_cfg / "wallpaper.conf")
    subprocess.run(["chown", "-R", f"{username}:{username}", str(new_cfg)])
    print("✓ Конфиг CryOS скопирован")

    # ── GTK тема для пользователя ────────────────────────────────
    gtk_cfg = home / ".config" / "gtk-4.0"
    gtk_cfg.mkdir(parents=True, exist_ok=True)
    theme_settings = CRYOS_ROOT / "system" / "theme" / "settings.ini"
    if theme_settings.exists():
        import shutil
        shutil.copy2(theme_settings, gtk_cfg / "settings.ini")
        subprocess.run(["chown", "-R", f"{username}:{username}", str(gtk_cfg)])
    print("✓ GTK тема настроена")

    # ── sudoers ──────────────────────────────────────────────────
    if add_sudo:
        sudoers_file = Path(f"/etc/sudoers.d/cryos-{username}")
        try:
            sudoers_file.write_text(SUDOERS_TMPL.format(username=username))
            sudoers_file.chmod(0o440)
            print("✓ Права sudo настроены")
        except Exception as e:
            warnings.append(f"sudoers: {e}")

    # ── Автологин ────────────────────────────────────────────────
    if autologin:
        _setup_autologin(username, warnings)

    return warnings


def _setup_autologin(username: str, warnings: list):
    configured = False

    # LightDM
    ldm_conf = Path("/etc/lightdm/lightdm.conf")
    if ldm_conf.parent.exists():
        try:
            ldm_conf.write_text(LIGHTDM_TMPL.format(username=username))
            print("✓ Автологин LightDM настроен")
            configured = True
        except Exception as e:
            warnings.append(f"LightDM autologin: {e}")

    # GDM3
    gdm_conf = Path("/etc/gdm3/daemon.conf")
    if gdm_conf.exists():
        try:
            text = gdm_conf.read_text()
            if "AutomaticLogin" not in text:
                text = text.replace(
                    "[daemon]",
                    f"[daemon]\nAutomaticLoginEnable=true\nAutomaticLogin={username}"
                )
            else:
                text = re.sub(r"AutomaticLogin\s*=.*", f"AutomaticLogin={username}", text)
                text = re.sub(r"AutomaticLoginEnable\s*=.*", "AutomaticLoginEnable=true", text)
            gdm_conf.write_text(text)
            print("✓ Автологин GDM3 настроен")
            configured = True
        except Exception as e:
            warnings.append(f"GDM3 autologin: {e}")

    # SDDM
    sddm_conf = Path("/etc/sddm.conf")
    if not sddm_conf.exists():
        sddm_conf = Path("/etc/sddm.conf.d/autologin.conf")
        sddm_conf.parent.mkdir(parents=True, exist_ok=True)
    if Path("/usr/sbin/sddm").exists() or Path("/usr/bin/sddm").exists():
        try:
            sddm_conf.write_text(
                f"[Autologin]\nUser={username}\nSession=cryos\n"
            )
            print("✓ Автологин SDDM настроен")
            configured = True
        except Exception as e:
            warnings.append(f"SDDM autologin: {e}")

    if not configured:
        warnings.append("Автологин: display manager не найден (LightDM/GDM3/SDDM)")


def interactive_setup():
    """Интерактивный мастер создания пользователя."""
    print("\n" + "=" * 50)
    print("  CryOS — Создание пользователя")
    print("=" * 50 + "\n")

    while True:
        username = input("Имя пользователя (a-z, 0-9, _): ").strip()
        err = validate_username(username)
        if err:
            print(f"Ошибка: {err}")
        else:
            break

    fullname = input("Полное имя [Enter = пропустить]: ").strip() or username

    while True:
        pw1 = getpass.getpass("Пароль: ")
        if len(pw1) < 4:
            print("Пароль слишком короткий (минимум 4 символа)")
            continue
        pw2 = getpass.getpass("Повторите пароль: ")
        if pw1 != pw2:
            print("Пароли не совпадают")
        else:
            break

    add_sudo   = input("Добавить в sudo? [Y/n]: ").strip().lower() not in ("n", "no")
    autologin  = input("Автологин? [Y/n]: ").strip().lower() not in ("n", "no")

    print(f"\nСоздание пользователя: {username}")
    if fullname != username:
        print(f"Полное имя: {fullname}")
    print(f"sudo: {'да' if add_sudo else 'нет'}")
    print(f"Автологин: {'да' if autologin else 'нет'}")
    confirm = input("\nПродолжить? [Y/n]: ").strip().lower()
    if confirm in ("n", "no"):
        print("Отмена.")
        sys.exit(0)

    warnings = create_system_user(username, pw1, fullname, add_sudo, autologin)
    _print_result(username, warnings)


def from_config_setup():
    """Создаёт пользователя из конфига OOBE."""
    if not USER_CFG.exists():
        print(f"Конфиг не найден: {USER_CFG}", file=sys.stderr)
        print("Запустите OOBE: cryos-oobe", file=sys.stderr)
        sys.exit(1)

    try:
        cfg = json.loads(USER_CFG.read_text())
    except Exception as e:
        print(f"Ошибка чтения конфига: {e}", file=sys.stderr)
        sys.exit(1)

    username = cfg.get("username", "").strip()
    fullname = cfg.get("fullname", username)
    add_sudo = cfg.get("sudo", True)
    autologin= cfg.get("autologin", True)

    err = validate_username(username)
    if err:
        print(f"Ошибка в конфиге: {err}", file=sys.stderr)
        sys.exit(1)

    # Запрашиваем пароль (не хранится в cfg в открытом виде)
    print(f"Создание пользователя: {username}")
    try:
        password = getpass.getpass(f"Пароль для '{username}': ")
    except (EOFError, KeyboardInterrupt):
        print("\nОтмена.")
        sys.exit(0)

    if not password:
        print("Пароль не может быть пустым.", file=sys.stderr)
        sys.exit(1)

    warnings = create_system_user(username, password, fullname, add_sudo, autologin)
    _print_result(username, warnings)


def _print_result(username: str, warnings: list):
    print()
    if warnings:
        print("Предупреждения:")
        for w in warnings:
            print(f"  ⚠  {w}")
        print()
    print("=" * 50)
    print(f"✅  Пользователь '{username}' готов к работе!")
    print(f"    Войдите в систему или запустите: startx")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="CryOS User Setup")
    parser.add_argument("--from-config",  action="store_true",
                        help="Создать из ~/.config/cryos/user.json")
    parser.add_argument("--interactive",  action="store_true",
                        help="Интерактивный мастер")
    parser.add_argument("--username",     help="Имя пользователя")
    parser.add_argument("--password",     help="Пароль")
    parser.add_argument("--fullname",     default="", help="Полное имя")
    parser.add_argument("--autologin",    action="store_true")
    parser.add_argument("--no-sudo",      action="store_true")
    args = parser.parse_args()

    check_root()

    if args.from_config:
        from_config_setup()
    elif args.interactive:
        interactive_setup()
    elif args.username and args.password:
        err = validate_username(args.username)
        if err:
            print(f"Ошибка: {err}", file=sys.stderr); sys.exit(1)
        warnings = create_system_user(
            args.username, args.password,
            args.fullname or args.username,
            not args.no_sudo, args.autologin
        )
        _print_result(args.username, warnings)
    else:
        parser.print_help()
        print("\nПример:")
        print("  sudo python3 setup_user.py --from-config")
        print("  sudo python3 setup_user.py --interactive")
        sys.exit(1)


if __name__ == "__main__":
    main()
