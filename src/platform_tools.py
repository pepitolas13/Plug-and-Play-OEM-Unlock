"""
Localiza adb y fastboot. Orden de busqueda:
  1. Junto al USB (carpeta ./platform-tools/ del propio proyecto) -> plug-and-play real.
  2. En el PATH del sistema.
  3. Ofrece descargar las Google Platform Tools oficiales al USB.

Asi el USB es autocontenido: si copias platform-tools/ dentro, funciona sin instalar nada.
"""

import os
import platform
import shutil
import stat
import subprocess
import sys
import threading
import urllib.request
import zipfile

# URLs oficiales de Google (SDK Platform Tools)
PLATFORM_TOOLS_URLS = {
    "Windows": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "Linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
    "Darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_TOOLS_DIR = os.path.join(PROJECT_ROOT, "platform-tools")


def _exe(name):
    return name + ".exe" if platform.system() == "Windows" else name


def find_tool(name):
    """Devuelve la ruta a adb/fastboot, priorizando la copia local del USB."""
    local = os.path.join(LOCAL_TOOLS_DIR, _exe(name))
    if os.path.isfile(local):
        return local
    found = shutil.which(name)
    if found:
        return found
    return None


def tools_available():
    return find_tool("adb") is not None and find_tool("fastboot") is not None


def heimdall_available():
    """Heimdall (flasher open-source de Samsung, reemplazo de Odin)."""
    return find_tool("heimdall") is not None


def heimdall_detect():
    """Devuelve True si hay un Samsung en Download Mode visible para heimdall."""
    if not heimdall_available():
        return None
    try:
        rc, out, err = run("heimdall", ["detect"], timeout=15)
    except FileNotFoundError:
        return None
    blob = (out + " " + err).lower()
    if rc == 0 and "detected" in blob:
        return True
    return False


def _dl_progress(count, block, total):
    """Barra de progreso para urlretrieve (solo si la salida es un terminal)."""
    if total <= 0 or not sys.stdout.isatty():
        return
    done = min(total, count * block)
    width = 24
    filled = int(width * done / total)
    bar = "=" * filled + "-" * (width - filled)
    sys.stdout.write(f"\r    [{bar}] {int(done * 100 / total)}%  "
                     f"({done / 1048576:.1f}/{total / 1048576:.1f} MB) ")
    sys.stdout.flush()


def download_platform_tools():
    """Descarga las platform-tools oficiales dentro del USB (carpeta ./platform-tools)."""
    system = platform.system()
    url = PLATFORM_TOOLS_URLS.get(system)
    if not url:
        print(f"[!] Sistema no soportado para descarga automatica: {system}")
        return False

    zip_path = os.path.join(PROJECT_ROOT, "platform-tools.zip")
    print(f"[*] Descargando Android Platform Tools oficiales para {system}...")
    print(f"    {url}")
    try:
        urllib.request.urlretrieve(url, zip_path, _dl_progress)
        if sys.stdout.isatty():
            sys.stdout.write("\n")
        print("[*] Extrayendo...")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(PROJECT_ROOT)
        os.remove(zip_path)
        # Dar permisos de ejecucion en Unix
        if system != "Windows":
            for tool in ("adb", "fastboot"):
                p = os.path.join(LOCAL_TOOLS_DIR, tool)
                if os.path.isfile(p):
                    st = os.stat(p)
                    os.chmod(p, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        print("[OK] Platform tools instaladas en el USB (carpeta platform-tools/).")
        return True
    except Exception as e:
        print(f"[!] Error descargando platform tools: {e}")
        print("    Descargalas manualmente de: https://developer.android.com/tools/releases/platform-tools")
        return False


def run(tool, args, timeout=60, cwd=None):
    """Ejecuta adb/fastboot con argumentos y devuelve (returncode, stdout, stderr)."""
    exe = find_tool(tool)
    if not exe:
        raise FileNotFoundError(f"No se encontro '{tool}'.")
    cmd = [exe] + args
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"Timeout tras {timeout}s ejecutando {tool} {' '.join(args)}"


def parse_getvar(blob, var):
    """Extrae el valor de una variable de la salida de 'fastboot getvar <var>'.

    fastboot escribe la respuesta en stderr y MUCHOS dispositivos (y bootloaders
    antiguos) la prefijan con '(bootloader) ', p. ej. '(bootloader) unlocked: yes'.
    Este parser tolera ese prefijo y espacios sobrantes. Devuelve "" si no aparece.
    """
    for raw in (blob or "").splitlines():
        line = raw.strip()
        if line.startswith("(bootloader)"):
            line = line[len("(bootloader)"):].strip()
        if line.startswith(var + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def run_stream(tool, args, cwd=None, timeout=600):
    """Ejecuta una orden mostrando su salida EN VIVO (para flasheos largos).
    Devuelve el codigo de salida."""
    exe = find_tool(tool)
    if not exe:
        raise FileNotFoundError(f"No se encontro '{tool}'.")
    cmd = [exe] + args
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    # Watchdog: si el proceso se estanca con el pipe abierto (p. ej. fastboot en
    # "< waiting for device >" tras desconectarse el movil), el bucle
    # 'for line in proc.stdout' bloquea hasta EOF y un 'wait(timeout=...)' NUNCA
    # se alcanzaria. Un timer que mata el proceso fuerza el EOF y desbloquea.
    timed_out = {"v": False}

    def _kill_on_timeout():
        timed_out["v"] = True
        try:
            proc.kill()
        except Exception:
            pass

    timer = threading.Timer(timeout, _kill_on_timeout)
    timer.daemon = True
    timer.start()
    try:
        for line in proc.stdout:
            print("    " + line.rstrip())
        proc.wait()
    finally:
        timer.cancel()
    if timed_out["v"]:
        print(f"    [!] Timeout tras {timeout}s (proceso terminado)")
        return -1
    return proc.returncode


def usb_has_samsung_download():
    """Best-effort: detecta un Samsung en Download Mode via VID 04e8 (donde se pueda)."""
    system = platform.system()
    try:
        if system in ("Linux", "Darwin"):
            out = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=10).stdout.lower()
            return "04e8" in out
        if system == "Windows":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-PnpDevice -PresentOnly | Select-Object -ExpandProperty InstanceId"],
                capture_output=True, text=True, timeout=15).stdout.lower()
            return "vid_04e8" in out
    except Exception:
        return None
    return None


def ensure_tools(auto=False):
    """Garantiza que adb/fastboot existen; si no, ofrece descargarlas."""
    if tools_available():
        return True
    print("[!] No se encontraron adb/fastboot ni en el USB ni en el sistema.")
    if auto:
        return download_platform_tools()
    try:
        ans = input("    Descargar las herramientas oficiales al USB ahora? [S/n]: ").strip().lower()
    except EOFError:
        ans = "s"
    if ans in ("", "s", "si", "si", "y", "yes"):
        return download_platform_tools()
    return False
