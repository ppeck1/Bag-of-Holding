# boh.spec — PyInstaller spec for Bag of Holding v2
#
# Build command:
#   pip install pyinstaller
#   pyinstaller boh.spec
#
# Output: dist/boh/ (directory) or dist/boh.exe (--onefile)
# The resulting executable starts the server and opens the browser automatically.

import sys
from pathlib import Path

block_cipher = None
project_root = Path(SPEC).parent  # noqa: F821 — PyInstaller provides SPEC

a = Analysis(
    ['launcher.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # Include the entire app/ package
        ('app', 'app'),
        # Include the UI static files
        ('app/ui', 'app/ui'),
        # Include schema
        ('app/db/schema.sql', 'app/db'),
        # Include the sample library
        ('library', 'library'),
        # Include docs
        ('docs', 'docs'),
    ],
    hiddenimports=[
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'fastapi',
        'starlette',
        'starlette.staticfiles',
        'starlette.routing',
        'pydantic',
        'yaml',
        'sqlite3',
        'app.api.main',
        'app.api.routes.index',
        'app.api.routes.search',
        'app.api.routes.canon',
        'app.api.routes.conflicts',
        'app.api.routes.library',
        'app.api.routes.workflow',
        'app.api.routes.nodes',
        'app.api.routes.events',
        'app.api.routes.review',
        'app.api.routes.ingest',
        'app.api.routes.dashboard',
        'app.api.routes.lineage',
        'app.core.canon',
        'app.core.conflicts',
        'app.core.planar',
        'app.core.rubrix',
        'app.core.search',
        'app.core.snapshot',
        'app.core.corpus',
        'app.core.lineage',
        'app.services.indexer',
        'app.services.parser',
        'app.services.events',
        'app.services.reviewer',
        'app.services.migration_report',
        'app.db.connection',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='boh',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,       # set False to suppress terminal window on Windows
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='boh',
)
