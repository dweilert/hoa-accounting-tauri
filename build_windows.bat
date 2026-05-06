@echo off
REM Build HOA Accounting as a Windows executable.
REM Run from the repo root: build_windows.bat

echo === HOA Accounting - Windows Build ===

REM Activate virtual environment
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo ERROR: .venv not found. Run: python -m venv .venv ^&^& pip install -e .[dev]
    exit /b 1
)

REM Ensure PyInstaller is available
pip install --quiet pyinstaller

REM Clean previous build
echo Cleaning previous build...
if exist dist\HOAAccounting rmdir /s /q dist\HOAAccounting
if exist build\HOAAccounting rmdir /s /q build\HOAAccounting

REM Build
echo Running PyInstaller...
pyinstaller hoa_accounting.spec --noconfirm

echo.
echo === Build complete ===
echo Output: dist\HOAAccounting\
echo.
echo To distribute, zip the dist\HOAAccounting\ folder.
echo The recipient should copy it to their Desktop or Program Files,
echo then double-click HOAAccounting.exe to launch.
