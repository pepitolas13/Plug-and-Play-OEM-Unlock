#!/usr/bin/env bash
# ============================================================
#  Plug-and-Play OEM Unlock - lanzador Linux / macOS
#  Ejecuta desde el USB:  ./unlock.sh
#  Instala Python 3 automaticamente si falta (mejor esfuerzo).
# ============================================================
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

find_python() {
    if command -v python3 >/dev/null 2>&1; then echo python3; return 0; fi
    if command -v python  >/dev/null 2>&1; then echo python;  return 0; fi
    return 1
}

PY="$(find_python || true)"

if [ -z "$PY" ]; then
    echo "[*] Python 3 no encontrado. Intentando instalarlo automaticamente..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -y && sudo apt-get install -y python3
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm python
    elif command -v zypper >/dev/null 2>&1; then
        sudo zypper --non-interactive install python3
    elif command -v brew >/dev/null 2>&1; then
        brew install python
    else
        echo "[X] No hay gestor de paquetes conocido. Instala Python 3 manualmente:"
        echo "    https://www.python.org/downloads/"
        exit 1
    fi
    PY="$(find_python || true)"
fi

if [ -z "$PY" ]; then
    echo "[X] No se pudo preparar Python 3. Instalalo manualmente y reintenta."
    exit 1
fi

exec "$PY" "$DIR/src/oem_unlock.py" --auto-tools "$@"
