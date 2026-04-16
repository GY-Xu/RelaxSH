# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path(__file__).resolve().parent.parent
src_root = project_root / "src"

block_cipher = None

a = Analysis(
    [str(src_root / "relaxsh" / "__main__.py")],
    pathex=[str(src_root)],
    binaries=[],
    datas=[(str(src_root / "relaxsh" / "data" / "demo.txt"), "relaxsh/data")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="relaxsh",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

