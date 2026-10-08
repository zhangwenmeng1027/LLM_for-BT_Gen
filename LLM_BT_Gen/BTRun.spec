# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = [('D:/software/anaconda/Library/bin/libexpat.dll', '.'), ('D:/software/anaconda/Library/bin/liblzma.dll', '.'), ('D:/software/anaconda/Library/bin/LIBBZ2.dll', '.'), ('D:/software/anaconda/Library/bin/ffi.dll', '.')]
hiddenimports = []
tmp_ret = collect_all('behaverify')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('textX')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['D:/科研/LLM_for_BT_Gen/LLM_BT_Gen/bt_bench_run.py'],
    pathex=['D:/科研/LLM_for_BT_Gen/behaverify/src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BTRun',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BTRun',
)
