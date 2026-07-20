"""
Instalacion automatica de dependencias.

- adb/fastboot : las descarga platform_tools dentro del USB.
- lz4 (python) : para descomprimir firmware Samsung .img.lz4 -> pip install.
- heimdall     : flasher Samsung -> gestor de paquetes del sistema.

Todo es "mejor esfuerzo": si algo no se puede instalar solo (por falta de
permisos o de gestor de paquetes), se avisa con instrucciones claras y se
continua con las alternativas disponibles.
"""

import platform
import shutil
import subprocess
import sys

import platform_tools as pt


def _run(cmd, timeout=600, capture=True):
    try:
        r = subprocess.run(cmd, timeout=timeout,
                           capture_output=capture, text=True)
        return r.returncode == 0
    except Exception:
        return False


# ---------------- lz4 (modulo python) ----------------
def lz4_available():
    try:
        import lz4.frame  # noqa: F401
        return True
    except ImportError:
        return False


def _pip_install(pkg):
    """Intenta pip install con varias estrategias (entornos gestionados incluidos)."""
    base = [sys.executable, "-m", "pip", "install", "--quiet"]
    for extra in ([], ["--user"], ["--break-system-packages"]):
        if _run(base + extra + [pkg], timeout=180):
            return True
    return False


def ensure_lz4(auto=True, verbose=True):
    """Garantiza descompresion lz4 (modulo python o comando del sistema)."""
    if lz4_available():
        return True
    if shutil.which("lz4") or shutil.which("unlz4"):
        return True  # el comando del sistema sirve de alternativa
    if not auto:
        return False
    if verbose:
        print("[*] Instalando soporte lz4 (descompresion de firmware Samsung)...")
    if _pip_install("lz4") and lz4_available():
        if verbose:
            print("[OK] lz4 instalado.")
        return True
    if verbose:
        print("[i] No pude instalar 'lz4' automaticamente (solo necesario para")
        print("    firmware Samsung comprimido). Alternativa: 'pip install lz4'")
        print("    o instala el comando 'lz4' de tu sistema.")
    return False


# ---------------- heimdall (flasher Samsung) ----------------
def ensure_heimdall(auto=True, verbose=True):
    """Instala Heimdall via el gestor de paquetes del sistema (mejor esfuerzo)."""
    if pt.find_tool("heimdall"):
        return True
    if not auto:
        return False
    system = platform.system()
    if verbose:
        print("[*] Intentando instalar Heimdall (flasher Samsung)...")

    candidates = []
    if system == "Linux":
        candidates = [
            ("apt-get", ["sudo", "apt-get", "install", "-y", "heimdall-flash"]),
            ("dnf", ["sudo", "dnf", "install", "-y", "heimdall"]),
            ("pacman", ["sudo", "pacman", "-S", "--noconfirm", "heimdall"]),
            ("zypper", ["sudo", "zypper", "--non-interactive", "install", "heimdall"]),
        ]
    elif system == "Darwin":
        candidates = [("brew", ["brew", "install", "heimdall"])]
    elif system == "Windows":
        candidates = [
            ("winget", ["winget", "install", "-e", "--id", "BenjaminDobell.Heimdall",
                        "--accept-package-agreements", "--accept-source-agreements"]),
            ("choco", ["choco", "install", "heimdall", "-y"]),
            ("scoop", ["scoop", "install", "heimdall"]),
        ]

    for mgr, cmd in candidates:
        if shutil.which(mgr):
            if verbose:
                print(f"    usando {mgr}...")
            if _run(cmd, capture=False) and pt.find_tool("heimdall"):
                if verbose:
                    print("[OK] Heimdall instalado.")
                return True

    if verbose:
        print("[i] No pude instalar Heimdall automaticamente. Instalalo a mano:")
        print("      Linux:   sudo apt install heimdall-flash  (o el paquete de tu distro)")
        print("      macOS:   brew install heimdall")
        print("      Windows: https://github.com/Benjamin-Dobell/Heimdall/releases")
    return False


# ---------------- setup completo ----------------
def setup_all():
    """Prepara TODAS las dependencias de una vez (para dejar el USB listo)."""
    print("=" * 50)
    print("  Preparando dependencias (instalacion automatica)")
    print("=" * 50)
    tools = pt.ensure_tools(auto=True)
    print(f"  adb/fastboot .... {'OK' if tools else 'FALLO (revisa tu conexion)'}")
    print(f"  lz4 (Samsung) ... {'OK' if ensure_lz4(verbose=False) else 'no (opcional)'}")
    print(f"  heimdall (Samsung) {'OK' if ensure_heimdall(verbose=True) else 'no (opcional)'}")
    print("=" * 50)
    print("Listo. adb/fastboot y lz4 quedan dentro del USB / entorno.")
    print("Heimdall solo hace falta para flashear ROMs en Samsung.")
    return 0 if tools else 1
