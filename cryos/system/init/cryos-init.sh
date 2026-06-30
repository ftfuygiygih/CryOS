#!/bin/sh
# ================================================================
#  CryOS Init Script  —  system/init/cryos-init.sh
#  Минимальная инициализация системы после загрузки ядра Linux.
#  Запускается из /etc/rc.local или как systemd-сервис.
# ================================================================

set -e

CRYOS_LOG="/var/log/cryos/init.log"
mkdir -p "$(dirname "$CRYOS_LOG")"

log() {
    echo "$(date '+%H:%M:%S') [INIT] $*" | tee -a "$CRYOS_LOG"
}

# ── Базовые проверки ─────────────────────────────────────────────
log "=== CryOS Init Start ==="
log "Kernel: $(uname -r)"
log "Hostname: $(hostname)"

# ── Настройка локали ─────────────────────────────────────────────
log "Локаль..."
export LANG=ru_RU.UTF-8
export LC_ALL=ru_RU.UTF-8

# ── Монтирование proc/sys/dev ────────────────────────────────────
log "Файловые системы..."
mount -t proc  proc  /proc  2>/dev/null || true
mount -t sysfs sysfs /sys   2>/dev/null || true
mount -t devtmpfs devtmpfs /dev 2>/dev/null || true

# ── Сеть ─────────────────────────────────────────────────────────
log "Сеть..."
if command -v dhcpcd >/dev/null 2>&1; then
    dhcpcd -q -b 2>/dev/null || true
elif command -v dhclient >/dev/null 2>&1; then
    dhclient -nw 2>/dev/null || true
fi

# ── Применяем тему GTK системно ──────────────────────────────────
log "GTK тема..."
THEME_SETTINGS="/usr/share/cryos/theme/settings.ini"
if [ -f "$THEME_SETTINGS" ]; then
    mkdir -p /etc/gtk-3.0 /etc/gtk-4.0
    cp "$THEME_SETTINGS" /etc/gtk-3.0/settings.ini
    cp "$THEME_SETTINGS" /etc/gtk-4.0/settings.ini
fi

# ── X.Org или Wayland ────────────────────────────────────────────
log "Дисплей-сервер..."
if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    if command -v startx >/dev/null 2>&1; then
        log "Запуск X.Org..."
        # .xinitrc запустит CryOS session
        XINITRC="/usr/share/cryos/system/init/xinitrc"
        if [ -f "$XINITRC" ]; then
            cp "$XINITRC" "$HOME/.xinitrc"
        fi
    fi
fi

log "=== CryOS Init Done ==="
