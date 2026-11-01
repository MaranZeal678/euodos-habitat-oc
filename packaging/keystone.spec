# PyInstaller spec for the Keystone macOS app. Build with packaging/build_macos.sh (it also makes the icon and .dmg).
# The desktop build leaves out torch/rasterio (live NAIP re-scans fall back to the stored CNN scans) and test tooling.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is provided by PyInstaller
VERSION = (ROOT / "packaging" / "VERSION").read_text().strip()

datas = [
    (str(ROOT / "keystone" / "regions"), "keystone/regions"),
    (str(ROOT / "keystone" / "app"), "keystone/app"),
    *[(str(ROOT / "data" / "processed" / f), "data/processed")
      for f in ("faith_sites.json", "site_scores.json", "market_gap.json", "naip_index.json")],
    *[(str(p), "artifacts") for p in sorted((ROOT / "artifacts").glob("market_gap_*.pkl"))],
    (str(ROOT / "artifacts" / "registry.json"), "artifacts"),
    (str(ROOT / "artifacts" / "improve_log.json"), "artifacts"),
]
LIVE_SCAN_ONLY = ("keystone.models.cnn", "keystone.models.site_score", "keystone.data", "keystone.pipeline",
                  "keystone.demo", "keystone.cli")
hidden = [m for m in collect_submodules("keystone") if not m.startswith(LIVE_SCAN_ONLY)]
hidden += collect_submodules("uvicorn") + collect_submodules("mcp")

a = Analysis(  # noqa: F821
    [str(ROOT / "keystone" / "desktop.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hidden,
    excludes=["torch", "torchvision", "rasterio", "pystac_client", "planetary_computer", "matplotlib", "tkinter",
              "IPython", "pytest", "hypothesis", "playwright", "axe_playwright_python", "keystone.models.cnn",
              "keystone.models.site_score", "keystone.data", "keystone.pipeline", "keystone.demo"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Keystone", console=False,  # noqa: F821
          argv_emulation=False, target_arch=None, codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name="Keystone")  # noqa: F821
app = BUNDLE(  # noqa: F821
    coll,
    name="Keystone.app",
    icon=str(ROOT / "packaging" / "build" / "Keystone.icns"),
    bundle_identifier="org.keystone.desktop",
    version=VERSION,
    info_plist={
        "CFBundleDisplayName": "Keystone",
        "CFBundleShortVersionString": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "13.0",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHumanReadableCopyright": "Keystone for Habitat for Humanity of Orange County · Keys to 100",
    },
)
