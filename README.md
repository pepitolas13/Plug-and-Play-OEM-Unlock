# 🔌 Plug-and-Play OEM Unlock

Herramienta **portátil desde USB** que detecta cualquier teléfono Android que
conectes y te guía para **desbloquear el bootloader (OEM Unlock)** con los
comandos correctos según el fabricante, automatizando todo lo que Android
permite automatizar.

Funciona con **todos tus teléfonos** (Google/Pixel, Xiaomi/Redmi/POCO, Samsung,
Motorola, Sony, OnePlus, ASUS, Nothing, Oppo/Realme…) gracias a una base de
datos de perfiles por marca.

---

## ⚠️ Lee esto primero (la verdad técnica)

**No existe ningún software que active silenciosamente el OEM Unlock con solo
enchufar un USB.** Y es a propósito: es la protección antirrobo de Android.
Concretamente:

1. **El interruptor "Desbloqueo de OEM"** (en Opciones de desarrollador) **solo
   se puede activar tocando la pantalla del teléfono ya desbloqueado.** Ningún
   comando por USB puede activarlo — si pudiera, cualquiera desbloquearía un
   móvil robado.
2. **Desbloquear el bootloader BORRA TODOS LOS DATOS** del teléfono.
3. Requiere **confirmación física** con los botones de volumen/encendido en la
   pantalla del propio teléfono.

Esta herramienta hace **todo lo demás** por ti: detecta el modelo, te dice los
pasos exactos de tu marca, reinicia a bootloader, lanza el comando de desbloqueo
correcto y verifica el resultado.

> Úsala **solo en teléfonos que sean tuyos.** Desbloquear el bootloader anula
> parte de la garantía y borra el dispositivo.

---

## 🚀 Uso rápido

1. Copia esta carpeta entera a un **USB**.
2. Conéctalo al PC y conecta el teléfono con un cable USB de datos.
3. En el teléfono, activa **Depuración USB** (Opciones de desarrollador).
4. Lanza:
   - **Windows:** doble clic en `unlock.bat`
     - ¿El `.bat` da problemas (p. ej. el *señuelo* "Python was not found" de la
       Store)? Usa el lanzador **PowerShell**: clic derecho en `unlock.ps1` →
       *Ejecutar con PowerShell*, o `powershell -ExecutionPolicy Bypass -File unlock.ps1`.
   - **Linux / macOS:** `./unlock.sh`

   Ambos lanzadores **instalan Python 3 solos** si falta (winget → instalador
   oficial → choco en Windows; apt/dnf/pacman/brew en Linux/macOS).

La herramienta descargará automáticamente `adb`/`fastboot` (oficiales de Google)
dentro del propio USB la primera vez, así el USB queda **autocontenido**.

### Requisitos
- Un cable USB de **datos** (no solo de carga).
- **Todo lo demás se instala solo.** Los lanzadores instalan Python 3 si falta
  (vía winget/choco en Windows; apt/dnf/pacman/brew en Linux/macOS), y el
  programa descarga `adb`/`fastboot` y prepara `lz4`/`heimdall` automáticamente.

### Instalar todas las dependencias de golpe (opcional)
Para dejar el USB listo antes de usarlo:
```
unlock.bat --setup      # Windows
./unlock.sh --setup     # Linux/macOS
```
Instala `adb`/`fastboot` (en el USB), el módulo `lz4` y `heimdall` (Samsung).
Es "mejor esfuerzo": si algo requiere permisos de admin o un gestor de paquetes
que no tienes, te lo dice con instrucciones claras.

---

## 🤖 Modos de funcionamiento

| Modo | Comando | Qué hace |
|------|---------|----------|
| **Guiado** (por defecto) | `unlock.bat` | Te pregunta y confirma cada paso. |
| **Automático** | `unlock.bat --auto` | Sin preguntas de software: detecta, espera a que actives el toggle, reinicia, desbloquea y verifica **solo**. |
| **Watch (multi-móvil)** | `unlock.bat --watch` | Queda vigilando el USB: conectas un móvil, lo procesa, lo desconectas y conectas el siguiente. Ideal para **varios teléfonos seguidos**. |
| **Lista** | `unlock.bat --list` | Muestra la matriz de compatibilidad. |
| **Setup** | `unlock.bat --setup` | Instala todas las dependencias y sale. |

> **¿Por qué no se ejecuta 100% solo al enchufar el USB?**
> Windows **desactivó el autorun de USB en 2011** por seguridad (el mismo motivo
> por el que un USB no puede infectar tu PC solo). Por eso lanzas el programa una
> vez (doble clic) y a partir de ahí, con `--watch`, ya procesa todos los
> teléfonos que enchufes sin tocar nada más en el PC.
>
> Y hay **dos pasos que NINGÚN software puede hacer por ti** (protección de
> Android, no una limitación de esta app): activar el *toggle OEM* en la pantalla
> del móvil y confirmar el borrado con los botones físicos. Todo lo demás está
> automatizado.

---

## 📦 Auto-flasheo de ROMs

