"""Separation worker. Runs in its own process so a job can be cancelled by
killing it, and so MLX memory is returned to the system when it finishes.

Reads a JSON job from argv, writes one JSON event per line to stdout.

Per song the pipeline is:
  1. main model, or two models for an ensemble (their stems are averaged)
  2. optional karaoke step on the Vocals stem -> Lead Vocals / Backing Vocals
  3. optional de-reverb step on the (lead) vocals -> "<stem> (No Reverb)"
  4. encode the kept stems to the chosen format
Intermediates are WAV files in a temp folder next to the output.
"""
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from catalog import ALL, MODELS, TOOLS, is_installed, marker

# Stem names as the main models report them -> the names we write.
STEM_NAMES = {
    "vocals": "Vocals",
    "instrumental": "Instrumental",
    "no vocals": "Instrumental",
    "drums": "Drums",
    "bass": "Bass",
    "guitar": "Guitar",
    "piano": "Piano",
    "other": "Other",
}
ORDER = ["Vocals", "Lead Vocals", "Backing Vocals", "Vocals (No Reverb)", "Lead Vocals (No Reverb)",
         "Instrumental", "Drums", "Bass", "Guitar", "Piano", "Other"]


def emit(**event):
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


class _Progress:
    """Stands in for tqdm inside the separator so we can report progress.
    Each model pass is one slice of the song's progress bar."""

    file = 0
    step = 0
    steps = 1

    def __init__(self, iterable=None, total=None, desc=None, **_):
        self.iterable = iterable
        self.total = total if total is not None else (len(iterable) if hasattr(iterable, "__len__") else None)
        self.n = 0

    def __iter__(self):
        last = 0.0
        for item in self.iterable:
            yield item
            self.n += 1
            now = time.monotonic()
            if self.total and (now - last > 0.15 or self.n == self.total):
                last = now
                frac = (_Progress.step + self.n / self.total) / _Progress.steps
                emit(type="progress", file=_Progress.file, frac=frac)

    def update(self, n=1):
        self.n += n

    def close(self):
        pass

    def set_description(self, *_a, **_k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Pipeline:
    def __init__(self, job, work):
        self.job = job
        self.work = work
        self.model_dir = job["model_dir"]
        self.loaded = {}

    def separator(self, model_id, label):
        """Load each model once per job and reuse it for every song."""
        if model_id not in self.loaded:
            emit(type="stage", stage="loading", file=_Progress.file, text=f"Loading {label}")
            from mlx_audio_separator import Separator

            sep = Separator(model_file_dir=self.model_dir, output_dir=str(self.work),
                            output_format="WAV", log_level=logging.WARNING)
            sep._set_strict_separation_errors(True)
            sep.load_model(model_id)
            self.loaded[model_id] = sep
        return self.loaded[model_id]

    def run(self, model_id, label, src, outdir, rename):
        """Separate `src` with one model. Returns {our stem name: wav path}."""
        sep = self.separator(model_id, label)
        outdir.mkdir(parents=True, exist_ok=True)
        sep.output_dir = str(outdir)
        sep.model_instance.output_dir = str(outdir)
        result = {}
        for out in sep.separate(str(src)):
            out = Path(out) if os.path.isabs(out) else outdir / out
            name = rename(stem_of(out.name))
            final = outdir / f"{name}.wav"
            shutil.move(str(out), final)
            result[name] = final
        return result


def average(paths, dest):
    """Ensemble: mean of the waveforms (UVR's 'Avg Wave')."""
    import mlx.core as mx
    import mlx_audio_io as mac

    arrays, sr = [], None
    for p in paths:
        a, sr = mac.load(str(p))
        arrays.append(a)
    n = min(a.shape[0] for a in arrays)
    mean = sum(a[:n] for a in arrays) / len(arrays)
    mac.save(str(dest), mx.clip(mean, -1.0, 1.0), sr, encoding="float32")
    return dest


def encode(src, dest, fmt):
    if fmt == "WAV":
        shutil.move(str(src), dest)
        return
    import mlx_audio_io as mac

    audio, sr = mac.load(str(src))
    if fmt == "MP3":
        mac.save(str(dest), audio, sr, bitrate="320k")
    else:
        mac.save(str(dest), audio, sr, encoding="pcm24")


def run(job):
    import mlx_audio_separator.separator.architectures.mdxc_separator as mdxc

    import ckpt_loader

    ckpt_loader.install()
    mdxc.tqdm = _Progress

    by_id = {m["id"]: m for m in MODELS}
    tools = {t["key"]: t for t in TOOLS}
    model_ids = job.get("models") or [job["model"]]
    models = [by_id[i] for i in model_ids]
    chain = [k for k in ("karaoke", "dereverb") if k in job.get("tools", [])]
    fmt = job.get("format", "WAV")
    ext = fmt.lower()
    keep = {s.lower() for s in job.get("stems", [])}
    root = Path(job["output_root"])
    work = root / ".vocal-remover-tmp"
    pipe = Pipeline(job, work)
    _Progress.steps = len(models) + len(chain)

    for i, src in enumerate(job["files"]):
        _Progress.file = i
        name = Path(src).stem
        tmp = work / f"job{i}"
        try:
            # 1. main model(s)
            passes = []
            for k, m in enumerate(models):
                _Progress.step = k
                emit(type="stage", stage="separating", file=i,
                     text=f"{m['name']}" + (f" ({k + 1}/{len(models)})" if len(models) > 1 else ""))

                def rename(stem, kind=m["kind"]):
                    stem = "instrumental" if (kind == "vocals" and stem == "other") else stem
                    return STEM_NAMES.get(stem, stem.title())

                passes.append(pipe.run(m["id"], m["name"], src, tmp / f"m{k}", rename))

            stems = dict(passes[0])
            if len(passes) > 1:
                for label in stems:
                    if all(label in p for p in passes):
                        stems[label] = average([p[label] for p in passes], tmp / f"ens_{label}.wav")

            extras = {}
            vocals = stems.get("Vocals")
            # 2. lead / backing
            if "karaoke" in chain and vocals:
                _Progress.step = len(models)
                t = tools["karaoke"]
                emit(type="stage", stage="separating", file=i, text="Splitting lead and backing vocals")
                extras.update(pipe.run(t["id"], "karaoke model", vocals, tmp / "karaoke",
                                       lambda s, t=t: t["stems"].get(s, s.title())))
            # 3. de-reverb the lead vocal if we have one, else the full vocal
            if "dereverb" in chain and vocals:
                _Progress.step = len(models) + chain.index("dereverb")
                t = tools["dereverb"]
                target = "Lead Vocals" if "Lead Vocals" in extras else "Vocals"
                emit(type="stage", stage="separating", file=i, text=f"Removing reverb from {target.lower()}")
                src_path = extras.get(target) or vocals
                res = pipe.run(t["id"], "de-reverb model", src_path, tmp / "dereverb",
                               lambda s, t=t: t["stems"].get(s, s.title()))
                if "Dry" in res:
                    extras[f"{target} (No Reverb)"] = res["Dry"]

            # 4. write what the user asked to keep, plus every extra
            dest = unique_dir(root / name)
            dest.mkdir(parents=True, exist_ok=True)
            written = []
            for label, path in list(stems.items()) + list(extras.items()):
                if label in stems and keep and label.lower() not in keep:
                    continue
                final = dest / f"{label}.{ext}"
                encode(path, final, fmt)
                written.append({"stem": label, "path": str(final)})
            written.sort(key=lambda w: ORDER.index(w["stem"]) if w["stem"] in ORDER else 99)
            emit(type="file_done", file=i, folder=str(dest), outputs=written)
        except Exception as e:  # report and move on to the next file
            emit(type="file_error", file=i, error=f"{type(e).__name__}: {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    shutil.rmtree(work, ignore_errors=True)
    emit(type="done")


class _DownloadProgress:
    """Stands in for tqdm in the separator's downloader."""

    model = None

    def __init__(self, total=0, **_):
        self.total = total or 0
        self.n = 0
        self.last = 0.0

    def update(self, n):
        self.n += n
        now = time.monotonic()
        if self.total > 5_000_000 and (now - self.last > 0.2 or self.n >= self.total):
            self.last = now
            emit(type="dl_progress", id=_DownloadProgress.model, done=self.n, total=self.total)

    def close(self):
        pass


def download(job):
    """Download and convert every catalog model that isn't installed yet.
    Checkpoints are converted to MLX .safetensors without PyTorch, then
    replaced by an empty stub to save space."""
    import mlx_audio_separator.core as core
    from mlx_audio_separator import Separator

    import ckpt_loader

    ckpt_loader.install()
    core.tqdm = _DownloadProgress
    model_dir = Path(job["model_dir"])
    model_dir.mkdir(parents=True, exist_ok=True)
    todo = [m for m in ALL if not is_installed(model_dir, m)]
    need = sum(m["mb"] for m in todo) * 1_000_000 + max((m["mb"] for m in todo), default=0) * 1_000_000
    free = shutil.disk_usage(model_dir).free
    if free < need:
        emit(type="fatal", error=f"Not enough disk space: the models need {need / 1e9:.1f} GB "
                                 f"while downloading, and {free / 1e9:.1f} GB is free.")
        sys.exit(1)

    for n, m in enumerate(todo):
        _DownloadProgress.model = m["id"]
        emit(type="dl_start", id=m["id"], index=n, count=len(todo))
        is_ckpt = m["id"].endswith((".ckpt", ".pth", ".th"))
        # names like "..._sdr_12.9755.ckpt" contain dots, so no with_suffix()
        weights = model_dir / (m["id"].rsplit(".", 1)[0] + ".safetensors")
        if is_ckpt:  # clear leftovers of an interrupted attempt
            (model_dir / m["id"]).unlink(missing_ok=True)
            weights.unlink(missing_ok=True)
        try:
            sep = Separator(model_file_dir=str(model_dir), output_dir=str(model_dir / ".tmp"),
                            save_converted_safetensors=True, log_level=logging.WARNING)
            emit(type="dl_stage", id=m["id"], text="Downloading")
            # load_model downloads, then converts while building the model
            sep.load_model(m["id"])
            if is_ckpt:
                if not weights.exists():
                    raise RuntimeError("conversion did not produce weights")
                (model_dir / m["id"]).write_bytes(b"")  # stub; weights are in .safetensors
            marker(model_dir, m).write_text("ok")
            emit(type="dl_done", id=m["id"])
        except Exception as e:
            emit(type="dl_error", id=m["id"], error=f"{type(e).__name__}: {e}")
        finally:
            shutil.rmtree(model_dir / ".tmp", ignore_errors=True)
    emit(type="done")


def stem_of(filename):
    """'song_(Vocals)_model.wav' -> 'vocals'."""
    if "_(" in filename and ")" in filename:
        return filename.rsplit("_(", 1)[1].split(")", 1)[0].lower()
    return Path(filename).stem.lower()


def unique_dir(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while (candidate := path.with_name(f"{path.name} ({n})")).exists():
        n += 1
    return candidate


def main(argv):
    job = json.loads(argv[0])
    try:
        download(job) if job.get("action") == "download" else run(job)
    except Exception as e:
        emit(type="fatal", error=f"{type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
