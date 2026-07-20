# 📦 Carpeta de ROMs

Pon aquí las ROMs que quieras flashear automáticamente. La herramienta detecta
el **codename** del teléfono conectado y busca una subcarpeta con ese nombre.

## Cómo organizarlo

```
roms/
├── oriole/          <- Pixel 6        (codename)
│   ├── boot.img
│   ├── vbmeta.img
│   └── system.img
├── lisa/            <- Xiaomi 11 Lite
│   └── recipe.json
└── beyond1lte/      <- Galaxy S10
    └── ...
```

El nombre de la carpeta debe coincidir con el **codename** del móvil (lo que
reporta `ro.product.device`). La herramienta te lo muestra al conectar el
teléfono ("Nombre clave"). También acepta el nombre de modelo.

> ¿No sabes el codename? Conéctalo y ejecuta la herramienta: te lo dirá. O
> míralo en la wiki de LineageOS / XDA de tu modelo.

## Tres formas de definir el flasheo (por prioridad)

### 1. `recipe.json` (recomendado — control total)
El más fiable. Defines los pasos exactos. Ejemplo en
[`_example-oriole/recipe.json`](_example-oriole/recipe.json):

```json
{
  "description": "LineageOS 21 - Pixel 6 (oriole)",
  "steps": [
    "flash boot boot.img",
    "flash dtbo dtbo.img",
    "flash vbmeta vbmeta.img --disable-verity --disable-verification",
    "reboot fastboot",
    "flash system system.img",
    "reboot bootloader"
  ]
}
```
Cada `step` son argumentos de `fastboot`. Los ficheros se resuelven dentro de la
propia carpeta. Solo se permiten verbos seguros: `flash`, `reboot`, `update`,
`erase`, `set_active`, `-w`.

### 2. Imágenes de fábrica oficiales (`flash-all.sh` / `flash-all.bat`)
Si descomprimes una *factory image* de Google (Pixel) dentro de la carpeta, la
herramienta detecta y ejecuta su `flash-all` oficial tal cual.

### 3. Auto-detección de imágenes sueltas
Si solo pones `boot.img`, `system.img`, `vbmeta.img`, etc., la herramienta
infiere el orden de flasheo seguro automáticamente. También acepta un único
`.zip` flasheable por `fastboot update`.

## Seguridad

- La herramienta **siempre te enseña el plan** y pide **una confirmación** antes
  de flashear (incluso en modo `--auto`), porque una ROM incorrecta puede
  inutilizar el teléfono.
- Verifica **siempre** que la ROM es para tu modelo exacto.
- Las ROMs (archivos grandes) están excluidas de git por `.gitignore`; solo se
  versiona esta guía y el ejemplo.

## Samsung (Heimdall)

Samsung no usa fastboot, sino **Heimdall** (reemplazo open-source de Odin). El
auto-flasheo Samsung está soportado si tienes `heimdall` instalado:

- **Linux:** `apt install heimdall-flash` (o compila Benjamin-Dobell/Heimdall)
- **macOS:** `brew install heimdall`
- **Windows:** descarga la *Heimdall Suite* de github.com/Benjamin-Dobell/Heimdall

El teléfono debe estar en **Download Mode** (la herramienta lo reinicia ahí sola
en modo `--auto`, o lo haces con Vol+ y Vol− al conectar el cable).

Tres formas de poner la ROM Samsung en `roms/<codename>/`:

1. **`recipe.json` con `"tool": "heimdall"`** (recomendado). Los pasos son
   argumentos de `heimdall flash`. Ejemplo en
   [`_example-beyond1lte/recipe.json`](_example-beyond1lte/recipe.json):
   ```json
   {
     "tool": "heimdall",
     "description": "TWRP para Galaxy S10",
     "steps": ["flash --RECOVERY recovery.img --no-reboot"]
   }
   ```
2. **Imágenes sueltas** (`boot.img`, `recovery.img`, `system.img`…): se mapean
   automáticamente a las particiones PIT comunes (BOOT, RECOVERY, SYSTEM…).
3. **Firmware Samsung `.tar` / `.tar.md5`** (AP/BL/CP/CSC): se extrae solo y se
   flashean los `.img` que contenga. Si trae `.img.lz4` (comprimidos, lo normal
   en el firmware oficial de Samsung), **se descomprimen automáticamente** a
   `.img` crudo antes de flashear — no tienes que hacer nada.

   > Para la descompresión automática la herramienta usa, por este orden: el
   > módulo Python `lz4` (`pip install lz4`), o el comando `lz4`/`unlz4` del
   > sistema. Si no encuentra ninguno, te lo dice y te indica cómo instalarlo.

> ⚠️ Los nombres de partición varían por modelo. Verifica el tuyo con
> `heimdall print-pit` y, si hace falta, usa un `recipe.json` con los nombres
> exactos.
