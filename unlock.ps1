<#
============================================================
 Plug-and-Play OEM Unlock - lanzador PowerShell (Windows)
 Alternativa a unlock.bat. Detecta e INSTALA Python 3 solo si falta,
 evitando el senuelo "Python was not found" de la Microsoft Store.

 COMO EJECUTARLO (si Windows bloquea los scripts .ps1):
   Boton derecho > "Ejecutar con PowerShell"
   o en una terminal:
     powershell -ExecutionPolicy Bypass -File unlock.ps1
   (puedes pasarle opciones:  ... -File unlock.ps1 --auto  /  --watch  /  --list)
============================================================
#>

# Permite el script en esta sesion aunque la politica global lo restrinja.
try { Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force -ErrorAction SilentlyContinue } catch {}

Set-Location -LiteralPath $PSScriptRoot

function Test-Python {
    # Devuelve $true solo si el comando ejecuta Python 3 DE VERDAD (no el stub
    # de la Store, que devuelve un codigo de error).
    param([string[]]$Cmd)
    try {
        $exe = $Cmd[0]
        $rest = @()
        if ($Cmd.Count -gt 1) { $rest = $Cmd[1..($Cmd.Count - 1)] }
        $null = Get-Command $exe -ErrorAction Stop
        & $exe @rest -c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-InstalledPython {
    # Tras instalar, el PATH de esta sesion no se refresca: buscamos python.exe
    # en las rutas tipicas de instalacion.
    $dirs = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313",
        "$env:LOCALAPPDATA\Programs\Python\Python312",
        "$env:LOCALAPPDATA\Programs\Python\Python311",
        "$env:ProgramFiles\Python313",
        "$env:ProgramFiles\Python312",
        "$env:ProgramFiles\Python311"
    )
    foreach ($d in $dirs) {
        $exe = Join-Path $d "python.exe"
        if (Test-Path $exe) {
            & $exe -c "import sys" *> $null
            if ($LASTEXITCODE -eq 0) { return , @($exe) }
        }
    }
    if (Test-Python @('py', '-3')) { return , @('py', '-3') }
    return $null
}

# --- 1) Buscar un Python REAL (el lanzador 'py' no lo tapa el alias de la Store) ---
# (if/elseif explicitos: los arrays anidados en un literal @(...) se aplanarian)
$python = $null
if     (Test-Python @('py', '-3'))  { $python = @('py', '-3') }
elseif (Test-Python @('python'))    { $python = @('python') }
elseif (Test-Python @('python3'))   { $python = @('python3') }

# --- 2) No hay Python: instalarlo automaticamente (mejor esfuerzo, sin admin) ---
if (-not $python) {
    Write-Host ""
    Write-Host "[*] Python 3 no encontrado (o solo aparece el senuelo de la Microsoft Store)."
    Write-Host "[*] Intentando instalarlo automaticamente. Puede tardar un par de minutos..."
    Write-Host ""

    # 2a) winget (App Installer), sin permisos de admin
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "[*] Instalando con winget..."
        winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
        $python = Find-InstalledPython
    }

    # 2b) Instalador oficial de python.org, en silencio
    if (-not $python) {
        try {
            $url = 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe'
            $setup = Join-Path $env:TEMP 'python-setup-pnp.exe'
            Write-Host "[*] Descargando el instalador oficial de python.org..."
            Invoke-WebRequest $url -OutFile $setup -UseBasicParsing -ErrorAction Stop
            Write-Host "[*] Instalando Python en silencio (solo para tu usuario)..."
            Start-Process -FilePath $setup -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1', 'Include_pip=1' -Wait
            Remove-Item $setup -ErrorAction SilentlyContinue
            $python = Find-InstalledPython
        } catch {
            Write-Host "[!] No se pudo descargar/instalar desde python.org: $_"
        }
    }

    # 2c) Chocolatey, por si el usuario lo tiene
    if (-not $python -and (Get-Command choco -ErrorAction SilentlyContinue)) {
        Write-Host "[*] Instalando con Chocolatey..."
        choco install python -y
        $python = Find-InstalledPython
    }

    # 2d) ultimo intento con los alias por si el PATH ya cambio
    if (-not $python -and (Test-Python @('py', '-3')))  { $python = @('py', '-3') }
    if (-not $python -and (Test-Python @('python')))    { $python = @('python') }
}

if (-not $python) {
    Write-Host ""
    Write-Host "[X] No se pudo preparar Python 3 automaticamente." -ForegroundColor Red
    Write-Host "    Opcion A: instala Python desde https://www.python.org/downloads/"
    Write-Host "              y marca 'Add python.exe to PATH'."
    Write-Host "    Opcion B: desactiva el senuelo en Configuracion > Aplicaciones >"
    Write-Host "              Alias de ejecucion de aplicaciones (apaga python.exe y python3.exe)."
    Read-Host "Pulsa ENTER para salir"
    exit 1
}

# --- 3) Ejecutar la herramienta ---
$exe = $python[0]
$rest = @()
if ($python.Count -gt 1) { $rest = $python[1..($python.Count - 1)] }
$script = Join-Path $PSScriptRoot "src\oem_unlock.py"

Write-Host ""
Write-Host "[*] Usando Python: $($python -join ' ')"
& $exe @rest $script --auto-tools @args
Read-Host "Pulsa ENTER para salir"
