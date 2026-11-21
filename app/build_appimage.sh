#!/bin/bash
set -euo pipefail
SRC="${SRC:-/mnt/c/pkmn}"
EMU="${EMU:-/root/pklab}"
WORK="${WORK:-$HOME/pkbuild}"
OUT="${OUT:-$WORK/PKLab-x86_64.AppImage}"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.12.16%2B20261110-x86_64-unknown-linux-gnu-install_only.tar.gz"
PY_SHA="c2f87d4b4e8db3abddb0f116c6ccfc503d0cbdbb9ee8faacddad1b679ec12e99"
TOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64"
DEBS="libnss3 libnspr4 libxcb-cursor0 libxkbfile1"
PIP="numpy==2.5.5 pywebview==6.2.1 bottle==0.13.4 proxy_tools==0.1.0 qtpy==2.4.3 PyQt6==6.12.1 PyQt6-Qt6==6.12.0 PyQt6-sip==13.13.1 PyQt6-WebEngine==6.140.1 PyQt6-WebEngine-Qt6==6.140.0"
KEEP_PYQT="QtCore QtGui QtWidgets QtNetwork QtWebChannel QtWebEngineCore QtWebEngineWidgets QtPrintSupport QtOpenGL QtOpenGLWidgets QtDBus QtPositioning QtQml QtQuick QtQuickWidgets"
LOCALES="en-US fr es de it"

DL="$WORK/dl"
APPDIR="$WORK/AppDir"
mkdir -p "$DL"
[ -f "$DL/python.tar.gz" ] || curl -fsSL -o "$DL/python.tar.gz" "$PY_URL"
echo "$PY_SHA  $DL/python.tar.gz" | sha256sum -c -
[ -x "$DL/appimagetool" ] || { curl -fsSL -o "$DL/appimagetool" "$TOOL_URL"; chmod +x "$DL/appimagetool"; }
[ -f "$DL/runtime-x86_64" ] || curl -fsSL -o "$DL/runtime-x86_64" "$RUNTIME_URL"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/share/pklab"
tar -xzf "$DL/python.tar.gz" -C "$APPDIR/usr"
mv "$APPDIR/usr/python" "$APPDIR/usr/py"
PY="$APPDIR/usr/py/bin/python3"
"$PY" -m pip install --no-cache-dir --no-warn-script-location --root-user-action=ignore -q $PIP
SITE="$APPDIR/usr/py/lib/python3.12/site-packages"
Q="$SITE/PyQt6/Qt6"

