#!/usr/bin/env python3
"""
Plug-and-Play OEM Unlock
========================
Herramienta portatil (desde USB) que detecta tu telefono Android y te guia
para desbloquear el bootloader (OEM Unlock) con los comandos correctos segun
el fabricante, automatizando todo lo que Android permite automatizar.

IMPORTANTE - LIMITE FISICO DE ANDROID:
  * El toggle "Desbloqueo de OEM" (Opciones de desarrollador) SOLO se puede
    activar tocando la pantalla del telefono. Ningun software puede activarlo
    remotamente: es la proteccion antirrobo de Android. Esta herramienta te
    guia por ese paso manual y automatiza el resto.
  * Desbloquear el bootloader BORRA TODOS LOS DATOS del telefono y requiere
    confirmacion fisica con los botones del dispositivo.

Uso: python oem_unlock.py [--auto-tools] [--yes]
"""

import argparse
import sys
import time

import platform_tools as pt
import device_db as db
import flasher
import deps
import windrivers

VERSION = "1.0.0"


# ---------- UI helpers ----------
C = {
    "reset": "\033[0m", "bold": "\033[1m", "red": "\033[91m",
    "green": "\033[92m", "yellow": "\033[93m", "blue": "\033[94m",
    "cyan": "\033[96m",
}


# Modo totalmente automatico: sin preguntas de software (los pasos fisicos del
# telefono siguen siendo obligatorios porque Android no permite saltarlos).
AUTO = False


def c(text, color):
    return f"{C.get(color,'')}{text}{C['reset']}"


def banner():
    print(c("=" * 60, "cyan"))
    print(c("   PLUG-AND-PLAY OEM UNLOCK  v" + VERSION, "bold"))
    print(c("   Desbloqueo de bootloader guiado y multi-marca", "cyan"))
    print(c("=" * 60, "cyan"))


def hr():
    print(c("-" * 60, "blue"))


def ask(prompt, default_yes=True):
    # En modo automatico asumimos la respuesta por defecto sin preguntar.
    if AUTO:
        return default_yes
    _drain_stdin()  # descarta teclas escritas antes (evita auto-responder)
    suffix = "[S/n]" if default_yes else "[s/N]"
    try:
        ans = input(f"{c('?', 'yellow')} {prompt} {suffix}: ").strip().lower()
    except EOFError:
        return default_yes
    if ans == "":
        return default_yes
    return ans in ("s", "si", "y", "yes")


def ask_confirm(prompt, default_yes=False):
    """Confirmacion que SIEMPRE pregunta, incluso en modo --auto, porque la
    accion es destructiva (flasheo/borrado). Es la unica confirmacion humana."""
    _drain_stdin()  # descarta teclas escritas antes (evita auto-confirmar/cancelar)
    suffix = "[S/n]" if default_yes else "[s/N]"
    try:
        ans = input(f"{c('?', 'yellow')} {prompt} {suffix}: ").strip().lower()
    except EOFError:
        return default_yes
    if ans == "":
        return default_yes
    return ans in ("s", "si", "y", "yes")


def wait_enter(msg="Pulsa ENTER cuando lo hayas hecho..."):
    _drain_stdin()  # ignora teclas escritas antes: exige un ENTER consciente
    try:
        input(c(">> " + msg, "yellow"))
    except EOFError:
        pass


# ---------- UX: esperas animadas, contador, banners ----------
_SPIN = "|/-\\"


def _isatty():
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _clear_line():
    if _isatty():
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


def _bar(remaining, total, width=22):
    if total <= 0:
        total = 1
    filled = max(0, min(width, int(round(width * remaining / total))))
    return "=" * filled + "-" * (width - filled)


