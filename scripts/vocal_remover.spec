# PyInstaller spec. Models are not bundled: the app downloads them on first run.
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
datas, binaries, hidden = [(str(ROOT / "app" / "web"), "web")], [], []
for pkg in ("mlx", "mlx_audio_separator", "mlx_audio_io", "mlx_spectro", "webview"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h
hidden += collect_submodules("mlx_audio_separator.separator") + ["catalog", "worker", "ckpt_loader"]

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT / "app")],
    datas=datas, binaries=binaries, hiddenimports=hidden,
    excludes=["torch", "torchaudio", "onnx", "coremltools", "demucs", "tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide6", "gi"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Vocal Remover",
          console=False, argv_emulation=False, target_arch="arm64")
coll = COLLECT(exe, a.binaries, a.datas, name="Vocal Remover")
app = BUNDLE(
    coll,
    name="Vocal Remover.app",
    icon=str(ROOT / "build" / "AppIcon.icns"),
    bundle_identifier="local.vocalremover.app",
    version="1.0.0",
    info_plist={
        "CFBundleDisplayName": "Vocal Remover",
        "CFBundleShortVersionString": "1.0.0",
        "LSMinimumSystemVersion": "13.0",
        "LSArchitecturePriority": ["arm64"],
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "Audio",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "Alternate",
            "LSItemContentTypes": ["public.audio"],
        }],
    },
)