Pon una ROM en `roms/<codename>/` del USB y la herramienta la flashea sola tras
desbloquear (o si el móvil ya está desbloqueado). **Solo das una confirmación.**

- Detecta el *codename* del móvil y busca su carpeta automáticamente.
- Soporta tres formatos: `recipe.json` (control total), imágenes de fábrica
  oficiales (`flash-all`), o imágenes sueltas (`boot.img`, `system.img`…) que
  ordena solo.
- Muestra el plan y pide **una** confirmación antes de flashear (siempre, por
  seguridad — una ROM incorrecta puede inutilizar el móvil).
- Salida del progreso **en vivo**.
- **Samsung** vía **Heimdall** (reemplazo open-source de Odin): flashea `.img`
  sueltas, firmware `.tar`/`.tar.md5` (se extrae solo) o un `recipe.json` con
  `"tool": "heimdall"`. Requiere tener `heimdall` instalado.

Guía completa y ejemplos en **[`roms/README.md`](roms/README.md)**.

---

## 🧩 ¿Qué automatiza y qué no?

| Paso | ¿Automático? |
|------|:---:|
| Detectar marca / modelo / Android | ✅ Sí |
| Elegir el flujo correcto por fabricante | ✅ Sí |
| Descargar adb/fastboot al USB | ✅ Sí |
| Instalar Python / drivers USB (Windows) | ✅ Sí (1 clic de permiso, UAC) |
| Activar el toggle "Desbloqueo de OEM" | ❌ Manual (límite de Android) |
| Reiniciar a bootloader | ✅ Sí |
| Lanzar el comando de desbloqueo correcto | ✅ Sí |
| Confirmar el borrado en pantalla | ❌ Manual (botones del teléfono) |
| Verificar estado final | ✅ Sí |

---

## 📱 Fabricantes soportados

**38 perfiles de marca** cubriendo cientos de modelos. Lista completa y detallada
en **[`docs/SUPPORT.md`](docs/SUPPORT.md)**. Resumen:

- 🟢 **Automático (fastboot):** Google/Pixel, OnePlus, Nothing, Fairphone, ASUS
  ROG/Zenfone, Lenovo/Legion, Nubia/RedMagic, ZTE, Infinix, Tecno, itel, BQ
  Aquaris, Essential, Razer, Sharp/AQUOS, Teracube, Micromax, Lava, Vsmart,
  rugerizados MTK (Blackview/Oukitel/Doogee/Ulefone/Cubot/UMIDIGI/CAT/Crosscall,
  **OSCAL** Pilot 1/Spider), y cualquier otra marca por defecto.
- 🟡 **Semi-automático:** Motorola (código), Sony (código IMEI), Oppo y realme
  (app oficial).
- 🔵 **Guiado:** Xiaomi/Redmi/POCO (Mi Unlock Tool), Samsung (Download Mode),
  HTC y LG (token web), Meizu.
- 🟣 **Ruta NO oficial (comunidad):** para las marcas sin método oficial pero con
  vía de la comunidad —**mtkclient** (BROM/testpoint) en modelos MediaTek de Vivo,
  iQOO, Nokia/HMD, TCL/Alcatel y Wiko; **testpoint** (Kirin) en Huawei/Honor. La
  app la muestra como **arriesgada** (puede brickear) y **nunca la ejecuta sin tu
  confirmación**.
- 🔴 **Sin método (ni oficial ni no oficial fiable):** modelos Qualcomm de esas
  mismas marcas. La app te lo dice claramente en vez de hacerte perder el tiempo.

La base de datos está en [`data/devices.json`](data/devices.json). Para añadir
marcas edítala y regenera la lista con `python tools/gen_support_matrix.py`.

---

## 📂 Estructura

```
Plug-and-Play-OEM-Unlock/
├── unlock.bat            # Lanzador Windows (cmd)
├── unlock.ps1            # Lanzador Windows (PowerShell, alternativo)
├── unlock.sh            # Lanzador Linux/macOS
├── src/
│   ├── oem_unlock.py    # Motor principal + flujo guiado
│   ├── device_db.py     # Detección y perfiles
│   ├── platform_tools.py# Localiza/descarga adb+fastboot
│   ├── flasher.py       # Auto-flasheo (fastboot + Samsung/Heimdall + lz4)
│   └── deps.py          # Instalación automática de dependencias
├── data/
│   └── devices.json     # Base de datos de fabricantes (fuente de verdad)
├── tools/
│   └── gen_support_matrix.py  # Regenera docs/SUPPORT.md
├── tests/
│   └── test_core.py    # Tests de la lógica (sin teléfono): python3 -m unittest
└── docs/
    ├── GUIA.md          # Guía detallada y solución de problemas
    └── SUPPORT.md       # Lista completa de compatibilidad
```

---

## 📖 Más información

Consulta [`docs/GUIA.md`](docs/GUIA.md) para la guía paso a paso, resolución de
problemas y cómo volver a bloquear el bootloader.

## Licencia
MIT © PepoTech
