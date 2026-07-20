"""
Instalacion y FORZADO automatico del driver USB en Windows (mejor esfuerzo).

Por que hace falta: un telefono MediaTek en modo fastboot aparece en el
Administrador de dispositivos como "Android" con triangulo amarillo (Otros
dispositivos, clase desconocida, ConfigManagerErrorCode 28), y 'fastboot' no lo
ve. El Google USB Driver (android_winusb.inf, FIRMADO) puede estar en el almacen,
pero Windows NO lo enlaza porque el hardware-ID del telefono (VID_0E8D...) no esta
listado en ese INF. El arreglo manual es: Actualizar controlador -> Examinar ->
Elegir de una lista -> "Android ADB Interface" -> aceptar el aviso de compatibilidad.

Este modulo AUTOMATIZA justo eso: detecta el dispositivo con problema, y fuerza
sobre el (por su InstanceId) el driver "Android ADB Interface" del android_winusb.inf
FIRMADO y SIN MODIFICAR (via SetupAPI DiInstallDevice, enumerando por CLASE, no por
hardware-ID). Como el INF/CAT no se tocan, la firma sigue valida (no hace falta
test-signing). Todo en UNA sola ventana de administrador (UAC).

LIMITE HONESTO: la ventana UAC no la puede evitar ningun programa. En sistemas que
no son Windows este modulo es un no-op que devuelve False.
"""

import json
import os
import platform
import re
import subprocess
import urllib.request
import zipfile

# Fuentes oficiales y firmadas.
GOOGLE_USB_DRIVER_URL = "https://dl.google.com/android/repository/usb_driver_r13-windows.zip"
USBDK_MSI_URL = "https://github.com/daynix/UsbDk/releases/download/v1.00-22/UsbDk_1.0.22_x64.msi"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIVERS_DIR = os.path.join(PROJECT_ROOT, "drivers")


def is_windows():
    return platform.system() == "Windows"


# ------------------------------------------------------------------
#  Deteccion del dispositivo (el "Android" con triangulo amarillo)
# ------------------------------------------------------------------
def _run_ps_capture(ps, timeout=60):
    """Ejecuta PowerShell y devuelve su stdout (str), '' si falla. NO eleva."""
    if not is_windows():
        return ""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


_VIDPID_RE = re.compile(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})")


def _vid_pid(instance_id):
    m = _VIDPID_RE.search(instance_id or "")
    if not m:
        return None, None
    return m.group(1).upper(), m.group(2).upper()


def find_problem_usb_devices():
    """Lista dispositivos USB presentes con problema de driver (el triangulo
    amarillo: Status != OK o ConfigManagerErrorCode != 0). Devuelve una lista de
    dicts con instance_id, name, class, error_code, vid, pid."""
    if not is_windows():
        return []
    ps = (
        "Get-PnpDevice -PresentOnly | "
        "Where-Object { $_.InstanceId -like 'USB\\*' -and "
        "($_.Status -ne 'OK' -or $_.ConfigManagerErrorCode -ne 0) } | "
        "Select-Object InstanceId, FriendlyName, Class, ConfigManagerErrorCode | "
        "ConvertTo-Json -Compress"
    )
    out = _run_ps_capture(ps).strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    devices = []
    for d in data:
        iid = d.get("InstanceId", "") or ""
        vid, pid = _vid_pid(iid)
        devices.append({
            "instance_id": iid,
            "name": d.get("FriendlyName") or "",
            "class": d.get("Class") or "",
            "error_code": d.get("ConfigManagerErrorCode"),
            "vid": vid,
            "pid": pid,
        })
    return devices


def pick_fastboot_candidate(devices):
    """De los dispositivos con problema de driver, elige el Android/MediaTek que
    hay que arreglar. Robusto ante VID/PID variables: puntua por error 28
    (CM_PROB_FAILED_INSTALL), VID MediaTek (0E8D), nombre y clase desconocida.
    Funcion pura (testeable sin Windows)."""
    def score(d):
        s = 0
        if d.get("error_code") == 28:
            s += 4
        if (d.get("vid") or "") == "0E8D":
            s += 3
        name = (d.get("name") or "").lower()
        if any(k in name for k in ("android", "adb", "bootloader", "fastboot")):
            s += 2
        if (d.get("class") or "").lower() in ("", "unknown"):
            s += 1
        return s
    ranked = sorted((d for d in devices if d.get("instance_id")),
                    key=score, reverse=True)
    if ranked and score(ranked[0]) > 0:
        return ranked[0]
    return None


