"""Read PyTorch .ckpt/.pth files into numpy arrays without PyTorch.

A modern torch checkpoint is a zip: `<name>/data.pkl` describes the objects
and `<name>/data/<key>` holds each tensor's raw bytes. We unpickle data.pkl
with a restricted Unpickler that only rebuilds tensors and plain containers.
Any other class named in the file becomes an inert placeholder, so nothing in
the checkpoint can run code -- stricter than torch.load itself.
"""
import pickle
import zipfile

import numpy as np

_DTYPES = {
    "FloatStorage": np.float32,
    "DoubleStorage": np.float64,
    "HalfStorage": np.float16,
    "BFloat16Storage": "bfloat16",
    "LongStorage": np.int64,
    "IntStorage": np.int32,
    "ShortStorage": np.int16,
    "CharStorage": np.int8,
    "ByteStorage": np.uint8,
    "BoolStorage": np.bool_,
}


class _StorageType:
    def __init__(self, name):
        self.name = name


class _Inert:
    """Stands in for any class we don't trust. Accepts anything, does nothing."""

    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return _Inert()

    def __setstate__(self, state):
        pass


def _rebuild_tensor(storage, offset, size, stride, *_rest):
    data, itemsize = storage
    if not size:
        return data[offset:offset + 1].reshape(()).copy()
    view = np.lib.stride_tricks.as_strided(
        data[offset:], shape=tuple(size), strides=tuple(s * itemsize for s in stride)
    )
    return np.ascontiguousarray(view)


def _rebuild_parameter(data, *_rest):
    return data


class _Unpickler(pickle.Unpickler):
    def __init__(self, fh, archive, prefix):
        super().__init__(fh)
        self.archive = archive
        self.prefix = prefix
        self.cache = {}

    def find_class(self, module, name):
        if module == "collections" and name == "OrderedDict":
            import collections

            return collections.OrderedDict
        if module == "torch._utils" and name in ("_rebuild_tensor_v2", "_rebuild_tensor"):
            return _rebuild_tensor
        if module == "torch._utils" and name == "_rebuild_parameter":
            return _rebuild_parameter
        if module == "torch" and name in _DTYPES:
            return _StorageType(name)
        return _Inert

    def persistent_load(self, pid):
        # ('storage', storage_type, key, location, numel)
        _, stype, key, _location, _numel = pid
        if key not in self.cache:
            name = stype.name if isinstance(stype, _StorageType) else "FloatStorage"
            raw = self.archive.read(f"{self.prefix}/data/{key}" if self.prefix else f"data/{key}")
            dtype = _DTYPES.get(name, np.float32)
            if dtype == "bfloat16":
                # bf16 is the top half of a float32
                u16 = np.frombuffer(raw, dtype=np.uint16)
                arr = (u16.astype(np.uint32) << 16).view(np.float32)
            else:
                arr = np.frombuffer(raw, dtype=dtype)
            self.cache[key] = (arr, arr.itemsize)
        return self.cache[key]


def load_state_dict(path):
    """Return the checkpoint's state dict as {name: np.ndarray}."""
    if not zipfile.is_zipfile(path):
        raise ValueError(f"{path} is not a zip-format PyTorch checkpoint")
    with zipfile.ZipFile(path) as archive:
        pkl = next(n for n in archive.namelist() if n.endswith("/data.pkl") or n == "data.pkl")
        prefix = pkl.rsplit("/", 1)[0] if "/" in pkl else ""
        with archive.open(pkl) as fh:
            obj = _Unpickler(fh, archive, prefix).load()

    if isinstance(obj, dict):
        for key in ("state_dict", "model"):
            if isinstance(obj.get(key), dict):
                obj = obj[key]
                break
    return {k: v for k, v in obj.items() if isinstance(v, np.ndarray)}


def install():
    """Make mlx-audio-separator use this reader instead of torch.load."""
    from mlx_audio_separator.separator.models.roformer import loader

    loader._load_state_dict = load_state_dict
