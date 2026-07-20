"""
Carga los perfiles de fabricante y detecta el telefono conectado.
"""

import json
import os
import re

import platform_tools as pt

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "devices.json"
)


def load_vendors():
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["vendors"]


def _alias_matches(alias, haystack):
    """Alias solo alfanumericos -> match por palabra completa (evita que 'itel'
    empareje dentro de 'oukitel'). Alias con espacio/+/- (p. ej. 'mi ', 'op ',
    '1+') -> se exige un limite de palabra al inicio para no casar dentro de
    otra palabra ('mi ' no debe emparejar dentro de 'nomi ')."""
    alias = alias.lower()
    if alias.strip() == "":
        return False
    if alias.isalnum():
        return re.search(r"\b" + re.escape(alias) + r"\b", haystack) is not None
    return re.search(r"\b" + re.escape(alias), haystack) is not None


def match_vendor(brand, manufacturer):
    """Empareja marca/fabricante reportado por el dispositivo con un perfil."""
    vendors = load_vendors()
    haystack = f"{brand} {manufacturer}".lower()
    for key, profile in vendors.items():
        if key.startswith("_"):
            continue
        for alias in profile.get("aliases", []):
            if _alias_matches(alias, haystack):
                return key, profile
    return "_default", vendors["_default"]


def _getprop(prop):
    rc, out, _ = pt.run("adb", ["shell", "getprop", prop], timeout=15)
    return out.strip() if rc == 0 else ""


def detect_adb_devices():
    """Lista dispositivos en modo ADB (telefono encendido con depuracion USB)."""
    devices = []
    try:
        rc, out, _ = pt.run("adb", ["devices"], timeout=15)
    except FileNotFoundError:
        return devices
    if rc != 0:
        return devices
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or "\t" not in line:
            continue
        serial, state = line.split("\t", 1)
        devices.append({"serial": serial, "state": state.strip()})
    return devices


def detect_fastboot_devices():
    """Lista dispositivos en modo fastboot/bootloader."""
    devices = []
    try:
        rc, out, _ = pt.run("fastboot", ["devices"], timeout=15)
    except FileNotFoundError:
        return devices
    if rc != 0:
        return devices
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if parts:
            devices.append({"serial": parts[0], "state": "fastboot"})
    return devices


def describe_adb_device():
    """Devuelve un dict con la info del telefono conectado por ADB."""
    brand = _getprop("ro.product.brand")
    manufacturer = _getprop("ro.product.manufacturer")
    model = _getprop("ro.product.model")
    codename = _getprop("ro.product.device")
    android = _getprop("ro.build.version.release")
    key, profile = match_vendor(brand, manufacturer)
    return {
        "connection": "adb",
        "brand": brand,
        "manufacturer": manufacturer,
        "model": model,
        "codename": codename,
        "android": android,
        "vendor_key": key,
        "profile": profile,
    }


def describe_fastboot_device():
    """Info disponible en modo fastboot (mas limitada)."""
    def fbvar(var):
        rc, out, err = pt.run("fastboot", ["getvar", var], timeout=15)
        # fastboot escribe getvar en stderr y puede prefijar '(bootloader) '.
        return pt.parse_getvar(out + "\n" + err, var)

    product = fbvar("product")
    unlocked = fbvar("unlocked")
    key, profile = match_vendor(product, product)
    return {
        "connection": "fastboot",
        "brand": product,
        "manufacturer": product,
        "model": product,
        "codename": product,
        "android": "",
        "unlocked": unlocked,
        "vendor_key": key,
        "profile": profile,
    }
