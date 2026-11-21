#!/bin/zsh
# Builds dist/Vocal Remover.app (and optionally a .dmg) from scratch.
#   ./build.sh          build the app
#   ./build.sh --dmg    also make dist/Vocal-Remover.dmg
set -euo pipefail
cd "${0:A:h}"
PY=3.12

[[ "$(uname -m)" == arm64 ]] || { echo "Apple Silicon required (MLX)."; exit 1; }
command -v uv >/dev/null || { echo "Install uv first: brew install uv"; exit 1; }

# 1. Runtime venv (no torch: models are downloaded and converted in the app).
if [[ ! -x build/venv-app/bin/pyinstaller ]]; then
  echo "==> Creating app environment"
  uv venv -q -p $PY build/venv-app
  uv pip install -q --python build/venv-app/bin/python -r requirements.txt
fi

# 2. Icon.
if [[ ! -f build/AppIcon.icns ]]; then
  echo "==> Drawing icon"
  swift scripts/make_icon.swift build/icon.png
  rm -rf build/AppIcon.iconset && mkdir build/AppIcon.iconset
  for s in 16 32 128 256 512; do
    sips -z $s $s build/icon.png --out build/AppIcon.iconset/icon_${s}x${s}.png >/dev/null
    sips -z $((s*2)) $((s*2)) build/icon.png --out build/AppIcon.iconset/icon_${s}x${s}@2x.png >/dev/null
  done
  iconutil -c icns build/AppIcon.iconset -o build/AppIcon.icns
fi

# 3. Bundle the app.
echo "==> Bundling"
build/venv-app/bin/pyinstaller --noconfirm --clean --log-level WARN \
  --distpath dist --workpath build/pyinstaller scripts/vocal_remover.spec
rm -rf "dist/Vocal Remover"   # the loose onedir copy; the .app is what we ship
APP="dist/Vocal Remover.app"

# 4. Record the hashes of the re-signed native extensions, then re-seal the
#    outer bundle. No --deep: inner binaries keep PyInstaller's signatures.
build/venv-app/bin/python scripts/fix_record.py "$APP"
echo "==> Signing (ad-hoc)"
codesign --force --sign - "$APP"
codesign --verify --strict "$APP" && echo "signature ok"

if [[ "${1:-}" == "--dmg" ]]; then
  echo "==> Making DMG"
  STAGE=build/dmg-stage
  rm -rf $STAGE dist/Vocal-Remover.dmg && mkdir -p $STAGE
  cp -cR "$APP" $STAGE/          # APFS clone, no extra space
  ln -s /Applications $STAGE/Applications
  hdiutil create -quiet -volname "Vocal Remover" -srcfolder $STAGE -ov -format ULFO dist/Vocal-Remover.dmg
  rm -rf $STAGE
  du -sh dist/Vocal-Remover.dmg
fi

echo "==> Self-test"
"$APP/Contents/MacOS/Vocal Remover" --selftest | grep SELFTEST
du -sh "$APP"
echo "Done: $APP"
