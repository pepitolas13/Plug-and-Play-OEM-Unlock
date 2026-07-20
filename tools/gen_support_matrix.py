#!/usr/bin/env python3
"""Genera docs/SUPPORT.md a partir de data/devices.json (fuente unica de verdad)."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "devices.json")
OUT = os.path.join(ROOT, "docs", "SUPPORT.md")

METHOD = {
    "fastboot": ("Automatico", "La app desbloquea por USB; solo confirmas con los botones del telefono."),
    "fastboot_code": ("Semi-automatico", "La app lee el ID; consigues un codigo en la web del fabricante y la app lo aplica."),
    "deep_testing": ("Semi-automatico", "Necesita la app oficial (In-Depth/Deep Test) del fabricante; luego la app hace fastboot."),
    "mi_unlock": ("Guiado", "La app te prepara; el desbloqueo final lo hace la Mi Unlock Tool oficial (espera obligatoria)."),
    "download_mode": ("Guiado", "No usa fastboot; la app te guia por el Download Mode del telefono."),
    "manual_web": ("Guiado", "Requiere descargar un archivo de desbloqueo de la web del fabricante y flashearlo."),
    "mtkclient": ("No oficial", "Sin metodo oficial: ruta de la comunidad via mtkclient (BROM/testpoint). Arriesgado."),
    "locked": ("No soportado", "El fabricante NO ofrece desbloqueo oficial."),
}

UNOFFICIAL_LABEL = {
    "mtkclient": "mtkclient (BROM)",
    "testpoint": "testpoint",
    "community": "comunidad",
}

BRAND_NAMES = {
    "google": "Google / Pixel / Nexus", "oneplus": "OnePlus", "nothing": "Nothing Phone",
    "fairphone": "Fairphone", "asus": "ASUS ROG / Zenfone", "lenovo": "Lenovo / Legion",
    "nubia": "Nubia / RedMagic", "zte": "ZTE (Axon/Blade)", "infinix": "Infinix",
    "tecno": "Tecno", "itel": "itel", "rugged_mtk": "Blackview/Oukitel/Doogee/Ulefone/Cubot/UMIDIGI/CAT/Crosscall",
    "oscal": "OSCAL (Pilot 1, Spider...)",
    "bq": "BQ Aquaris", "essential": "Essential Phone", "razer": "Razer Phone",
    "sharp": "Sharp AQUOS", "teracube": "Teracube", "micromax": "Micromax",
    "lava": "Lava", "vsmart": "Vsmart / VinSmart",
    "motorola": "Motorola / Moto", "sony": "Sony Xperia", "htc": "HTC",
    "lg": "LG", "xiaomi": "Xiaomi / Redmi / POCO / Black Shark", "samsung": "Samsung Galaxy",
    "oppo": "Oppo", "realme": "realme", "meizu": "Meizu", "huawei": "Huawei",
    "honor": "Honor", "vivo": "Vivo", "iqoo": "iQOO", "nokia": "Nokia / HMD",
    "tcl": "TCL / Alcatel", "wiko": "Wiko", "_default": "Cualquier otra marca",
}


def main():
    vendors = json.load(open(DB, encoding="utf-8"))["vendors"]
    lines = []
    lines.append("# ✅ Lista de compatibilidad\n")
    lines.append("Generado automaticamente desde `data/devices.json`. "
                 "Ejecuta `python tools/gen_support_matrix.py` para regenerarlo.\n")
    lines.append("> **Recuerda los limites de Android que ningun software puede saltar:**\n"
                 "> 1) el toggle *Desbloqueo de OEM* se activa a mano en el telefono; "
                 "2) la confirmacion final es fisica (botones); "
                 "3) algunas marcas no permiten desbloqueo.\n")

    order = ["Automatico", "Semi-automatico", "Guiado", "No oficial", "No soportado"]
    groups = {k: [] for k in order}
    for key, p in vendors.items():
        if key.startswith("_") and key != "_default":
            continue
        cat, _ = METHOD.get(p.get("method"), ("?", ""))
        groups.setdefault(cat, []).append((key, p))

    headers = {
        "Automatico": "## 🟢 Desbloqueo automatico por USB (fastboot)\nEnchufas, activas el toggle y la app hace el resto. Solo confirmas en pantalla.",
        "Semi-automatico": "## 🟡 Semi-automatico (falta un paso web/app del fabricante)\nLa app hace casi todo; necesitas un codigo o una app oficial del fabricante.",
        "Guiado": "## 🔵 Guiado (el desbloqueo final es fuera de fastboot)\nLa app detecta y te guia paso a paso por el metodo propio de la marca.",
        "No oficial": "## 🟣 Solo por ruta NO oficial\nEl fabricante no da metodo oficial, pero existe una via de la comunidad (bajo tu propio riesgo).",
        "No soportado": "## 🔴 Sin metodo oficial de desbloqueo\nEstas marcas no permiten desbloquear el bootloader oficialmente. Cuando existe, se indica la ruta NO oficial de la comunidad (arriesgada).",
    }

    for cat in order:
        if not groups.get(cat):
            continue
        lines.append(headers[cat] + "\n")
        show_unofficial = cat in ("No oficial", "No soportado")
        if show_unofficial:
            lines.append("| Marca | Cuenta req. | Espera | Ruta no oficial | Notas |")
            lines.append("|-------|:-----------:|:------:|:---------------:|-------|")
        else:
            lines.append("| Marca | Cuenta req. | Espera | Notas |")
            lines.append("|-------|:-----------:|:------:|-------|")
        for key, p in groups[cat]:
            name = BRAND_NAMES.get(key, key)
            acct = "Si" if p.get("needs_account") else "No"
            wait = f"{p['waiting_days']} dias" if p.get("waiting_days") else "-"
            note = p.get("notes", "").replace("\n", " ")
            if show_unofficial:
                unof = UNOFFICIAL_LABEL.get(p.get("unofficial_method"), "-")
                lines.append(f"| **{name}** | {acct} | {wait} | {unof} | {note} |")
            else:
                lines.append(f"| **{name}** | {acct} | {wait} | {note} |")
        lines.append("")

    total = len([k for k in vendors if not k.startswith("_") or k == "_default"])
    workable = len([k for k, p in vendors.items()
                    if (not k.startswith("_") or k == "_default") and p.get("method") != "locked"])
    unofficial = len([k for k, p in vendors.items()
                      if (not k.startswith("_") or k == "_default")
                      and p.get("method") == "locked" and p.get("unofficial_method")])
    lines.append("---\n")
    lines.append(f"**Resumen:** {total} perfiles de marca; {workable} con metodo de desbloqueo "
                 f"disponible, {total - workable} sin metodo oficial "
                 f"(de los cuales {unofficial} tienen una ruta NO oficial de la comunidad).\n")
    lines.append("Cada perfil cubre TODOS los modelos de esa marca que compartan metodo "
                 "(cientos de telefonos). Las marcas no listadas usan el flujo `fastboot` "
                 "estandar por defecto.\n")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Escrito {OUT} ({total} marcas, {workable} desbloqueables)")


if __name__ == "__main__":
    main()