rm -rf "$DL/debs" && mkdir -p "$DL/debs"
(cd "$DL/debs" && apt-get download $DEBS >/dev/null 2>&1)
for d in "$DL"/debs/*.deb; do dpkg-deb -x "$d" "$DL/debs/x"; done
cp -L "$DL"/debs/x/usr/lib/x86_64-linux-gnu/*.so* "$Q/lib/"
[ -d "$DL/debs/x/usr/lib/x86_64-linux-gnu/nss" ] && cp -L "$DL"/debs/x/usr/lib/x86_64-linux-gnu/nss/*.so* "$Q/lib/"
command -v patchelf >/dev/null || apt-get install -y -q patchelf >/dev/null
for f in "$DL"/debs/x/usr/lib/x86_64-linux-gnu/*.so* "$DL"/debs/x/usr/lib/x86_64-linux-gnu/nss/*.so*; do
  [ -e "$f" ] && patchelf --set-rpath '$ORIGIN' "$Q/lib/$(basename "$f")"
done

for m in "$SITE"/PyQt6/Qt*.abi3.so; do
  n=$(basename "$m" .abi3.so)
  case " $KEEP_PYQT " in *" $n "*) ;; *) rm -f "$m" "$SITE/PyQt6/$n.pyi";; esac
done
rm -rf "$Q/qml" "$Q/plugins/sqldrivers" "$Q/plugins/multimedia" "$Q/plugins/qmltooling" "$Q/plugins/sensors" \
  "$Q/plugins/texttospeech" "$Q/plugins/designer" "$Q/plugins/canbus" "$Q/plugins/renderers" "$Q/plugins/assetimporters" \
  "$Q/plugins/position" "$Q/plugins/geometryloaders" "$Q/plugins/sceneparsers" "$Q/plugins/printsupport" \
  "$Q/plugins/platformthemes/libqgtk3.so" "$Q/plugins/wayland"* "$Q/plugins/egldeviceintegrations"
find "$Q/plugins/platforms" -type f ! -name "libqxcb.so" ! -name "libqoffscreen.so" -delete
find "$Q/translations" -maxdepth 1 -name "*.qm" -delete
for f in "$Q"/translations/qtwebengine_locales/*.pak; do
  b=$(basename "$f" .pak)
  case " $LOCALES " in *" $b "*) ;; *) rm -f "$f";; esac
done

needed=$(mktemp)
roots=$(ls "$SITE"/PyQt6/*.so; find "$Q/plugins" -name "*.so"; echo "$Q/libexec/QtWebEngineProcess"; ls "$Q"/lib/libnss*.so* "$Q"/lib/libsoftokn3.so* "$Q"/lib/libfreebl*.so* "$Q"/lib/libsmime3.so* 2>/dev/null || true)
for f in $roots; do
  LD_LIBRARY_PATH="$Q/lib" ldd "$f" 2>/dev/null | awk '{print $3}' | grep "^$Q/lib/" || true
  basename "$f"
done | xargs -n1 basename | sort -u > "$needed"
for f in "$Q"/lib/lib*.so*; do
  b=$(basename "$f")
  grep -qx "$b" "$needed" && continue
  case "$b" in libnss*|libnspr*|libplc*|libplds*|libsmime*|libsoftokn*|libfreebl*|libnssckbi*|libnssdbm*) continue;; esac
  rm -f "$f"
done
rm -f "$needed"
find "$APPDIR/usr/py" -depth -type d \( -name "test" -o -name "tests" -o -name "idlelib" -o -name "tkinter" -o -name "turtledemo" -o -name "ensurepip" \) -exec rm -rf {} +
find "$APPDIR/usr/py" -name "*.so*" -type f -exec strip --strip-unneeded {} + 2>/dev/null || true
rm -rf "$APPDIR/usr/py/lib/python3.12/lib-dynload/_tkinter"* "$APPDIR/usr/py/lib/libtcl"* "$APPDIR/usr/py/lib/libtk"* "$APPDIR/usr/py/lib/tcl"* "$APPDIR/usr/py/lib/tk"* "$APPDIR/usr/py/share"

R="$APPDIR/usr/share/pklab"
mkdir -p "$R/app/assets"
for f in "$SRC"/app/*.py; do
  case "$(basename "$f")" in build_*|make_update.py) ;; *) cp "$f" "$R/app/";; esac
done
cp "$SRC/app/assets/pklab_256.png" "$R/app/assets/"
cp "$SRC/pklab.html" "$SRC/mgba_gen3_bridge.lua" "$SRC/mgba_gen2_bridge.lua" "$SRC/favicon.png" "$R/"
for top in data boxart; do
  (cd "$SRC" && find "$top" -type f ! -name "*.bak*" ! -name "*.tsv" ! -path "*avant*" -print0) | (cd "$SRC" && xargs -0 cp --parents -t "$R")
done
mkdir -p "$R/emulators/mgba" "$R/emulators/melonds"
cp "$EMU/mgba/mGBA.AppImage" "$R/emulators/mgba/"
cp "$EMU/melonds/melonDS.AppImage" "$R/emulators/melonds/"
chmod 755 "$R"/emulators/*/*.AppImage
"$PY" -m compileall -q "$R/app" "$APPDIR/usr/py/lib/python3.12" >/dev/null 2>&1 || true

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export PKLAB_RES_DIR="$HERE/usr/share/pklab"
export PYWEBVIEW_GUI=qt
export QT_QPA_PLATFORM="${PKLAB_QPA:-xcb}"
if [ "$(id -u)" = 0 ]; then export QTWEBENGINE_DISABLE_SANDBOX=1; fi
exec "$HERE/usr/py/bin/python3" -s -E "$HERE/usr/share/pklab/app/app.py" "$@"
EOF
chmod 755 "$APPDIR/AppRun"
cat > "$APPDIR/pklab.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=PKLab
Comment=Pokémon companion for mGBA, melonDS and Azahar
Exec=PKLab
Icon=pklab
Categories=Game;
Terminal=false
EOF
cp "$SRC/app/assets/pklab_256.png" "$APPDIR/pklab.png"
ln -sf pklab.png "$APPDIR/.DirIcon"

rm -f "$OUT"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$DL/appimagetool" --no-appstream --runtime-file "$DL/runtime-x86_64" "$APPDIR" "$OUT" >/dev/null
chmod 755 "$OUT"
du -sh "$APPDIR" "$OUT"
sha256sum "$OUT"
