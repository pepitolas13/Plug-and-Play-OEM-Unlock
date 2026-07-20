@echo off
REM ============================================================
REM  Plug-and-Play OEM Unlock - lanzador Windows
REM  Doble clic desde el USB. Detecta e INSTALA Python 3 solo si falta,
REM  evitando el senuelo "Python was not found" de la Microsoft Store.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PYTHON="

REM --- 1) Buscar un Python REAL (no el stub de la Store) ---
REM    El lanzador 'py' es el mas fiable porque el alias de la Store no lo tapa.
call :try_python py -3
if defined PYTHON goto :run
call :try_python python
if defined PYTHON goto :run
call :try_python python3
if defined PYTHON goto :run

REM --- 2) No hay Python: instalarlo automaticamente (mejor esfuerzo) ---
echo.
echo [*] Python 3 no encontrado (o solo aparece el senuelo de la Microsoft Store).
echo [*] Intentando instalarlo automaticamente. Esto puede tardar un par de minutos...
echo.

REM 2a) winget (App Installer) - sin permisos de admin (--scope user)
where winget >nul 2>nul
if !errorlevel!==0 (
    echo [*] Instalando con winget...
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    call :find_installed_python
    if defined PYTHON goto :run
)

REM 2b) Instalador oficial de python.org, descargado y ejecutado en silencio
where powershell >nul 2>nul
if !errorlevel!==0 (
    echo [*] Descargando el instalador oficial de python.org...
    set "PYSETUP=%TEMP%\python-setup-pnp.exe"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '!PYSETUP!' -UseBasicParsing } catch { exit 1 }"
    if exist "!PYSETUP!" (
        echo [*] Instalando Python en silencio (solo para tu usuario)...
        "!PYSETUP!" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1
        del "!PYSETUP!" >nul 2>nul
        call :find_installed_python
        if defined PYTHON goto :run
    ) else (
        echo [!] No se pudo descargar el instalador ^(sin internet?^).
    )
)

REM 2c) Chocolatey, por si el usuario lo tiene
where choco >nul 2>nul
if !errorlevel!==0 (
    echo [*] Instalando con Chocolatey...
    choco install python -y
    call :find_installed_python
    if defined PYTHON goto :run
)

REM --- 3) Si se instalo pero esta ventana no ve aun el PATH nuevo ---
call :try_python py -3
if defined PYTHON goto :run
call :try_python python
if defined PYTHON goto :run

echo.
echo [X] No se pudo preparar Python 3 automaticamente.
echo     Opcion A: instala Python desde https://www.python.org/downloads/
echo               y marca la casilla "Add python.exe to PATH".
echo     Opcion B: desactiva el senuelo de la Store en
echo               Configuracion ^> Aplicaciones ^> Alias de ejecucion de aplicaciones
echo               (desactiva python.exe y python3.exe), luego reinstala Python.
echo     Despues, vuelve a abrir unlock.bat.
echo.
pause
exit /b 1

REM ============================================================
:run
echo.
echo [*] Usando Python: %PYTHON%
%PYTHON% "%~dp0src\oem_unlock.py" --auto-tools %*
echo.
pause
exit /b 0

REM ============================================================
REM  Subrutinas
REM ============================================================
:try_python
REM  Comprueba que el comando (%*) ejecuta Python 3 DE VERDAD (no el stub).
REM  El senuelo de la Store devuelve un codigo de error, asi que no pasa.
set "CAND=%*"
%CAND% -c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" >nul 2>nul
if !errorlevel!==0 set "PYTHON=%CAND%"
goto :eof

:find_installed_python
REM  Tras instalar, el PATH de ESTA ventana no se refresca: buscamos el .exe
REM  en las rutas tipicas de instalacion (usuario y sistema).
for %%D in (
    "%LocalAppData%\Programs\Python\Python313"
    "%LocalAppData%\Programs\Python\Python312"
    "%LocalAppData%\Programs\Python\Python311"
    "%ProgramFiles%\Python313"
    "%ProgramFiles%\Python312"
    "%ProgramFiles%\Python311"
) do (
    if exist "%%~D\python.exe" (
        "%%~D\python.exe" -c "import sys" >nul 2>nul
        if !errorlevel!==0 (
            set "PYTHON=%%~D\python.exe"
            goto :eof
        )
    )
)
REM  El lanzador 'py' pudo quedar disponible aunque 'python' no.
py -3 -c "import sys" >nul 2>nul
if !errorlevel!==0 set "PYTHON=py -3"
goto :eof
