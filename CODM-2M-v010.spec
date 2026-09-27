# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = [('codm_compiler/codm_types.json', 'codm_compiler')]
datas += collect_data_files('UnityPy')
datas += collect_data_files('archspec')
datas += collect_data_files('imgui_bundle', includes=['assets/fonts/*', 'assets/app_settings/*'])


a = Analysis(
    ['launcher.py'],
    pathex=[SPECPATH],
    binaries=collect_dynamic_libs('fmod_toolkit') + collect_dynamic_libs('imgui_bundle') + collect_dynamic_libs('glfw'),
    datas=datas,
    hiddenimports=['OpenGL.platform.win32', 'OpenGL.arrays.numpymodule', 'OpenGL.arrays.ctypesarrays', 'OpenGL.arrays.ctypesparameters', 'OpenGL.arrays.ctypespointers', 'OpenGL.arrays.lists', 'OpenGL.arrays.numbers', 'OpenGL.arrays.strings', 'imgui_bundle._imgui_bundle', 'PIL.PngImagePlugin', 'texture2ddecoder', 'astc_encoder', 'etcpak'] + collect_submodules('astc_encoder') + collect_submodules('etcpak'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'scipy', 'matplotlib', 'pandas', 'cv2', 'IPython'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CODM-2M-v010',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    name='CODM-2M-v010',
)


