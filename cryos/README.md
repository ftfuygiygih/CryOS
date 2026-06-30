# CryOS

**Лёгкая, быстрая и минималистичная операционная система**  
Атмосфера Windows 95/98 · Белый и тёмно-синий · Маскот — Коната

---

## Структура проекта

```
cryos/
├── desktop/          # Рабочий стол (WM + панель задач + меню Cry)
├── apps/
│   ├── file-manager/ # Файловый менеджер с секретной папкой
│   ├── git-manager/  # Менеджер Git-репозиториев
│   ├── disk-utility/ # Утилита работы с дисками (аналог GParted)
│   └── app-installer/# Установка Flatpak/AppImage
├── system/
│   ├── init/         # Инициализация системы (замена systemd-минимум)
│   ├── session/      # Управление сессией пользователя
│   ├── theme/        # GTK-тема + иконки CryOS
│   └── auth/         # Аутентификация и PAM-конфигурация
├── oobe/             # Приветственные экраны (Out-Of-Box Experience)
├── assets/           # Иконки, шрифты, маскот Коната
├── build/            # Скрипты сборки ISO
└── docs/             # Документация
```

## Быстрый старт

```bash
# Клонирование
git clone https://github.com/yourname/cryos.git
cd cryos

# Сборка всего проекта
./build/build.sh

# Только тема
./build/build.sh --component theme

# Только приложения
./build/build.sh --component apps
```

## Требования для сборки

- Debian 12 / Ubuntu 24.04 LTS / Linux Mint 21+
- Python 3.11+
- GTK 4.x dev libraries
- PyGObject
- flatpak-builder (опционально)
- xorriso (для сборки ISO)

## Лицензия

MIT — см. LICENSE