def _fmt_mmss(secs):
    m, s = divmod(int(secs), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def bell():
    if _isatty():
        sys.stdout.write("\a")
        sys.stdout.flush()


# Sentinela: el usuario pidio saltar la cuenta atras (pulso una tecla).
SKIP = object()


def _drain_stdin():
    """Descarta la entrada pendiente en el buffer (teclas escritas antes de tiempo)
    para que no auto-respondan un prompt posterior. No-op si no hay terminal.
    Esto evita el bug de que un ENTER pulsado durante la cuenta atras responda
    solo el '(s/N)' de una confirmacion destructiva."""
    if not _isatty():
        return
    try:
        if windrivers.is_windows():
            import msvcrt
            while msvcrt.kbhit():
                msvcrt.getwch()
        else:
            import termios
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass


def _skip_key_pressed():
    """True (consumiendo el buffer) si el usuario ha pulsado una tecla/ENTER, de
    forma NO bloqueante. En Windows detecta cualquier tecla; en Unix (modo cocido)
    se activa al pulsar ENTER. Solo con terminal."""
    if not _isatty():
        return False
    try:
        if windrivers.is_windows():
            import msvcrt
            if msvcrt.kbhit():
                while msvcrt.kbhit():
                    msvcrt.getwch()
                return True
            return False
        import select
        import termios
        if select.select([sys.stdin], [], [], 0)[0]:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
            return True
        return False
    except Exception:
        return False


def animated_wait(poll_fn, timeout, render, poll_every=1.5, frame=0.25, skippable=False):
    """Espera hasta 'timeout' s. Cada 'poll_every' s llama poll_fn(); si devuelve
    algo truthy lo retorna. Entre polls anima con render(remaining, i). Devuelve el
    valor de poll_fn, None si se agota el tiempo, o SKIP si 'skippable' y el usuario
    pulsa una tecla. Sin terminal, degrada a esperas silenciosas."""
    tty = _isatty()
    start = time.monotonic()
    last = -1e9
    i = 0
    while True:
        elapsed = time.monotonic() - start
        remaining = timeout - elapsed
        if remaining <= 0:
            _clear_line()
            return None
        if elapsed - last >= poll_every:
            res = poll_fn()
            last = elapsed
            if res:
                _clear_line()
                return res
        if skippable and tty and _skip_key_pressed():
            _clear_line()
            return SKIP
        if tty:
            render(remaining, i)
            i += 1
            time.sleep(frame)
        else:
            time.sleep(poll_every)


def _mk_countdown(label, total, hint=""):
    """Devuelve una funcion render(remaining, i) con barra + cuenta atras."""
    def render(remaining, i):
        tail = f"  {c(hint, 'cyan')}" if hint else ""
        sys.stdout.write(
            f"\r   {c(label, 'cyan')} [{c(_bar(remaining, total), 'blue')}] "
            f"{c(str(int(remaining)) + 's', 'yellow')}{tail} ")
        sys.stdout.flush()
    return render


def action_required(title, lines):
    """Banner llamativo + campana para los pasos FISICOS que hace el usuario."""
    bell()
    print(c("\n  " + "=" * 56, "yellow"))
    print(c("  >>> " + title, "bold"))
    print(c("  " + "-" * 56, "yellow"))
    for ln in lines:
        print("   " + ln)
    print(c("  " + "=" * 56, "yellow"))


def _enable_ansi_windows():
    """Activa el procesamiento de secuencias ANSI en la consola de Windows 10+
    (si no, los colores saldrian como texto tipo '<-[92m')."""
    if not windrivers.is_windows():
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        # ENABLE_PROCESSED_OUTPUT | ENABLE_WRAP_AT_EOL | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        k.SetConsoleMode(k.GetStdHandle(-11), 7)
    except Exception:
        pass


# ---------- Detection ----------
def wait_for_device(timeout=180):
    """Espera a que aparezca un telefono en modo ADB o fastboot (con spinner)."""
    print(c("[*] Esperando a que conectes un telefono por USB...", "cyan"))
    print("    (Enciende el telefono, desbloquea la pantalla y acepta la")
    print("     depuracion USB si te lo pregunta.)")
    warned = {"v": False}

    def poll():
        adb = db.detect_adb_devices()
        if any(d["state"] == "device" for d in adb):
            return "adb"
        if db.detect_fastboot_devices():
            return "fastboot"
        if not warned["v"] and any(d["state"] == "unauthorized" for d in adb):
            _clear_line()
            bell()
            print(c("[!] Telefono detectado pero SIN autorizar.", "yellow"))
            print("    Mira la pantalla del telefono y pulsa 'Permitir' en el")
            print("    dialogo de depuracion USB (marca 'Permitir siempre').")
            warned["v"] = True
        return None

    def render(remaining, i):
        sys.stdout.write(f"\r   {c(_SPIN[i % 4], 'cyan')} Buscando telefono...  "
                         f"{c(_fmt_mmss(timeout - remaining), 'yellow')} ")
        sys.stdout.flush()

    return animated_wait(poll, timeout, render)


def show_device_info(info):
    hr()
    print(c("  TELEFONO DETECTADO", "bold"))
    print(f"   Marca .......... {c(info['brand'] or '?', 'green')}")
    print(f"   Fabricante ..... {info['manufacturer'] or '?'}")
    print(f"   Modelo ......... {c(info['model'] or '?', 'green')}")
    print(f"   Nombre clave ... {info['codename'] or '?'}")
    if info.get("android"):
        print(f"   Android ........ {info['android']}")
    print(f"   Perfil ......... {c(info['vendor_key'], 'cyan')}")
    hr()


# ---------- Guided steps ----------
def check_oem_toggle():
    """Comprueba (cuando es posible) si el toggle OEM esta activado."""
    try:
        rc, out, _ = pt.run("adb", ["shell", "getprop", "sys.oem_unlock_allowed"], timeout=15)
    except FileNotFoundError:
        return None
    if rc == 0 and out.strip() in ("0", "1"):
        return out.strip() == "1"
    return None  # desconocido en este dispositivo


def _print_oem_instructions(info):
    action_required("ACCION EN EL TELEFONO: activar 'Desbloqueo de OEM'", [
        "Este paso NO puede hacerlo ningun software (proteccion de Android).",
        "En el telefono:",
        "  1. Ajustes > Acerca del telefono",
        "  2. Pulsa 7 veces en 'Numero de compilacion' (activa Opciones de desarrollador)",
        "  3. Ajustes > Sistema > Opciones de desarrollador",
        c("  4. Activa 'Desbloqueo de OEM' (OEM unlocking)", "yellow"),
    ])
    if info["profile"].get("needs_account"):
        print(c("   NOTA: Este fabricante ademas exige vincular una cuenta y/o esperar.", "yellow"))


def guide_oem_toggle(info):
    print(c("\nPASO 1 - Activar 'Desbloqueo de OEM' (manual, obligatorio)", "bold"))
    state = check_oem_toggle()
    if state is True:
        print(c("   [OK] El toggle 'Desbloqueo de OEM' YA esta activado.", "green"))
        return True
    if state is False:
        print(c("   [!] El toggle 'Desbloqueo de OEM' esta DESACTIVADO.", "yellow"))
    _print_oem_instructions(info)

    if AUTO:
        # Modo automatico: esperamos (sondeando) a que actives el toggle y seguimos solos.
        if state is None:
            print(c("   (No puedo leer el estado del toggle en este modelo; espero 30s y sigo.)", "cyan"))
            for _ in range(15):
                time.sleep(2)
            return True
        print(c("   Esperando a que actives el toggle en el telefono (hasta 5 min)...", "cyan"))
        for _ in range(150):
            if check_oem_toggle() is True:
                print(c("   [OK] Toggle detectado como ACTIVADO. Continuo automaticamente.", "green"))
                return True
            time.sleep(2)
        print(c("   [!] Tiempo agotado esperando el toggle.", "red"))
        return False

    wait_enter()
    state = check_oem_toggle()
    if state is False:
        print(c("   [!] Sigue detectandose desactivado. Revisalo antes de continuar.", "red"))
        return ask("Continuar de todos modos?", default_yes=False)
    return True


def _wait_for_fastboot(seconds=60):
    """Sondea hasta 'seconds' segundos a que el telefono aparezca en fastboot."""
    for _ in range(max(1, seconds // 2)):
        if db.detect_fastboot_devices():
            return True
        time.sleep(2)
    return bool(db.detect_fastboot_devices())


def reboot_to_bootloader():
    print(c("\nPASO 2 - Reiniciando a modo bootloader (fastboot)...", "bold"))
    try:
        rc, out, err = pt.run("adb", ["reboot", "bootloader"], timeout=30)
    except FileNotFoundError:
        rc, out, err = -1, "", "adb no disponible"
    if rc != 0:
        print(c(f"   [!] No se pudo reiniciar via ADB: {err or out}", "red"))
        print("   Reinicia manualmente a fastboot (apaga y manten Power + Vol-).")
    total = 60
    hint = ("ENTER para instalar el driver ya" if windrivers.is_windows()
            else "ENTER para saltar")
    found = animated_wait(lambda: bool(db.detect_fastboot_devices()), total,
                          _mk_countdown("Esperando fastboot", total, hint),
                          skippable=True)
    if found is True:
        print(c("   [OK] Dispositivo en fastboot.", "green"))
        return True
    if found is SKIP:
        print(c("   [>] Saltas la espera: preparo el driver ahora mismo.", "cyan"))

    # En Windows, la causa tipica de "no aparece" es el driver USB (sobre todo en
    # MediaTek). Al agotarse (o saltarse) la cuenta atras lo instalamos/FORZAMOS
    # solos y reintentamos. Requiere 1 clic de permiso (UAC): ningun programa
    # puede instalar un driver sin esa aprobacion.
    if windrivers.is_windows():
        if found is None:
            print(c("   [.] Cuenta atras agotada: el telefono no aparece en fastboot.", "cyan"))
        print(c("   [i] En Windows suele faltar el driver USB (MediaTek). Lo instalo/FUERZO ahora.", "cyan"))
        print(c("       Acepta el aviso de seguridad de Windows ('Si') cuando salga.", "cyan"))
        if windrivers.setup_fastboot_windows():
            print(c("   [*] Driver enlazado. Reintentando deteccion...", "cyan"))
            found2 = animated_wait(lambda: bool(db.detect_fastboot_devices()), 30,
                                   _mk_countdown("Esperando fastboot", 30, "ENTER para saltar"),
                                   skippable=True)
            if found2 is True:
                print(c("   [OK] Dispositivo en fastboot.", "green"))
                return True
        print(c("   [i] Si aun no aparece: prueba un puerto USB 2.0 (los negros) directo a la", "yellow"))
        print(c("       placa, o usa Linux (./unlock.sh), donde fastboot funciona SIN drivers.", "yellow"))

    print(c("   [!] No aparecio en fastboot.", "red"))
    return False


def run_unlock(profile, confirmed):
    method = profile.get("method", "fastboot")

    if method in ("fastboot", "fastboot_code", "deep_testing"):
        cmd = profile.get("unlock_command")

        if method == "fastboot_code":
            return handle_code_based(profile)

        if method == "deep_testing":
            print(c("\n   Este fabricante (Oppo/Realme) requiere la 'In-Depth/Deep Test App'", "yellow"))
            print("   oficial para habilitar el desbloqueo ANTES de fastboot.")
            print(f"   Herramienta: {profile.get('external_tool','')}")
            if not ask("La app ya esta configurada y quieres intentar fastboot?", default_yes=True):
                return False

        print(c(f"\nPASO 3 - Ejecutando: {cmd}", "bold"))
        action_required("ACCION EN EL TELEFONO: confirmar el desbloqueo", [
            c("*** ESTO BORRARA TODOS LOS DATOS DEL TELEFONO ***", "red"),
            "Cuando el comando lo pida, en la pantalla del telefono:",
            "  - Usa VOLUMEN para elegir 'Unlock the bootloader'",
            "  - Pulsa POWER para confirmar.",
        ])
        if not confirmed and not ask("Confirmas que quieres desbloquear (se borra todo)?", default_yes=False):
            print("   Cancelado.")
            return False
        args = cmd.split()[1:]  # quita el 'fastboot'
        # Salida EN VIVO: el comando bloquea esperando la confirmacion FISICA en
        # la pantalla; en vivo el usuario ve el aviso del bootloader mientras
        # pulsa los botones (con run() no veria nada durante la espera).
        rc = pt.run_stream("fastboot", args, timeout=300)
        if rc == 0:
            return True
        if rc == -1:
            # Timeout/proceso terminado: NO reintentamos con el fallback, para no
            # lanzar un SEGUNDO desbloqueo sobre un movil que quiza ya confirmo.
            print(c("   [!] Sin respuesta a tiempo. Mira la pantalla del telefono y revisa el cable.", "yellow"))
            return False
        # Fallback solo ante un fallo REAL del comando (p. ej. 'unknown command').
        fb = profile.get("fallback_command")
        if fb:
            print(c(f"   Intentando comando alternativo: {fb}", "yellow"))
            rc2 = pt.run_stream("fastboot", fb.split()[1:], timeout=300)
            return rc2 == 0
        return False

    if method == "mi_unlock":
        return handle_xiaomi(profile)

    if method == "download_mode":
        return handle_samsung(profile)

    if method == "manual_web":
        return handle_manual_web(profile)

    if method == "mtkclient":
        return handle_mtkclient(profile)

    if method == "locked":
        return handle_locked(profile)

    print(c(f"[!] Metodo desconocido: {method}", "red"))
    return False


def handle_manual_web(profile):
    print(c("\n  DESBLOQUEO POR TOKEN/WEB (HTC / LG / Meizu)", "bold"))
    get_cmd = profile.get("get_data_command")
    if get_cmd:
        print(f"   Leyendo identificador del dispositivo ({get_cmd})...")
        try:
            rc, out, err = pt.run("fastboot", get_cmd.split()[1:], timeout=30)
            print((out + "\n" + err).strip())
        except FileNotFoundError:
            print(c("   (Necesitas estar en modo bootloader para leer el token.)", "yellow"))
    print(c(f"\n   Portal oficial: {profile.get('external_tool','')}", "yellow"))
    print(f"   {profile.get('notes','')}")
    print(c("   Este flujo requiere descargar un archivo de desbloqueo desde la web", "cyan"))
    print(c("   del fabricante y flashearlo manualmente. No se puede automatizar.", "cyan"))
    return None  # flujo externo


def _mtk_tool():
    """Localiza el ejecutable de mtkclient (nombres posibles: mtk / mtkclient)."""
    for name in ("mtk", "mtkclient"):
        if pt.find_tool(name):
            return name
    return None


def handle_mtkclient(profile, unofficial=False):
    """Ruta MediaTek via mtkclient (modo BROM). Metodo de la COMUNIDAD, NO oficial:
    se muestra el riesgo y solo se ejecuta con una confirmacion destructiva."""
    print(c("\n  DESBLOQUEO MEDIATEK via mtkclient (modo BROM)", "bold"))
    print(c("   *** Metodo de la COMUNIDAD, NO oficial. Bajo tu responsabilidad. ***", "red"))
    print(c("   *** Puede inutilizar (brickear) el telefono. Borra todos los datos. ***", "red"))
    print("   Solo funciona en telefonos con SoC MediaTek (MTK).")

    tool = _mtk_tool()
    if not tool:
        print(c("\n   [!] 'mtkclient' no esta instalado.", "yellow"))
        print("   Instalalo (necesita Python 3 + libusb):")
        print("     pip install mtkclient")
        print("     (o)  git clone https://github.com/bkerler/mtkclient")
        print(f"   Mas info: {profile.get('unofficial_tool', 'https://github.com/bkerler/mtkclient')}")
        return None

    print(c(f"\n   [OK] mtkclient encontrado ({tool}).", "green"))
    if windrivers.is_windows():
        # El modo BROM necesita el driver UsbDk en Windows: lo instalamos solo.
        windrivers.ensure_usbdk()
    print("   Pasos para entrar en modo BROM:")
    print("     1. APAGA el telefono del todo (desconecta el cable).")
    print("     2. Manten " + c("Vol+ y Vol-", "yellow") + " (o usa el test point del modelo)")
    print("        y conecta el USB para entrar en modo " + c("BROM", "yellow") + ".")
    print("   La app lanzara: " + c("mtk da seccfg unlock", "cyan"))

    if AUTO:
        print(c("\n   [i] mtkclient necesita timing fisico (BROM); no se automatiza en --auto.", "cyan"))
        print(c("       Ejecutalo sin --auto con el telefono en modo BROM.", "cyan"))
        return None

    if not ask_confirm("El telefono esta en modo BROM y quieres DESBLOQUEAR ahora (se borra todo)?",
                       default_yes=False):
        print("   Cancelado.")
        return False

    print(c(f"\n   > {tool} da seccfg unlock", "bold"))
    try:
        rc = pt.run_stream(tool, ["da", "seccfg", "unlock"], timeout=600)
    except FileNotFoundError:
        print(c("   [!] No se pudo ejecutar mtkclient.", "red"))
        return None
    if rc == 0:
        print(c("\n[OK] mtkclient termino sin errores. Revisa el telefono.", "green"))
        return True
    print(c(f"\n[X] mtkclient devolvio codigo {rc}. Revisa la salida de arriba.", "red"))
    return False


def handle_locked(profile):
    print(c("\n  SIN METODO OFICIAL DE DESBLOQUEO", "red"))
    print(f"   {profile.get('notes','')}")

    unof = profile.get("unofficial_method")
    if unof == "mtkclient":
        print(c("\n   [i] Hay una ruta NO OFICIAL de la comunidad para modelos MediaTek.", "yellow"))
        if AUTO:
            print(c("       (Modo --auto: no ejecuto rutas no oficiales. Reejecuta sin --auto.)", "cyan"))
            return False
        if ask("Quieres ver/usar la ruta no oficial (mtkclient, arriesgada)?", default_yes=False):
            return handle_mtkclient(profile, unofficial=True)
        return False
    if unof == "testpoint":
        print(c("\n   [i] No hay metodo por software. La unica via NO oficial conocida es por", "yellow"))
        print("   " + c("test point", "yellow") + " de hardware + servicio de pago (p. ej. Kirin de Huawei/Honor).")
        print(f"   Herramienta/servicio: {profile.get('unofficial_tool', '(varios, de pago)')}")
        print(c("   Es arriesgado, no garantizado y puede ser una estafa. Bajo tu responsabilidad.", "red"))
        return False

    print(c("   No existe forma segura ni oficial de desbloquear este bootloader.", "yellow"))
    print("   Cualquier 'servicio' de pago que lo prometa es arriesgado y puede")
    print("   dejar el telefono inservible o ser una estafa.")
    return False


def handle_code_based(profile):
    print(c("\nPASO 3 - Desbloqueo por CODIGO (Motorola/Sony)", "bold"))
    get_cmd = profile.get("get_data_command", "fastboot oem get_unlock_data")
    print(f"   Leyendo datos del dispositivo ({get_cmd})...")
    rc, out, err = pt.run("fastboot", get_cmd.split()[1:], timeout=30)
    print((out + "\n" + err).strip())
    print(c(f"\n   1. Ve al portal oficial: {profile.get('external_tool','')}", "yellow"))
    print("   2. Pega ahi los datos de arriba (o el IMEI en Sony).")
    print("   3. Recibiras un CODIGO de desbloqueo.")
    if AUTO:
        print(c("   [i] Este fabricante necesita un codigo del portal web; no se puede", "cyan"))
        print(c("       automatizar. Vuelve a ejecutar sin --auto cuando tengas el codigo.", "cyan"))
        return None
    try:
        code = input(c("   Pega aqui el codigo recibido (o ENTER para cancelar): ", "yellow")).strip()
    except EOFError:
        code = ""
    if not code:
        print("   Cancelado.")
        return False
    cmd = profile["unlock_command"].format(unlock_code=code)
    print(c(f"   Ejecutando: {cmd}", "bold"))
    print(c("   *** ESTO BORRARA TODOS LOS DATOS ***", "red"))
    if not ask("Continuar?", default_yes=False):
        return False
    rc, out, err = pt.run("fastboot", cmd.split()[1:], timeout=120)
    print((out + "\n" + err).strip())
    return rc == 0


def handle_xiaomi(profile):
    print(c("\n  XIAOMI / REDMI / POCO - flujo especial", "bold"))
    print("   Xiaomi NO permite desbloqueo por fastboot directo. Pasos:")
    print("     1. En el telefono: Ajustes > Acerca > vincula tu cuenta Mi.")
    print("     2. Ajustes > Opciones de desarrollador > 'Estado de desbloqueo Mi'")
    print("        > 'Anadir cuenta y dispositivo'.")
    print(c(f"     3. Espera el periodo obligatorio (~{profile.get('waiting_days',7)} dias).", "yellow"))
    print(f"     4. Usa la {profile.get('external_tool','Mi Unlock Tool')} en Windows.")
    print("   Esta herramienta te ha preparado el telefono; el desbloqueo final")
    print("   lo hace la Mi Unlock Tool oficial (requisito de Xiaomi).")
    return None  # flujo externo


def handle_samsung(profile):
    print(c("\n  SAMSUNG GALAXY - flujo Download Mode (semi-automatico)", "bold"))
    print("   Samsung NO usa fastboot; el desbloqueo es una accion fisica en")
    print("   Download Mode que ningun software puede pulsar por ti.")
    print("   Automatizo lo que se puede: reiniciar a Download Mode.")

    # Paso automatico: reiniciar a Download Mode via adb.
    print(c("\n   Reiniciando el telefono a Download Mode (adb reboot download)...", "cyan"))
    try:
        rc, out, err = pt.run("adb", ["reboot", "download"], timeout=30)
    except FileNotFoundError:
        rc, out, err = -1, "", "adb no disponible"
    if rc != 0:
        print(c(f"   [!] No se pudo automatizar: {err or out}", "yellow"))
        print("   Hazlo a mano: apaga el telefono, manten Vol+ y Vol- y conecta el cable.")
    else:
        # Esperar a que el dispositivo salga de adb (ha reiniciado)
        for _ in range(15):
            if not db.detect_adb_devices():
                break
            time.sleep(1)
        det = pt.usb_has_samsung_download()
        if det is True:
            print(c("   [OK] Samsung detectado en Download Mode.", "green"))
        elif det is None:
            print(c("   [i] No pude confirmar el modo por USB (normal en este SO).", "cyan"))
        else:
            print(c("   [i] Esperando a que entre en Download Mode...", "cyan"))

    print(c("\n   AHORA, en la pantalla del telefono (2 pulsaciones fisicas):", "bold"))
    print("     1. Manten " + c("Vol+", "yellow") + " hasta la pantalla 'Unlock Bootloader'.")
    print("     2. Pulsa " + c("Vol+", "yellow") + " otra vez para CONFIRMAR el desbloqueo.")
    print(c("   Se borraran todos los datos. Tras reiniciar, vuelve a activar", "yellow"))
    print(c("   'Desbloqueo de OEM' en Opciones de desarrollador.", "yellow"))
    print(c("\n   Nota: variantes USA/Canada (Snapdragon) NO tienen esta opcion.", "cyan"))
    return None  # el desbloqueo final es fisico


def verify_unlocked():
    print(c("\nVerificando estado del bootloader...", "cyan"))
    try:
        rc, out, err = pt.run("fastboot", ["getvar", "unlocked"], timeout=15)
    except FileNotFoundError:
        return None
    val = pt.parse_getvar(out + "\n" + err, "unlocked").lower()
    if val == "yes":
        print(c("   [OK] Bootloader DESBLOQUEADO.", "green"))
        return True
    if val:
        print(c(f"   [i] Estado reportado: unlocked={val}", "yellow"))
        return False
    print("   No se pudo leer el estado (normal en algunos fabricantes).")
    return None


def list_support():
    """Imprime la matriz de compatibilidad desde la base de datos."""
    method_labels = {
        "fastboot": "Automatico (fastboot)",
        "fastboot_code": "Semi-auto (codigo web)",
        "deep_testing": "Semi-auto (app oficial)",
        "mi_unlock": "Guiado (Mi Unlock Tool)",
        "download_mode": "Guiado (Download Mode)",
        "manual_web": "Guiado (token/web)",
        "mtkclient": "No oficial (mtkclient)",
        "locked": "Sin metodo oficial",
    }
    unof_labels = {"mtkclient": "mtkclient", "testpoint": "testpoint"}
    vendors = db.load_vendors()
    banner()
    print(c("\nMATRIZ DE COMPATIBILIDAD\n", "bold"))
    print(f"  {'MARCA':<14}{'METODO':<26}{'CUENTA':<8}{'ESPERA':<8}{'NO OFICIAL'}")
    print(c("  " + "-" * 66, "blue"))
    for key, p in vendors.items():
        if key.startswith("_") and key != "_default":
            continue
        name = "otros" if key == "_default" else key
        method = method_labels.get(p.get("method"), p.get("method", "?"))
        acct = "si" if p.get("needs_account") else "no"
        wait = f"{p.get('waiting_days',0)}d" if p.get("waiting_days") else "-"
        unof = unof_labels.get(p.get("unofficial_method"), "-")
        print(f"  {name:<14}{method:<26}{acct:<8}{wait:<8}{unof}")
    print(c("\n  Leyenda de METODO:", "cyan"))
    print("   Automatico    = la app hace el desbloqueo por USB (solo confirmas en pantalla).")
    print("   Semi-auto     = la app prepara todo; falta un paso web/app del fabricante.")
    print("   Guiado        = la app te guia; el desbloqueo final es fuera de fastboot.")
    print("   Sin metodo    = el fabricante no permite desbloquear oficialmente.")
    print(c("   NO OFICIAL    = ruta de la comunidad (mtkclient/testpoint) para marcas sin", "cyan"))
    print(c("                   metodo oficial. Arriesgada: puede brickear. Solo bajo tu riesgo.", "cyan"))
    return 0


def flash_if_rom(info, yes):
    """Si hay una ROM en el USB para este movil, la flashea (device en fastboot).
    Devuelve None si no habia ROM, True/False segun el flasheo."""
    rom_dir = flasher.find_rom_dir(info.get("codename", ""), info.get("model", ""))
    if not rom_dir:
        flasher.maybe_flash(info, yes, ask, c)  # solo informa carpetas disponibles
        return None

    # Asegurar que el telefono esta en fastboot para poder flashear.
    if not db.detect_fastboot_devices():
        print(c("\n[i] Esperando a que el telefono vuelva a fastboot para flashear la ROM...", "cyan"))
        for _ in range(40):
            if db.detect_fastboot_devices():
                break
            time.sleep(2)
    if not db.detect_fastboot_devices():
        print(c("[!] El telefono no esta en fastboot ahora, no puedo flashear.", "yellow"))
        print(c("    Ponlo en fastboot (adb reboot bootloader) y reejecuta la herramienta.", "yellow"))
        return None

    return flasher.maybe_flash(info, yes, ask_confirm, c)


def _completion_summary(info, elapsed, flashed, unlocked=True):
    border = "green" if unlocked is True else "yellow"
    print(c("\n  " + "=" * 56, border))
    print(c("  RESUMEN", "bold"))
    dev = (f"{info.get('brand', '?')} {info.get('model', '') or ''}").strip()
    print(f"   Telefono ....... {dev}")
    if unlocked is True:
        print(f"   Bootloader ..... {c('DESBLOQUEADO', 'green')}")
    else:  # None: el comando fue OKAY pero el modelo no reporta el estado
        print(f"   Bootloader ..... {c('no confirmado (tu modelo no reporta el estado)', 'yellow')}")
    if flashed is True:
        print(f"   ROM ............ {c('flasheada', 'green')}")
    print(f"   Tiempo total ... {_fmt_mmss(elapsed)}")
    print(c("  " + "=" * 56, border))
    bell()


def process_device(yes):
    """Procesa el telefono conectado ahora mismo.
    Devuelve True (desbloqueado), False (fallo), None (flujo guiado externo) o
    la cadena 'no_device' si no se detecto ningun telefono."""
    start_t = time.monotonic()
    mode = wait_for_device()
    if mode is None:
        print(c("[X] No se detecto ningun telefono. Revisa el cable/depuracion USB.", "red"))
        return "no_device"

    if mode == "adb":
        info = db.describe_adb_device()
        show_device_info(info)
        profile = info["profile"]
        print(c(f"\n  Notas del fabricante:\n   {profile.get('notes','')}", "cyan"))

        if profile.get("method") == "locked":
            handle_locked(profile)
            return False

        if not guide_oem_toggle(info):
            print(c("[X] Sin el toggle OEM no se puede continuar de forma segura.", "red"))
            return False

        if profile.get("method") in ("mi_unlock", "download_mode", "manual_web"):
            # HTC/LG (manual_web con lectura de token) necesitan estar en
            # BOOTLOADER: 'fastboot oem get_identifier_token' / 'oem device-id'
            # no funcionan en modo ADB (se quedarian esperando dispositivo hasta
            # agotar el timeout). Reiniciamos a fastboot antes de leer el token.
            if profile.get("method") == "manual_web" and profile.get("get_data_command"):
                reboot_to_bootloader()
            run_unlock(profile, yes)
            if profile.get("method") == "download_mode":
                # Samsung: intentar flasheo por Heimdall si hay ROM en el USB.
                flasher.flash_samsung(info, ask_confirm, c)
            print(c("\n[i] Sigue las instrucciones de arriba para tu marca.", "cyan"))
            return None

        if not reboot_to_bootloader():
            return False
        result = run_unlock(profile, yes)
    else:  # fastboot
        info = db.describe_fastboot_device()
        show_device_info(info)
        if info["vendor_key"] == "_default":
            print(c("\n[i] En modo fastboot solo se lee el 'product' (nombre clave), no la", "cyan"))
            print(c("    marca. Si tu fabricante necesita un flujo especial (Motorola, Sony,", "cyan"))
            print(c("    Xiaomi...), enciende el telefono normal y reejecuta: se detecta por ADB.", "cyan"))
        # Si ya esta desbloqueado, saltamos el desbloqueo y vamos directos a flashear.
        if info.get("unlocked", "").lower() == "yes":
            print(c("\n[i] El bootloader ya esta DESBLOQUEADO.", "green"))
            result = True
        else:
            result = run_unlock(info["profile"], yes)

    if result is True:
        # La VERIFICACION manda sobre el codigo de salida: 'fastboot flashing
        # unlock' devuelve OKAY aunque elijas 'No' en la pantalla del telefono.
        verified = verify_unlocked()
        if verified is False:
            print(c("\n[i] El bootloader sigue BLOQUEADO (unlocked=no).", "yellow"))
            print(c("    Parece que elegiste 'No' en la pantalla del telefono (o tu", "yellow"))
            print(c("    modelo/operador no permite el desbloqueo). NO se ha borrado nada.", "yellow"))
            print(c("    Reinicio el telefono a su estado normal.", "cyan"))
            try:
                pt.run("fastboot", ["reboot"], timeout=30)
            except FileNotFoundError:
                pass
            return False
        # Intentar flashear ROM si hay una para este movil (solo si esta desbloqueado).
        flashed = flash_if_rom(info, yes)
        if flashed is None:
            if verified is True:
                print(c("\n[OK] Desbloqueo completado. El telefono hara un factory reset", "green"))
                print(c("     y se reiniciara. Puede tardar varios minutos la primera vez.", "green"))
            else:  # None: no se pudo leer el estado
                print(c("\n[i] Comando enviado. No pude LEER el estado en este modelo.", "cyan"))
                print(c("    Si en el telefono elegiste 'Unlock', ya esta hecho (factory reset).", "cyan"))
            try:
                pt.run("fastboot", ["reboot"], timeout=30)
            except FileNotFoundError:
                pass
        _completion_summary(info, time.monotonic() - start_t, flashed, unlocked=verified)
    elif result is False:
        print(c("\n[X] El desbloqueo no se completo. Revisa los mensajes de arriba.", "red"))
    return result


# ---------- Main ----------
def main():
    global AUTO
    _enable_ansi_windows()
    parser = argparse.ArgumentParser(description="Plug-and-Play OEM Unlock")
    parser.add_argument("--auto-tools", action="store_true",
                        help="Descarga adb/fastboot automaticamente si faltan")
    parser.add_argument("--yes", action="store_true",
                        help="No pedir la confirmacion final de borrado (usar con cuidado)")
    parser.add_argument("--auto", action="store_true",
                        help="Modo automatico: sin preguntas de software; hace todo lo posible solo")
    parser.add_argument("--watch", action="store_true",
                        help="Vigila el USB: procesa cada telefono que conectes, uno tras otro")
    parser.add_argument("--list", action="store_true",
                        help="Muestra la matriz de compatibilidad y sale")
    parser.add_argument("--setup", action="store_true",
                        help="Instala TODAS las dependencias (adb/fastboot, lz4, heimdall) y sale")
    args = parser.parse_args()

    if args.list:
        return list_support()

    if args.setup:
        return deps.setup_all()

    AUTO = args.auto or args.watch
    yes = args.yes or AUTO

    banner()
    print(c("\nAVISO: desbloquear el bootloader BORRA TODOS los datos del telefono", "yellow"))
    print(c("y anula parte de la garantia. Hazlo solo en telefonos tuyos.\n", "yellow"))
    if AUTO:
        print(c("[MODO AUTOMATICO] Hare todo lo posible sin preguntar. Los pasos", "cyan"))
        print(c("fisicos del telefono (toggle OEM y confirmacion) siguen siendo tuyos.\n", "cyan"))

    if not pt.ensure_tools(auto=args.auto_tools or AUTO):
        print(c("[X] No hay adb/fastboot disponibles. Abortando.", "red"))
        return 1

    # Dependencia opcional: soporte lz4 (solo se instala si falta; silencioso si ya esta).
    deps.ensure_lz4(auto=True, verbose=False)

    if not args.watch:
        result = process_device(yes)
        return 0 if result is not False else 1

    # ---- Modo watch: bucle infinito, un telefono tras otro ----
    print(c("[WATCH] Conecta un telefono. Cuando termine, desconectalo y conecta", "cyan"))
    print(c("        el siguiente. Ctrl+C para salir.\n", "cyan"))
    count = 0
    while True:
        result = process_device(yes)
        # Contamos cualquier telefono realmente detectado (exito, fallo o flujo
        # guiado). Solo 'no_device' (nada conectado) no cuenta.
        if result != "no_device":
            count += 1
            print(c(f"\n[WATCH] Telefonos procesados: {count}. Desconecta este y", "cyan"))
            print(c("        conecta el siguiente (Ctrl+C para salir)...", "cyan"))
            # Espera a que el actual se desconecte de forma ESTABLE (varias
            # lecturas vacias seguidas). Asi no lo reprocesamos durante el breve
            # hueco en que un reboot/flasheo lo deja invisible unos segundos.
            empty = 0
            while empty < 3:
                if db.detect_adb_devices() or db.detect_fastboot_devices():
                    empty = 0
                else:
                    empty += 1
                time.sleep(2)
        time.sleep(1)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(c("\n\nInterrumpido por el usuario.", "yellow"))
        sys.exit(130)
