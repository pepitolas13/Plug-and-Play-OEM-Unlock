
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
G:\Plug-and-Play-OEM-Unlock-main\drivers\forcebind.log
'@
$Inf = @'
G:\Plug-and-Play-OEM-Unlock-main\drivers\google_usb\usb_driver\android_winusb.inf
'@
$InstanceId = @'
USB\VID_0E8D&PID_201C\PILOT1NEU0000767
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