# ------------------------------------------------------------------
#  Descargas / utilidades
# ------------------------------------------------------------------
def _download(url, dest):
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        urllib.request.urlretrieve(url, dest)
        return os.path.isfile(dest)
    except Exception as e:
        print(f"   [!] No se pudo descargar {url}: {e}")
        return False


def _find_inf(root):
    for base, _dirs, files in os.walk(root):
        for f in files:
            if f.lower() == "android_winusb.inf":
                return os.path.join(base, f)
    return None


def _ensure_google_usb_driver_extracted():
    """Descarga (si falta) y extrae el Google USB Driver oficial FIRMADO en
    drivers/google_usb/. Devuelve la ruta a android_winusb.inf o None. NO eleva."""
    if not is_windows():
        return None
    drv_dir = os.path.join(DRIVERS_DIR, "google_usb")
    inf = _find_inf(drv_dir)
    if inf:
        return inf
    zip_path = os.path.join(DRIVERS_DIR, "usb_driver.zip")
    print("   [*] Descargando el Google USB Driver (oficial, firmado)...")
    if not _download(GOOGLE_USB_DRIVER_URL, zip_path):
        return None
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(drv_dir)
    except Exception as e:
        print(f"   [!] No se pudo extraer el driver: {e}")
        return None
    finally:
        try:
            os.remove(zip_path)
        except OSError:
            pass
    inf = _find_inf(drv_dir)
    if not inf:
        print("   [!] No encontre android_winusb.inf en el paquete descargado.")
    return inf


