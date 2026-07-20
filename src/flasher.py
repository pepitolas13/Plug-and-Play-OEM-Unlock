"""
Auto-flasheo de ROMs desde el USB.

Estructura esperada en el USB:
    roms/
      <codename>/            (ej: oriole, lisa, cheetah, beyond1lte...)
        recipe.json          (opcional, control total del flasheo)
        flash-all.sh/.bat    (opcional, imagenes de fabrica oficiales)
        boot.img, system.img, vbmeta.img, ...   (imagenes sueltas)

Prioridad de flujo:
    1. recipe.json          -> se ejecutan sus 'steps' tal cual (lo mas fiable).
    2. flash-all.sh/.bat     -> script oficial (Pixel/Google factory images).
    3. auto-deteccion        -> infiere comandos a partir de imagenes conocidas.

Los ficheros de cada paso se resuelven relativos a la carpeta de la ROM
(fastboot se ejecuta con cwd = carpeta de la ROM).
"""

import json
import os
import platform
import shlex
import tarfile

import platform_tools as pt


def _load_recipe(path):
    """Carga un recipe.json tolerando errores de sintaxis: devuelve el dict o
    None (avisando), en vez de reventar con un traceback de JSONDecodeError."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError) as e:
        print(f"   [!] recipe.json invalido ({os.path.basename(path)}): {e}")
        return None


def _safe_extractall(tf, dest):
    """extractall protegido contra path traversal (miembros que escaparian de
    'dest' con rutas absolutas o '../'). Usa el filtro 'data' en Python 3.12+."""
    dest_abs = os.path.abspath(dest)
    for m in tf.getmembers():
        target = os.path.abspath(os.path.join(dest, m.name))
        if target != dest_abs and not target.startswith(dest_abs + os.sep):
            raise ValueError(f"ruta insegura en el tar: {m.name}")
    try:
        tf.extractall(dest, filter="data")  # Python 3.12+
    except TypeError:
        tf.extractall(dest)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROMS_DIR = os.path.join(ROOT, "roms")

# Orden seguro de flasheo cuando se infiere desde imagenes sueltas.
# (particion, fichero, argumentos_extra)
INFER_ORDER = [
    ("bootloader", "bootloader.img", ""),
    ("radio", "radio.img", ""),
    ("dtbo", "dtbo.img", ""),
    ("vbmeta", "vbmeta.img", "--disable-verity --disable-verification"),
    ("vbmeta_system", "vbmeta_system.img", "--disable-verity --disable-verification"),
    ("boot", "boot.img", ""),
    ("init_boot", "init_boot.img", ""),
    ("recovery", "recovery.img", ""),
    ("vendor_boot", "vendor_boot.img", ""),
    ("super", "super.img", ""),
    ("system", "system.img", ""),
    ("vendor", "vendor.img", ""),
    ("product", "product.img", ""),
]


# --- Samsung / Heimdall ---
# Mapeo fichero -> particion PIT (nombres comunes; verifica con 'heimdall print-pit').
HEIMDALL_MAP = {
    "boot.img": "BOOT",
    "recovery.img": "RECOVERY",
    "system.img": "SYSTEM",
    "vendor.img": "VENDOR",
    "super.img": "SUPER",
    "dtbo.img": "DTBO",
    "vbmeta.img": "VBMETA",
    "userdata.img": "USERDATA",
    "cache.img": "CACHE",
    "up_param.bin": "UP_PARAM",
}


def _norm(name):
    return "".join(ch for ch in name.lower() if ch.isalnum())


def find_rom_dir(codename, model=""):
    """Busca roms/<codename> (o modelo) sin distinguir mayus/minus."""
    if not os.path.isdir(ROMS_DIR):
        return None
    targets = {_norm(codename), _norm(model)}
    targets.discard("")
    for entry in os.listdir(ROMS_DIR):
        full = os.path.join(ROMS_DIR, entry)
        if os.path.isdir(full) and _norm(entry) in targets:
            return full
    return None


def list_rom_dirs():
    if not os.path.isdir(ROMS_DIR):
        return []
    return [d for d in os.listdir(ROMS_DIR)
            if os.path.isdir(os.path.join(ROMS_DIR, d)) and not d.startswith(".")]


def build_plan(rom_dir):
    """Devuelve (kind, payload, description). kind: recipe|script|infer|empty."""
    # 1. recipe.json
    recipe_path = os.path.join(rom_dir, "recipe.json")
    if os.path.isfile(recipe_path):
        recipe = _load_recipe(recipe_path)
        if recipe is None:
            return "empty", [], "recipe.json invalido (revisa la sintaxis JSON)"
        steps = recipe.get("steps", [])
        desc = recipe.get("description", "recipe.json")
        return "recipe", steps, desc

    # 2. flash-all oficial
    script = "flash-all.bat" if platform.system() == "Windows" else "flash-all.sh"
    script_path = os.path.join(rom_dir, script)
    if os.path.isfile(script_path):
        return "script", script_path, f"script oficial {script}"

    # 3. auto-deteccion de imagenes conocidas
    steps = []
    for part, fname, extra in INFER_ORDER:
        if os.path.isfile(os.path.join(rom_dir, fname)):
            cmd = f"flash {part} {fname}"
            if extra:
                cmd += " " + extra
            steps.append(cmd)
    if steps:
        return "infer", steps, "auto-deteccion de imagenes"

    # 4. zip flasheable por fastboot (fastboot update)
    zips = [f for f in os.listdir(rom_dir) if f.lower().endswith(".zip")]
    if len(zips) == 1:
        # Citamos el nombre por si lleva espacios (se parsea con shlex despues).
        return "infer", [f"update {shlex.quote(zips[0])}"], f"fastboot update {zips[0]}"

    return "empty", [], "sin ficheros flasheables reconocidos"


def _print_plan(kind, payload, desc, rom_dir):
    print("   Carpeta ROM ... " + rom_dir)
    print("   Metodo ........ " + desc)
    if kind in ("recipe", "infer"):
        print("   Pasos:")
        for i, step in enumerate(payload, 1):
            print(f"     {i}. fastboot {step}")
    elif kind == "script":
        print("   Se ejecutara el script oficial de fabrica.")


def execute_plan(kind, payload, rom_dir):
    """Ejecuta el plan de flasheo. Devuelve True/False."""
    if kind == "script":
        print("\n   Ejecutando script oficial (salida en vivo)...")
        if platform.system() == "Windows":
            rc = pt.run_stream("cmd", ["/c", payload], cwd=rom_dir)
        else:
            rc = pt.run_stream("sh", [payload], cwd=rom_dir)
        return rc == 0

    for step in payload:
        # shlex respeta comillas -> nombres de fichero con espacios intactos.
        args = shlex.split(step)
        # Solo permitimos verbos de flasheo seguros de fastboot.
        if args and args[0] not in ("flash", "reboot", "update", "erase", "-w", "set_active", "--set-active"):
            print(f"   [!] Paso ignorado por seguridad: fastboot {step}")
            continue
        print(f"\n   > fastboot {step}")
        rc = pt.run_stream("fastboot", args, cwd=rom_dir)
        if rc != 0:
            # 'reboot' puede devolver !=0 al perder la conexion; no es fatal.
            if args and args[0] == "reboot":
                print("   (reboot: continuo)")
                continue
            print(f"   [X] Fallo en: fastboot {step} (codigo {rc})")
            return False
    return True


def maybe_flash(info, auto, ask_fn, c_fn):
    """Punto de entrada: si hay ROM para este dispositivo, la flashea (con 1 confirmacion).
    Devuelve None si no habia nada que hacer, True/False segun resultado."""
    codename = info.get("codename", "") or ""
    model = info.get("model", "") or ""
    rom_dir = find_rom_dir(codename, model)

    if not rom_dir:
        available = list_rom_dirs()
        if available:
            print(c_fn(f"\n[i] No hay carpeta de ROM para '{codename}'. "
                       f"Carpetas disponibles: {', '.join(available)}", "cyan"))
        return None

    kind, payload, desc = build_plan(rom_dir)
    if kind == "empty":
        print(c_fn(f"\n[i] Carpeta {rom_dir} sin ficheros flasheables.", "cyan"))
        return None

    print(c_fn("\nFLASHEO DE ROM DETECTADO", "bold"))
    _print_plan(kind, payload, desc, rom_dir)
    print(c_fn("   *** Flashear una ROM incorrecta puede inutilizar el telefono. ***", "red"))
    print(c_fn(f"   *** Asegurate de que la ROM es para: {codename} / {model} ***", "yellow"))

    # Siempre pedimos UNA confirmacion, incluso en --auto (riesgo de brick).
    if not ask_fn("Flashear esta ROM ahora?", default_yes=False):
        print("   Flasheo cancelado.")
        return None

    ok = execute_plan(kind, payload, rom_dir)
    if ok:
        print(c_fn("\n[OK] ROM flasheada. Reiniciando el telefono...", "green"))
        try:
            pt.run("fastboot", ["reboot"], timeout=30)
        except FileNotFoundError:
            pass
    else:
        print(c_fn("\n[X] El flasheo no se completo. Revisa los mensajes de arriba.", "red"))
    return ok


# ============================================================
#  SAMSUNG - flasheo via Heimdall (reemplazo open-source de Odin)
# ============================================================
def _decompress_lz4(src, dst):
    """Descomprime un .img.lz4 (formato LZ4 frame de Samsung) a .img crudo.
    Intenta: modulo python 'lz4' -> comando 'lz4' -> comando 'unlz4'."""
    import shutil as _sh
    import subprocess as _sp
    # 1. Modulo python lz4 (streaming, no carga todo en memoria)
    try:
        import lz4.frame as _l
        with _l.open(src, "rb") as fi, open(dst, "wb") as fo:
            _sh.copyfileobj(fi, fo)
        return True
    except ImportError:
        pass
    except Exception:
        if os.path.isfile(dst):
            os.remove(dst)
    # 2. Comando lz4 del sistema
    if _sh.which("lz4"):
        try:
            _sp.run(["lz4", "-d", "-f", src, dst], check=True, capture_output=True)
            return True
        except Exception:
            pass
    # 3. Comando unlz4
    if _sh.which("unlz4"):
        try:
            _sp.run(["unlz4", src, dst], check=True, capture_output=True)
            return True
        except Exception:
            pass
    return False


def _decompress_all_lz4(work_dir):
    """Descomprime automaticamente todos los *.img.lz4 de work_dir a *.img.
    Devuelve (n_ok, fallidos:list)."""
    lz4s = [f for f in os.listdir(work_dir) if f.lower().endswith(".img.lz4")]
    ok, failed = 0, []
    for f in lz4s:
        dst = os.path.join(work_dir, f[:-4])  # quita '.lz4'
        if os.path.isfile(dst):
            ok += 1
            continue
        print(f"   Descomprimiendo {f} -> {os.path.basename(dst)} ...")
        if _decompress_lz4(os.path.join(work_dir, f), dst):
            ok += 1
        else:
            failed.append(f)
    return ok, failed


def _extract_tars(rom_dir):
    """Extrae .tar/.tar.md5 de Samsung a una subcarpeta _extracted/.
    Devuelve la carpeta de salida o None si no habia tars."""
    tars = [f for f in os.listdir(rom_dir)
            if f.lower().endswith(".tar") or f.lower().endswith(".tar.md5")]
    if not tars:
        return None
    out_dir = os.path.join(rom_dir, "_extracted")
    os.makedirs(out_dir, exist_ok=True)
    for t in tars:
        try:
            with tarfile.open(os.path.join(rom_dir, t)) as tf:
                _safe_extractall(tf, out_dir)
        except Exception as e:
            print(f"   [!] No se pudo extraer {t}: {e}")
    return out_dir


def build_samsung_plan(rom_dir):
    """Devuelve (work_dir, steps, description) para heimdall.
    steps = lista de listas de argumentos para 'heimdall flash'."""
    # 1. recipe.json con tool heimdall
    recipe_path = os.path.join(rom_dir, "recipe.json")
    if os.path.isfile(recipe_path):
        recipe = _load_recipe(recipe_path)
        if recipe and recipe.get("tool", "").lower() == "heimdall":
            _decompress_all_lz4(rom_dir)  # por si el recipe apunta a .img descomprimibles
            steps = [shlex.split(s) for s in recipe.get("steps", [])]
            return rom_dir, steps, recipe.get("description", "recipe.json (heimdall)")

    # 2. carpeta de trabajo: la propia, o _extracted/ si hay .tar
    work_dir = rom_dir
    if not [f for f in os.listdir(rom_dir) if f.lower().endswith((".img", ".img.lz4"))]:
        extracted = _extract_tars(rom_dir)
        if extracted:
            work_dir = extracted

    # 3. descomprimir automaticamente cualquier .img.lz4 -> .img
    _, failed = _decompress_all_lz4(work_dir)
    imgs = [f for f in os.listdir(work_dir) if f.lower().endswith(".img")]

    if not imgs:
        if failed:
            return None, [], "lz4"  # habia .lz4 pero no se pudo descomprimir
        return None, [], "sin imagenes flasheables"

    # Construir un unico 'flash' con todas las particiones reconocidas
    flash_args = ["flash"]
    recognized = []
    for fname in imgs:
        part = HEIMDALL_MAP.get(fname.lower())
        if part:
            flash_args += [f"--{part}", fname]
            recognized.append(f"{part}={fname}")
    if len(flash_args) == 1:
        return work_dir, [], "imagenes no reconocidas (usa recipe.json con los nombres PIT)"
    return work_dir, [flash_args], "auto: " + ", ".join(recognized)


def flash_samsung(info, ask_fn, c_fn):
    """Flashea un Samsung via Heimdall. Devuelve None/True/False."""
    rom_dir = find_rom_dir(info.get("codename", ""), info.get("model", ""))
    if not rom_dir:
        return None

    if not pt.heimdall_available():
        print(c_fn("\n[i] Hay una ROM para este Samsung pero falta 'heimdall'.", "cyan"))
        import deps
        if not deps.ensure_heimdall(auto=True):
            print("    Alternativa: usa Odin (Windows) con el firmware en .tar.md5.")
            return None

    work_dir, steps, desc = build_samsung_plan(rom_dir)
    if desc == "lz4" or not steps:
        print(c_fn("\n[i] No pude preparar un flasheo Heimdall automatico.", "cyan"))
        if desc == "lz4":
            print("    El firmware trae imagenes .img.lz4 y no encontre ninguna herramienta")
            print("    para descomprimirlas automaticamente. Instala una de estas:")
            print("      - Python:  pip install lz4")
            print("      - Linux:   apt install lz4        (o el paquete 'lz4')")
            print("      - macOS:   brew install lz4")
            print("    y vuelve a ejecutar: se descomprimiran solas.")
        else:
            print("    Anade un recipe.json con los nombres de particion PIT correctos.")
            print("    Consulta las particiones con: heimdall print-pit")
        return None

    # Comprobar que el telefono esta en Download Mode
    det = pt.heimdall_detect()
    if det is not True:
        print(c_fn("\n   Para flashear Samsung el telefono debe estar en Download Mode.", "yellow"))
        print("   Apaga el telefono, manten Vol+ y Vol- y conecta el cable (o deja que")
        print("   la herramienta lo reinicie ahi). Pulsa Vol+ para entrar en Download Mode.")
        if not ask_fn("El telefono ya esta en Download Mode?", default_yes=False):
            print("   Flasheo Samsung cancelado.")
            return None

    print(c_fn("\nFLASHEO SAMSUNG (Heimdall) DETECTADO", "bold"))
    print("   Carpeta ROM ... " + rom_dir)
    print("   Metodo ........ " + desc)
    for st in steps:
        print("   > heimdall " + " ".join(st))
    print(c_fn("   *** Una ROM/particion incorrecta puede inutilizar el telefono. ***", "red"))
    print(c_fn(f"   *** Verifica que es para: {info.get('model','?')} ***", "yellow"))

    if not ask_fn("Flashear con Heimdall ahora?", default_yes=False):
        print("   Flasheo cancelado.")
        return None

    for st in steps:
        args = list(st)
        # Heimdall reinicia el telefono por defecto tras flashear; NO existe un
        # flag '--reboot' (anadirlo haria que heimdall imprima el uso y salga con
        # error). Respetamos '--no-reboot' si el usuario lo puso en el recipe.
        print(c_fn(f"\n   > heimdall {' '.join(args)}", "bold"))
        rc = pt.run_stream("heimdall", args, cwd=work_dir)
        if rc != 0:
            print(c_fn(f"   [X] Heimdall fallo (codigo {rc}).", "red"))
            return False
    print(c_fn("\n[OK] ROM Samsung flasheada con Heimdall.", "green"))
    return True
