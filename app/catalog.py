"""Models bundled with Vocal Remover. Shared by the build scripts and the app."""

MODELS = [
    {
        "id": "BS-Roformer-SW.ckpt",
        "mb": 699,
        "name": "BS-Roformer SW",
        "author": "jarredou",
        "tagline": "6 stems: vocals, drums, bass, guitar, piano, other",
        "kind": "stems",
        "stems": ["Vocals", "Drums", "Bass", "Guitar", "Piano", "Other"],
        "speed": 2,
        "quality": 5,
        "default": False,
    },
    {
        "id": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        "mb": 639,
        "name": "BS-Roformer Viperx 1297",
        "author": "viperx",
        "tagline": "Best instrumental. Vocals + instrumental",
        "kind": "vocals",
        "stems": ["Vocals", "Instrumental"],
        "speed": 3,
        "quality": 5,
        "default": True,
    },
    {
        "id": "vocals_mel_band_roformer.ckpt",
        "mb": 913,
        "name": "Mel-Roformer Kim",
        "author": "KimberleyJSN",
        "tagline": "Cleanest vocals. Vocals + instrumental",
        "kind": "vocals",
        "stems": ["Vocals", "Instrumental"],
        "speed": 3,
        "quality": 5,
        "default": False,
    },
    {
        "id": "mel-roformer-zfturbo-vocals-v1-mlx",
        "mb": 67,
        "name": "Mel-Roformer Lite",
        "author": "ZFTurbo",
        "tagline": "Small and fast. Vocals + instrumental",
        "kind": "vocals",
        "stems": ["Vocals", "Instrumental"],
        "speed": 5,
        "quality": 3,
        "default": False,
    },
]

# Post-processing steps that run on the Vocals stem after the main model.
TOOLS = [
    {
        "id": "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt",
        "mb": 913,
        "key": "karaoke",
        "name": "Split lead & backing vocals",
        "author": "aufr33 & viperx",
        # model stem -> our stem name
        "stems": {"vocals": "Lead Vocals", "instrumental": "Backing Vocals"},
    },
    {
        "id": "dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt",
        "mb": 913,
        "key": "dereverb",
        "name": "Remove reverb from vocals",
        "author": "anvuew",
        "stems": {"noreverb": "Dry", "reverb": "Reverb"},
    },
]

ALL = MODELS + TOOLS


def marker(model_dir, model):
    """Written after a model is downloaded and converted. A partial download
    or an interrupted conversion never leaves one behind."""
    from pathlib import Path

    return Path(model_dir) / f"{model['id']}.installed"


def is_installed(model_dir, model):
    return marker(model_dir, model).exists()
