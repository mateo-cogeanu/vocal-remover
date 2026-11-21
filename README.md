# Vocal Remover

A Mac app for splitting songs into stems, built on
[mlx-audio-separator](https://github.com/ssmall256/mlx-audio-separator). Runs on the
Apple Silicon GPU through MLX. No PyTorch, no Python install: one small app (about 80 MB
to download).

On first launch, press **Download all** to fetch the models (6 models, 4.1 GB). After that,
everything runs offline. Models are stored in
`~/Library/Application Support/Vocal Remover/models`.

## Models

| Model | Output | Notes |
|---|---|---|
| BS-Roformer SW (jarredou) | Vocals, Drums, Bass, Guitar, Piano, Other | 6-stem split |
| BS-Roformer Viperx 1297 | Vocals, Instrumental | Default. Best instrumental (SDR 16.5) |
| Mel-Roformer Kim | Vocals, Instrumental | Cleanest vocals (SDR 12.6) |
| Mel-Roformer Lite (ZFTurbo) | Vocals, Instrumental | 67 MB, fastest |

**Ensemble:** with a Vocals + Instrumental model selected, turn on Ensemble and pick a
second model. Both run, and their stems are averaged (UVR's "Avg Wave"). This usually
gives cleaner results than either model alone, but takes twice as long.

**Vocal extras** run on the Vocals stem after the main split, so they work with any
model, ensembles included:

| Extra | Model | Adds |
|---|---|---|
| Split lead & backing vocals | Mel-Roformer Karaoke (aufr33 & viperx) | Lead Vocals, Backing Vocals |
| Remove reverb from vocals | Mel-Roformer De-Reverb (anvuew) | Vocals (No Reverb), or Lead Vocals (No Reverb) when splitting too |

Extras are always saved. "Keep" applies to the main model's stems.

Most models are published as PyTorch `.ckpt` checkpoints. The app converts each one to
MLX `.safetensors` right after downloading, with its own checkpoint reader
([`app/ckpt_loader.py`](app/ckpt_loader.py)), so PyTorch is never needed. The reader only
rebuilds tensors and never runs code from the file. Its output is bit-for-bit identical
to converting with PyTorch.

## Using it

Drop songs or folders onto the window, pick a model and which stems to keep, then
press **Separate**. Each song gets its own folder (`~/Music/Vocal Remover/<song>/`
by default), with files named `Vocals.wav`, `Instrumental.wav` and so on. Click a stem to
play it in the app. Switching stems while one plays keeps your place, so you can A/B them.

## Building

```bash
./build.sh          # -> dist/Vocal Remover.app
./build.sh --dmg    # also dist/Vocal-Remover.dmg
```

Needs an Apple Silicon Mac, `uv`, and Xcode command line tools (for `swift`, `iconutil`).

What the build does:

1. Creates a venv with the runtime dependencies (no PyTorch).
2. Bundles the GUI (pywebview) and runtime with PyInstaller.
3. Fixes the native-extension hashes that mlx-audio-io verifies, ad-hoc signs the app,
   and runs a self-test that opens the window.

To change the model list, edit `MODELS` or `TOOLS` in `app/catalog.py` and rebuild. Any
Roformer model from `mlx-audio-separator --list_models` works. The app then offers to
download the new ones.

Run from source without building:

```bash
uv venv -p 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python app/main.py
```

## Layout

```
app/main.py        window, file dialogs, drag-drop, local stem player server
app/worker.py      separation in a child process (cancellable, emits JSON progress)
app/catalog.py     the model list
app/ckpt_loader.py torch-free PyTorch checkpoint reader
app/web/           the interface (HTML/CSS/JS)
scripts/           icon, PyInstaller spec, RECORD fix
```

The app is ad-hoc signed, which is fine on the Mac that built it. To share it with
other Macs, sign it with a Developer ID and notarize it, or recipients will need to
right-click → Open the first time.

Logs: `~/Library/Logs/Vocal Remover/worker.log`

## Credits

Separation runs on [mlx-audio-separator](https://github.com/ssmall256/mlx-audio-separator),
an MLX port of [python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator).
The models belong to their authors (jarredou, viperx, KimberleyJSN, ZFTurbo, aufr33,
anvuew). They're downloaded from the original sources, not redistributed here.
