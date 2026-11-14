# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = [('mgba_bundle/mGBA.exe', 'mgba_bundle'), ('melonds_bundle/melonDS.exe', 'melonds_bundle')]
hiddenimports = []
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('clr_loader')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pythonnet')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pycaw')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('comtypes')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


import os as _os
_ROOT = "C:/pkmn"
def _res(rel_file, dest_dir):
    datas.append((_os.path.join(_ROOT, rel_file), ("pklab_res/" + dest_dir) if dest_dir else "pklab_res"))
for _f in ("pklab.html", "mgba_gen3_bridge.lua", "favicon.png"):
    _res(_f, "")
_res("app/assets/app_icon.ico", "app/assets")
for _top in ("data", "boxart"):
    for _d, _dirs, _files in _os.walk(_os.path.join(_ROOT, _top)):
        _dirs[:] = [x for x in _dirs if ".bak" not in x and "avant" not in x]
        for _f in _files:
            if ".bak" in _f or _f.endswith(".tsv"):
                continue
            _rel = _os.path.relpath(_os.path.join(_d, _f), _ROOT).replace(_os.sep, "/")
            _res(_rel, _os.path.dirname(_rel))


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

import re as _re
_ver = _re.search(r'APP_VERSION = "([\d.]+)"', open(_os.path.join(_ROOT, "app", "paths.py"), encoding="utf-8").read()).group(1)
_v4 = tuple((list(int(x) for x in _ver.split(".")) + [0, 0, 0, 0])[:4])
_vfile = _os.path.join(_ROOT, "app", "build_version_info.txt")
with open(_vfile, "w", encoding="utf-8") as _f:
    _f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={_v4}, prodvers={_v4}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040C04B0', [
      StringStruct('CompanyName', 'Mourad (github.com/mrdbmyla)'),
      StringStruct('FileDescription', 'PKLab'),
      StringStruct('FileVersion', '{_ver}'),
      StringStruct('InternalName', 'PKLab'),
      StringStruct('LegalCopyright', '© 2026 Mourad. Tous droits réservés.'),
      StringStruct('OriginalFilename', 'PKLab.exe'),
      StringStruct('ProductName', 'PKLab'),
      StringStruct('ProductVersion', '{_ver}')])]),
    VarFileInfo([VarStruct('Translation', [0x040C, 1200])])
  ]
)
""")

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PKLab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_icon.ico',
    version=_vfile,
)
