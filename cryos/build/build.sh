#!/bin/bash
# ================================================================
#  CryOS Build System  —  build/build.sh
#  v2: обои, слайд-шоу, создание пользователя, сборка ISO.
#
#  Использование:
#    ./build/build.sh                   — полная сборка + установка
#    ./build/build.sh --component theme — только тема
#    ./build/build.sh --component apps  — только приложения
#    ./build/build.sh --component oobe  — только OOBE
#    ./build/build.sh --iso             — + собрать ISO
#    ./build/build.sh --create-user     — создать системного пользователя
# ================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_OUT="$ROOT_DIR/build/output"
DIST_DIR="$ROOT_DIR/dist"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'
YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

log()   { echo -e "${BLUE}[BUILD]${NC} $*"; }
ok()    { echo -e "${GREEN}[  OK ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[ WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
info()  { echo -e "${CYAN}[ INFO]${NC} $*"; }

COMPONENT="all"
BUILD_ISO=0
CREATE_USER=0

while [[ $# -gt 0 ]]; do
    case $1 in
        --component)  COMPONENT="$2"; shift 2;;
        --iso)        BUILD_ISO=1;    shift;;
        --create-user)CREATE_USER=1;  shift;;
        --help|-h)
            echo "CryOS Build v2"
            echo "Использование: $0 [--component <name>] [--iso] [--create-user]"
            echo "Компоненты: all, theme, apps, desktop, oobe, system, assets"
            exit 0;;
        *) warn "Неизвестный параметр: $1"; shift;;
    esac
done

mkdir -p "$BUILD_OUT" "$DIST_DIR"