# ------------------------------------------------------------------
#  Ejecucion elevada (una sola UAC)
# ------------------------------------------------------------------
def _run_elevated_ps(ps_body, timeout=900):
    """Ejecuta un bloque de PowerShell COMO ADMINISTRADOR (una sola ventana UAC).
    Devuelve True si el proceso elevado termino con codigo 0. El .ps1 se guarda en
    drivers/_elevated.ps1 (no se borra) para poder inspeccionarlo si falla."""
    if not is_windows():
        return False
    try:
        os.makedirs(DRIVERS_DIR, exist_ok=True)
        ps1 = os.path.join(DRIVERS_DIR, "_elevated.ps1")
        with open(ps1, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write(ps_body)
        # ArgumentList como UNA cadena para controlar el quoting: la ruta del .ps1
        # va entre comillas dobles (tolera espacios tipo C:\Users\Juan Perez\...).
        # El array de Start-Process NO auto-comilla y rompia con esas rutas (causa
        # tipica de "error al abrirse la powershell").
        inner = '-NoProfile -ExecutionPolicy Bypass -File "' + ps1 + '"'
        inner_ps = "'" + inner.replace("'", "''") + "'"
        launcher = (
            "try { $p = Start-Process powershell -ArgumentList " + inner_ps +
            " -Verb RunAs -Wait -PassThru; exit $p.ExitCode } catch { exit 1 }"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", launcher],
            timeout=timeout)
        return r.returncode == 0
    except Exception as e:
        print(f"   [!] No se pudo ejecutar con permisos de administrador: {e}")
        return False


# El "force-bind": replica exactamente "Actualizar controlador -> Elegir de una
# lista -> Android ADB Interface". Enumera los drivers por CLASE (SPDIT_CLASSDRIVER
# con DI_ENUMSINGLEINF sobre el propio INF, NO por hardware-ID), selecciona el nodo
# "ADB Interface" e instala con DiInstallDevice sobre el InstanceId. Usa el
# android_winusb.inf de Google SIN MODIFICAR -> catalogo firmado valido, sin
# test-signing. Registra todo en un log y, si falla, deja la ventana abierta.
_FORCE_BIND_PS = r'''
$ErrorActionPreference = "Stop"
# Reejecutar en PowerShell de 64 bits (DiInstallDevice da ERROR_IN_WOW64 en 32-bit
# sobre Windows x64). Hereda la elevacion del proceso padre.
if (-not [Environment]::Is64BitProcess) {
    $ps64 = "$env:WINDIR\sysnative\WindowsPowerShell\v1.0\powershell.exe"
    if (Test-Path $ps64) {
        & $ps64 -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath
        exit $LASTEXITCODE
    }
}

$Log = @'
{log}
'@
$Inf = @'
{inf}
'@
$InstanceId = @'
{instance_id}
'@

try { Start-Transcript -Path $Log -Append -Force | Out-Null } catch {}
$exit = 2
try {
    Write-Host "== Force-bind del driver Android =="
    Write-Host ("InstanceId : " + $InstanceId)
    Write-Host ("INF        : " + $Inf)

    # Stage del INF firmado en el almacen (idempotente).
    try { pnputil /add-driver "$Inf" /install | Out-Null }
    catch { Write-Host ("add-driver aviso: " + $_.Exception.Message) }

Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class FB {
  const int LINE_LEN = 256; const int MAX_PATH = 260;
  public const uint SPDIT_CLASSDRIVER = 0x1;
  public const uint DI_ENUMSINGLEINF  = 0x00010000;
  public const uint DI_FLAGSEX_ALLOWEXCLUDEDDRVS = 0x00000040;
  [StructLayout(LayoutKind.Sequential)]
  public struct SP_DEVINFO_DATA { public uint cbSize; public Guid ClassGuid; public uint DevInst; public IntPtr Reserved; }
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  public struct SP_DEVINSTALL_PARAMS {
    public uint cbSize; public uint Flags; public uint FlagsEx;
    public IntPtr hwndParent; public IntPtr InstallMsgHandler; public IntPtr InstallMsgHandlerContext;
    public IntPtr FileQueue; public UIntPtr ClassInstallReserved; public uint Reserved;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=MAX_PATH)] public string DriverPath; }
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  public struct SP_DRVINFO_DATA {
    public uint cbSize; public uint DriverType; public UIntPtr Reserved;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=LINE_LEN)] public string Description;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=LINE_LEN)] public string MfgName;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=LINE_LEN)] public string ProviderName;
    public long DriverDate; public ulong DriverVersion; }
  // CharSet.Unicode en TODAS: si no, .NET resuelve la variante ANSI (que espera
  // structs con campos de texto de 260 bytes) mientras nuestras structs son
  // Unicode (520 bytes) -> cbSize no cuadra -> ERROR_INVALID_USER_BUFFER (1784).
  [DllImport("setupapi.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern IntPtr SetupDiCreateDeviceInfoList(IntPtr g, IntPtr h);
  [DllImport("setupapi.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern bool SetupDiOpenDeviceInfo(IntPtr h, string id, IntPtr hwnd, uint f, ref SP_DEVINFO_DATA d);
  [DllImport("setupapi.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern bool SetupDiGetDeviceInstallParams(IntPtr h, ref SP_DEVINFO_DATA d, ref SP_DEVINSTALL_PARAMS p);
  [DllImport("setupapi.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern bool SetupDiSetDeviceInstallParams(IntPtr h, ref SP_DEVINFO_DATA d, ref SP_DEVINSTALL_PARAMS p);
  [DllImport("setupapi.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern bool SetupDiBuildDriverInfoList(IntPtr h, ref SP_DEVINFO_DATA d, uint t);
  [DllImport("setupapi.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern bool SetupDiEnumDriverInfo(IntPtr h, ref SP_DEVINFO_DATA d, uint t, uint i, ref SP_DRVINFO_DATA drv);
  [DllImport("setupapi.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern bool SetupDiSetSelectedDriver(IntPtr h, ref SP_DEVINFO_DATA d, ref SP_DRVINFO_DATA drv);
  [DllImport("setupapi.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern bool SetupDiDestroyDeviceInfoList(IntPtr h);
  [DllImport("newdev.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern bool DiInstallDevice(IntPtr hwnd, IntPtr h, ref SP_DEVINFO_DATA d, ref SP_DRVINFO_DATA drv, uint f, out bool reboot);
  [DllImport("newdev.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern bool UpdateDriverForPlugAndPlayDevicesW(IntPtr hwnd, string hwid, string inf, uint flags, out bool reboot);

  public static string Run(string instanceId, string infPath) {
    IntPtr h = SetupDiCreateDeviceInfoList(IntPtr.Zero, IntPtr.Zero);
    if (h == (IntPtr)(-1)) throw new Exception("CreateList:"+Marshal.GetLastWin32Error());
    try {
      var dev = new SP_DEVINFO_DATA(); dev.cbSize=(uint)Marshal.SizeOf(typeof(SP_DEVINFO_DATA));
      if (!SetupDiOpenDeviceInfo(h, instanceId, IntPtr.Zero, 0, ref dev))
        throw new Exception("Open:"+Marshal.GetLastWin32Error());
      var p = new SP_DEVINSTALL_PARAMS(); p.cbSize=(uint)Marshal.SizeOf(typeof(SP_DEVINSTALL_PARAMS));
      if (!SetupDiGetDeviceInstallParams(h, ref dev, ref p)) throw new Exception("GetParams:"+Marshal.GetLastWin32Error());
      p.Flags   |= DI_ENUMSINGLEINF;
      p.FlagsEx |= DI_FLAGSEX_ALLOWEXCLUDEDDRVS;
      p.DriverPath = infPath;
      if (!SetupDiSetDeviceInstallParams(h, ref dev, ref p)) throw new Exception("SetParams:"+Marshal.GetLastWin32Error());
      if (!SetupDiBuildDriverInfoList(h, ref dev, SPDIT_CLASSDRIVER)) throw new Exception("Build:"+Marshal.GetLastWin32Error());
      var chosen = new SP_DRVINFO_DATA(); bool got=false; string seen="";
      for (uint i=0;;i++) {
        var drv = new SP_DRVINFO_DATA(); drv.cbSize=(uint)Marshal.SizeOf(typeof(SP_DRVINFO_DATA));
        if (!SetupDiEnumDriverInfo(h, ref dev, SPDIT_CLASSDRIVER, i, ref drv)) break;
        seen += " | " + drv.Description;
        if (!got){ chosen=drv; got=true; }
        if (drv.Description!=null && drv.Description.IndexOf("ADB",StringComparison.OrdinalIgnoreCase)>=0){ chosen=drv; got=true; break; }
      }
      if (!got) throw new Exception("EMPTY_LIST");
      if (!SetupDiSetSelectedDriver(h, ref dev, ref chosen)) throw new Exception("Select:"+Marshal.GetLastWin32Error());
      bool reboot;
      if (!DiInstallDevice(IntPtr.Zero, h, ref dev, ref chosen, 0, out reboot)) throw new Exception("Install:"+Marshal.GetLastWin32Error());
      return "OK::"+chosen.Description+" [candidatos:"+seen+"]";
    } finally { SetupDiDestroyDeviceInfoList(h); }
  }

  public static string RunForce(string hwid, string infPath) {
    bool rb;
    if (!UpdateDriverForPlugAndPlayDevicesW(IntPtr.Zero, hwid, infPath, 0x1, out rb))
      throw new Exception("Force:"+Marshal.GetLastWin32Error());
    return "OK::force";
  }
}
'@

    $result = ""
    try { $result = [FB]::Run($InstanceId, $Inf) }
    catch {
        $err1 = $_.Exception.Message
        Write-Host ("DiInstallDevice fallo: " + $err1)
        if ($err1 -match "EMPTY_LIST") {
            # Dispositivo en clase Unknown (Otros dispositivos): fija la clase
            # Android y reintenta (equivale a elegir la categoria en el asistente).
            $g = "{3F966BD9-FA04-4EC5-991C-D326973B5128}"
            $k = "HKLM:\SYSTEM\CurrentControlSet\Enum\$InstanceId"
            try { New-ItemProperty $k -Name ClassGUID -Value $g -PropertyType String -Force | Out-Null } catch {}
            Start-Sleep 1
            try { $result = [FB]::Run($InstanceId, $Inf) } catch { $err1 = $err1 + " ; retry: " + $_.Exception.Message }
        }
        if (-not ($result -like 'OK::*')) {
            # Fallback: UpdateDriverForPlugAndPlayDevices con FORCE contra el HWID real.
            $hwid = (Get-PnpDeviceProperty -InstanceId $InstanceId -KeyName 'DEVPKEY_Device_HardwareIds' -EA SilentlyContinue).Data |
                    Where-Object { $_ -like 'USB\VID_*' } | Select-Object -First 1
            if ($hwid) {
                Write-Host ("Fallback UpdateDriver FORCE con " + $hwid)
                try { $result = [FB]::RunForce($hwid, $Inf) } catch { $result = "FAIL::" + $err1 + " | force: " + $_.Exception.Message }
            } else { $result = "FAIL::" + $err1 }
        }
    }
    Write-Host ("Resultado  : " + $result)

    Start-Sleep -Seconds 2
    $after = Get-PnpDevice -InstanceId $InstanceId -EA SilentlyContinue
    if ($after) { Write-Host ("Estado ahora: " + $after.Status + " (code " + $after.ConfigManagerErrorCode + ")") }
    if (($after -and $after.Status -eq 'OK' -and $after.ConfigManagerErrorCode -eq 0) -or ($result -like 'OK::*')) { $exit = 0 }
} catch {
    Write-Host ("[ERROR] " + $_.Exception.Message) -ForegroundColor Red
    Write-Host $_.ScriptStackTrace
    $exit = 3
}
try { Stop-Transcript | Out-Null } catch {}
if ($exit -ne 0) {
    Write-Host ""
    Write-Host "No se pudo forzar el driver automaticamente." -ForegroundColor Yellow
    Write-Host ("Log guardado en: " + $Log)
    Write-Host "Haz una captura de esta ventana (y del log) para poder ayudarte."
    Read-Host "Pulsa ENTER para cerrar"
}
exit $exit
'''


def force_bind(instance_id, inf_path):
    """Fuerza el android_winusb.inf (firmado, SIN editar) sobre el InstanceId dado,
    replicando 'Elegir de una lista -> Android ADB Interface'. Una sola UAC."""
    if not is_windows():
        return False
    log = os.path.join(DRIVERS_DIR, "forcebind.log")
    ps = (_FORCE_BIND_PS
          .replace("{log}", log)
          .replace("{inf}", inf_path)
          .replace("{instance_id}", instance_id))
    return _run_elevated_ps(ps)


def setup_fastboot_windows():
    """Detecta el telefono Android con problema de driver e instala/FUERZA el
    driver correcto para que 'fastboot' lo vea, en UNA sola ventana UAC. Devuelve
    True si quedo enlazado. No-op fuera de Windows."""
    if not is_windows():
        return False
    cand = pick_fastboot_candidate(find_problem_usb_devices())
    if not cand:
        print("   [i] No veo ningun dispositivo Android con problema de driver.")
        print("       Asegurate de que el telefono esta conectado en modo fastboot.")
        return False
    print(f"   [*] Dispositivo detectado: {cand.get('name') or cand['instance_id']}")
    inf = _ensure_google_usb_driver_extracted()
    if not inf:
        return False
    print("   [*] Instalando y FORZANDO el driver correcto sobre el dispositivo.")
    print("   [*] Acepta el aviso de seguridad de Windows ('Si') cuando aparezca.")
    ok = force_bind(cand["instance_id"], inf)
    if ok:
        print("   [OK] Driver enlazado correctamente.")
    else:
        print("   [i] No se pudo enlazar el driver automaticamente.")
        print(f"       Detalle del intento en: {os.path.join(DRIVERS_DIR, 'forcebind.log')}")
    return ok


# ------------------------------------------------------------------
#  UsbDk (para el modo BROM de mtkclient)
# ------------------------------------------------------------------
def ensure_usbdk():
    """Instala UsbDk (firmado), que mtkclient necesita para hablar con el modo
    BROM de MediaTek. Pide UNA aprobacion UAC. Mejor esfuerzo."""
    if not is_windows():
        return False
    msi = os.path.join(DRIVERS_DIR, "UsbDk.msi")
    if not os.path.isfile(msi):
        print("   [*] Descargando UsbDk (driver para el modo BROM de MediaTek)...")
        if not _download(USBDK_MSI_URL, msi):
            return False
    print("   [*] Instalando UsbDk. Acepta el aviso de Windows ('Si').")
    ps = ("Start-Process msiexec -ArgumentList '/i','" + msi + "','/quiet','/norestart' "
          "-Wait; exit 0")
    return _run_elevated_ps(ps)


# Compatibilidad: el flujo principal puede llamar a cualquiera de las dos.
def ensure_fastboot_driver():
    """Alias del flujo completo (deteccion + force-bind). No-op fuera de Windows."""
    return setup_fastboot_windows()
