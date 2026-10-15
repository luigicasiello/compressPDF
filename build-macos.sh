#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR=".venv-macos"
DIST_DIR="dist/macos"
WORK_DIR="build/macos"
APP_PATH="$DIST_DIR/ComprimiPDF.app"
DMG_PATH="$DIST_DIR/ComprimiPDF.dmg"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Errore: la versione macOS deve essere compilata direttamente su un Mac." >&2
    exit 1
fi

echo "Preparazione dell'ambiente Python per macOS..."
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.txt

echo "Creazione di ComprimiPDF.app..."
"$VENV_DIR/bin/python" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --name "ComprimiPDF" \
    --distpath "$DIST_DIR" \
    --workpath "$WORK_DIR" \
    --specpath "$WORK_DIR" \
    --icon "assets/dog_mascot.icns" \
    --add-data "assets:assets" \
    --collect-all pymupdf \
    --osx-bundle-identifier "it.localtools.comprimipdf" \
    app.py

if [[ -n "${MACOS_SIGN_IDENTITY:-}" ]]; then
    echo "Firma con Developer ID: $MACOS_SIGN_IDENTITY"
    codesign --force --deep --strict --options runtime --timestamp \
        --sign "$MACOS_SIGN_IDENTITY" "$APP_PATH"
else
    echo "Applicazione di una firma ad-hoc per uso locale..."
    codesign --force --deep --strict --sign - "$APP_PATH"
fi

codesign --verify --deep --strict --verbose=2 "$APP_PATH"

echo "Creazione dell'immagine DMG..."
rm -f "$DMG_PATH"
hdiutil create \
    -volname "ComprimiPDF" \
    -srcfolder "$APP_PATH" \
    -ov \
    -format UDZO \
    "$DMG_PATH"

if [[ -n "${MACOS_NOTARY_PROFILE:-}" ]]; then
    if [[ -z "${MACOS_SIGN_IDENTITY:-}" ]]; then
        echo "Errore: la notarizzazione richiede MACOS_SIGN_IDENTITY." >&2
        exit 1
    fi
    echo "Invio ad Apple per la notarizzazione..."
    xcrun notarytool submit "$DMG_PATH" \
        --keychain-profile "$MACOS_NOTARY_PROFILE" \
        --wait
    xcrun stapler staple "$DMG_PATH"
    xcrun stapler validate "$DMG_PATH"
fi

echo
echo "Build macOS completata:"
echo "  $APP_PATH"
echo "  $DMG_PATH"