# ════════════════════════════════════════════════════════════════════
# ПРОВЕРКА ЗАВИСИМОСТЕЙ
# ════════════════════════════════════════════════════════════════════
check_deps() {
    log "Проверка зависимостей..."
    local miss=()
    command -v python3 >/dev/null || miss+=("python3")
    command -v git     >/dev/null || miss+=("git")
    if [ ${#miss[@]} -gt 0 ]; then
        err "Не найдены: ${miss[*]}"
        err "Установите: sudo apt install python3 git"
        exit 1
    fi

    # Проверка GTK PyGObject
    if ! python3 -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk" 2>/dev/null; then
        warn "PyGObject / GTK 4 не найден."
        warn "Установка: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0"
    else
        ok "PyGObject GTK 4 — OK"
    fi

    # Проверка рекомендуемых утилит обоев
    command -v feh      >/dev/null && ok "feh (обои) — найден" \
        || warn "feh не найден (sudo apt install feh) — нужен для применения обоев"
    command -v nitrogen >/dev/null && ok "nitrogen (обои) — найден" || true

    ok "Зависимости проверены"
}

# ════════════════════════════════════════════════════════════════════
# РЕСУРСЫ (ОБОИ + СЛАЙД-ШОУ)
# ════════════════════════════════════════════════════════════════════
build_assets() {
    log "Копирование ресурсов..."
    ASSET_OUT="$BUILD_OUT/assets"
    mkdir -p "$ASSET_OUT/wallpapers" "$ASSET_OUT/slideshow" "$ASSET_OUT/icons"

    # ── Обои ────────────────────────────────────────────────────
    local wall_count=0
    for name in w01.png w02.png w03.png; do
        SRC="$ROOT_DIR/assets/wallpapers/$name"
        if [ -f "$SRC" ]; then
            cp "$SRC" "$ASSET_OUT/wallpapers/$name"
            ok "Обои: $name ($(du -sh "$SRC" | cut -f1))"
            wall_count=$((wall_count+1))
        else
            warn "Обои не найдены: $SRC"
            warn "  → Положите файл: assets/wallpapers/$name"
            # Создаём placeholder SVG как временный файл
            _make_placeholder_wallpaper "$ASSET_OUT/wallpapers/$name" "$name"
        fi
    done
    info "Обоев скопировано: $wall_count/3"

    # ── Слайд-шоу (01.png … 10.png) ────────────────────────────
    local slide_count=0
    for i in $(seq -w 1 10); do
        SRC="$ROOT_DIR/assets/slideshow/${i}.png"
        if [ -f "$SRC" ]; then
            cp "$SRC" "$ASSET_OUT/slideshow/${i}.png"
            ok "Слайд: ${i}.png"
            slide_count=$((slide_count+1))
        else
            warn "Слайд не найден: assets/slideshow/${i}.png"
            # OOBE покажет красивый fallback без PNG
        fi
    done
    info "Слайдов скопировано: $slide_count/10"

    ok "Ресурсы → $ASSET_OUT"
}

_make_placeholder_wallpaper() {
    local dst="$1" name="$2"
    # Генерируем минимальный SVG-placeholder
    cat > "${dst%.png}.svg" << EOF
<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080">
  <rect width="1920" height="1080" fill="#008080"/>
  <text x="960" y="540" font-family="monospace" font-size="48"
        fill="white" text-anchor="middle">CryOS — $name</text>
  <text x="960" y="600" font-family="monospace" font-size="24"
        fill="#ccffff" text-anchor="middle">Замените файл: assets/wallpapers/$name</text>
</svg>
EOF
    info "  Placeholder создан: ${dst%.png}.svg"
}

# ════════════════════════════════════════════════════════════════════
# ТЕМА
# ════════════════════════════════════════════════════════════════════
build_theme() {
    log "Сборка темы CryOS..."
    THEME_OUT="$BUILD_OUT/theme/CryOS"
    mkdir -p "$THEME_OUT/gtk-4.0" "$THEME_OUT/gtk-3.0"

    cp "$ROOT_DIR/system/theme/gtk.css"      "$THEME_OUT/gtk-4.0/gtk.css"
    cp "$ROOT_DIR/system/theme/gtk.css"      "$THEME_OUT/gtk-3.0/gtk.css"
    cp "$ROOT_DIR/system/theme/index.theme"  "$THEME_OUT/index.theme"
    cp "$ROOT_DIR/system/theme/settings.ini" "$THEME_OUT/settings.ini"

    ok "Тема → $THEME_OUT"
}

# ════════════════════════════════════════════════════════════════════
# ПРИЛОЖЕНИЯ
# ════════════════════════════════════════════════════════════════════
build_apps() {
    log "Сборка приложений..."
    APPS_OUT="$BUILD_OUT/apps"
    mkdir -p "$APPS_OUT"

    for app in file-manager git-manager disk-utility app-installer; do
        SRC="$ROOT_DIR/apps/$app"
        if [ -d "$SRC" ]; then
            cp -r "$SRC" "$APPS_OUT/$app"
            chmod +x "$APPS_OUT/$app/main.py" 2>/dev/null || true
            ok "Приложение: $app"
        else
            warn "Не найдено: $SRC"
        fi
    done
}

# ════════════════════════════════════════════════════════════════════
# РАБОЧИЙ СТОЛ
# ════════════════════════════════════════════════════════════════════
build_desktop() {
    log "Сборка рабочего стола..."
    DST="$BUILD_OUT/desktop"
    mkdir -p "$DST"
    cp -r "$ROOT_DIR/desktop/." "$DST/"
    chmod +x "$DST/desktop.py"
    ok "Рабочий стол → $DST"
}

# ════════════════════════════════════════════════════════════════════
# OOBE
# ════════════════════════════════════════════════════════════════════
build_oobe() {
    log "Сборка OOBE..."
    DST="$BUILD_OUT/oobe"
    mkdir -p "$DST"
    cp -r "$ROOT_DIR/oobe/." "$DST/"
    chmod +x "$DST/oobe.py"
    ok "OOBE → $DST"
}

# ════════════════════════════════════════════════════════════════════
# СИСТЕМНЫЕ КОМПОНЕНТЫ
# ════════════════════════════════════════════════════════════════════
build_system() {
    log "Сборка системных компонентов..."
    DST="$BUILD_OUT/system"
    mkdir -p "$DST"
    cp -r "$ROOT_DIR/system/." "$DST/"
    chmod +x "$DST/init/cryos-init.sh"
    chmod +x "$DST/init/xinitrc"
    chmod +x "$DST/session/session.py"
    chmod +x "$DST/auth/setup_user.py"
    ok "Системные компоненты → $DST"
}

# ════════════════════════════════════════════════════════════════════
# LAUNCHER-СКРИПТЫ
# ════════════════════════════════════════════════════════════════════
build_launchers() {
    log "Создание launcher-скриптов..."
    BIN_OUT="$BUILD_OUT/bin"
    mkdir -p "$BIN_OUT"

    PREFIX="/usr/share/cryos"

    declare -A APPS=(
        ["cryos-desktop"]="desktop/desktop.py"
        ["cryos-files"]="apps/file-manager/main.py"
        ["cryos-git"]="apps/git-manager/main.py"
        ["cryos-disk"]="apps/disk-utility/main.py"
        ["cryos-appinstall"]="apps/app-installer/main.py"
        ["cryos-install"]="apps/installer/main.py"
        ["cryos-oobe"]="oobe/oobe.py"
        ["cryos-session"]="system/session/session.py"
        ["cryos-setup-user"]="system/auth/setup_user.py"
    )

    for name in "${!APPS[@]}"; do
        cat > "$BIN_OUT/$name" << EOF
#!/bin/sh
# CryOS launcher: $name
exec python3 $PREFIX/${APPS[$name]} "\$@"
EOF
        chmod +x "$BIN_OUT/$name"
        ok "Launcher: $name"
    done
}

# ════════════════════════════════════════════════════════════════════
# .desktop ФАЙЛЫ
# ════════════════════════════════════════════════════════════════════
generate_desktop_files() {
    log "Генерация .desktop файлов..."
    XDG_OUT="$BUILD_OUT/applications"
    mkdir -p "$XDG_OUT"

    cat > "$XDG_OUT/cryos-files.desktop" << EOF
[Desktop Entry]
Type=Application
Name=CryOS Файлы
Comment=Файловый менеджер CryOS
Exec=cryos-files
Icon=folder
Terminal=false
Categories=System;FileManager;
EOF

    cat > "$XDG_OUT/cryos-git.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Git Manager
Comment=Менеджер Git-репозиториев
Exec=cryos-git
Icon=applications-vcs
Terminal=false
Categories=Development;VersionControl;
EOF

    cat > "$XDG_OUT/cryos-disk.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Утилита диска
Comment=Управление дисковыми разделами
Exec=cryos-disk
Icon=drive-harddisk
Terminal=false
Categories=System;
EOF

    cat > "$XDG_OUT/cryos-appinstall.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Установка ПО
Comment=Установка Flatpak и AppImage
Exec=cryos-appinstall
Icon=system-software-install
Terminal=false
Categories=System;PackageManager;
EOF

    cat > "$XDG_OUT/cryos-install.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Установить CryOS
Comment=Установить CryOS на компьютер
Exec=cryos-install
Icon=system-software-install
Terminal=false
Categories=System;
EOF

    # XSession файл
    mkdir -p "$BUILD_OUT/xsessions"
    cat > "$BUILD_OUT/xsessions/cryos.desktop" << EOF
[Desktop Entry]
Name=CryOS
Comment=Лёгкая ОС в стиле Windows 95/98
Exec=/usr/share/cryos/system/session/session.py
TryExec=python3
Type=XSession
EOF

    ok ".desktop файлы созданы"
}

# ════════════════════════════════════════════════════════════════════
# УСТАНОВКА ЛОКАЛЬНО
# ════════════════════════════════════════════════════════════════════
install_local() {
    log "Установка в ~/.local/share/cryos ..."
    LOCAL="$HOME/.local/share/cryos"
    mkdir -p "$LOCAL"
    cp -r "$BUILD_OUT/." "$LOCAL/"

    # GTK тема
    mkdir -p "$HOME/.themes/CryOS"
    if [ -d "$BUILD_OUT/theme/CryOS" ]; then
        cp -r "$BUILD_OUT/theme/CryOS/." "$HOME/.themes/CryOS/"
    fi

    # Применяем GTK тему через gsettings
    command -v gsettings >/dev/null && {
        gsettings set org.gnome.desktop.interface gtk-theme "CryOS" 2>/dev/null || true
    }

    # Launchers в ~/.local/bin
    mkdir -p "$HOME/.local/bin"
    for launcher in "$BUILD_OUT/bin/"cryos-*; do
        [ -f "$launcher" ] || continue
        bname="$(basename "$launcher")"
        # Переписываем путь на локальный
        sed "s|/usr/share/cryos|$LOCAL|g" "$launcher" > "$HOME/.local/bin/$bname"
        chmod +x "$HOME/.local/bin/$bname"
        ok "~/.local/bin/$bname"
    done

    # .desktop файлы
    mkdir -p "$HOME/.local/share/applications"
    for df in "$BUILD_OUT/applications/"*.desktop; do
        [ -f "$df" ] || continue
        cp "$df" "$HOME/.local/share/applications/"
    done

    ok "Установлено: $LOCAL"
    info ""
    info "  Убедитесь, что ~/.local/bin в PATH:"
    info "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    info ""
    info "  Запуск рабочего стола: cryos-desktop"
    info "  Запуск OOBE вручную:   cryos-oobe"
}

# ════════════════════════════════════════════════════════════════════
# СОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ (системное, требует root)
# ════════════════════════════════════════════════════════════════════
do_create_user() {
    log "Создание системного пользователя CryOS..."

    USER_CFG="$HOME/.config/cryos/user.json"
    SETUP_SCRIPT="$ROOT_DIR/system/auth/setup_user.py"

    if [ ! -f "$USER_CFG" ]; then
        err "Конфиг пользователя не найден: $USER_CFG"
        err "Сначала запустите OOBE: cryos-oobe"
        exit 1
    fi

    if [ "$EUID" -eq 0 ]; then
        python3 "$SETUP_SCRIPT" --from-config
    else
        info "Запрос прав root через pkexec/sudo..."
        if command -v pkexec >/dev/null; then
            pkexec python3 "$SETUP_SCRIPT" --from-config
        elif command -v sudo >/dev/null; then
            sudo python3 "$SETUP_SCRIPT" --from-config
        else
            err "Нет pkexec и sudo. Запустите от root:"
            err "  sudo python3 $SETUP_SCRIPT --from-config"
            exit 1
        fi
    fi
}

# ════════════════════════════════════════════════════════════════════
# СБОРКА ISO
# ════════════════════════════════════════════════════════════════════
build_iso() {
    log "Сборка ISO образа..."
    command -v xorriso >/dev/null || {
        err "xorriso не найден: sudo apt install xorriso"
        return 1
    }

    ISO_WORK="$BUILD_OUT/iso-work"
    ISO_OUT="$DIST_DIR/cryos.iso"
    mkdir -p "$ISO_WORK/usr/share/cryos"

    # Копируем собранные файлы в структуру ISO
    cp -r "$BUILD_OUT/." "$ISO_WORK/usr/share/cryos/"

    # Скрипты запуска
    mkdir -p "$ISO_WORK/usr/bin"
    for launcher in "$BUILD_OUT/bin/"cryos-*; do
        [ -f "$launcher" ] || continue
        bname="$(basename "$launcher")"
        sed 's|~/.local/share/cryos|/usr/share/cryos|g' "$launcher" \
            > "$ISO_WORK/usr/bin/$bname"
        chmod +x "$ISO_WORK/usr/bin/$bname"
    done

    # XSession
    mkdir -p "$ISO_WORK/usr/share/xsessions"
    cp "$BUILD_OUT/xsessions/cryos.desktop" \
       "$ISO_WORK/usr/share/xsessions/" 2>/dev/null || true

    xorriso -as mkisofs \
        -iso-level 3 \
        -full-iso9660-filenames \
        -volid "CryOS_1.0" \
        -output "$ISO_OUT" \
        "$ISO_WORK" 2>/dev/null

    ok "ISO: $ISO_OUT  ($(du -sh "$ISO_OUT" | cut -f1))"
}

# ════════════════════════════════════════════════════════════════════
# ГЛАВНЫЙ ЗАПУСК
# ════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         CryOS Build System v2            ║${NC}"
echo -e "${BLUE}║   Лёгкая ОС в стиле Windows 95/98       ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""

check_deps

if [ "$CREATE_USER" -eq 1 ]; then
    do_create_user
    exit 0
fi

case "$COMPONENT" in
    all)
        build_assets
        build_theme
        build_apps
        build_desktop
        build_oobe
        build_system
        build_launchers
        generate_desktop_files
        install_local
        ;;
    assets)  build_assets;;
    theme)   build_theme;;
    apps)    build_apps;;
    desktop) build_desktop;;
    oobe)    build_oobe;;
    system)  build_system;;
    *)
        err "Неизвестный компонент: $COMPONENT"
        err "Доступные: all, assets, theme, apps, desktop, oobe, system"
        exit 1;;
esac

[ "$BUILD_ISO" -eq 1 ] && build_iso

echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  Сборка завершена!                       ${NC}"
echo -e "${GREEN}  cryos-desktop  — запуск рабочего стола  ${NC}"
echo -e "${GREEN}  cryos-oobe     — приветственный экран   ${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo ""

# Напоминание про обои
if [ ! -f "$ROOT_DIR/assets/wallpapers/w01.png" ]; then
    echo -e "${YELLOW}╔══════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║  ⚠  Обои не найдены!                    ║${NC}"
    echo -e "${YELLOW}║  Положите файлы в:                       ║${NC}"
    echo -e "${YELLOW}║    assets/wallpapers/w01.png             ║${NC}"
    echo -e "${YELLOW}║    assets/wallpapers/w02.png             ║${NC}"
    echo -e "${YELLOW}║    assets/wallpapers/w03.png             ║${NC}"
    echo -e "${YELLOW}╚══════════════════════════════════════════╝${NC}"
fi

if [ ! -f "$ROOT_DIR/assets/slideshow/01.png" ]; then
    echo -e "${YELLOW}╔══════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║  ⚠  Слайды OOBE не найдены!             ║${NC}"
    echo -e "${YELLOW}║  Положите файлы в:                       ║${NC}"
    echo -e "${YELLOW}║    assets/slideshow/01.png … 10.png      ║${NC}"
    echo -e "${YELLOW}║  (OOBE покажет красивый fallback)        ║${NC}"
    echo -e "${YELLOW}╚══════════════════════════════════════════╝${NC}"
fi
