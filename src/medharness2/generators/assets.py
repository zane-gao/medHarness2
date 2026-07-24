from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import pickletools
from pathlib import Path
from typing import Any
import zipfile


_IMAGE_SUFFIXES = (
    ".bmp",
    ".dcm",
    ".dicom",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
)
_VOLUME_SUFFIXES = (".nii", ".nii.gz", ".npy", ".npz")
_FEATURE_SUFFIXES = (".h5", ".hdf5", ".pt", ".pth")
_EXTERNAL_IMAGE_SUFFIXES = (".gif", ".jpeg", ".jpg", ".png", ".webp")


@dataclass(frozen=True)
class ImageAsset:
    path: str
    kind: str
    capability: str = "image_2d"
    sha256: str = ""
    size_bytes: int = 0


def looks_like_volume(path: str) -> bool:
    return str(path).lower().endswith(_VOLUME_SUFFIXES)


def looks_like_2d_image(path: str) -> bool:
    candidate = Path(path).expanduser()
    return str(candidate).lower().endswith(_IMAGE_SUFFIXES) or _has_dicom_preamble(candidate)


def looks_like_feature_embedding(path: str) -> bool:
    return str(path).lower().endswith(_FEATURE_SUFFIXES)


def is_existing_nonempty_file(path: str) -> bool:
    candidate = Path(path).expanduser()
    try:
        return candidate.is_file() and candidate.stat().st_size > 0
    except OSError:
        return False


def is_external_image_asset(path: str) -> bool:
    return str(path).lower().endswith(_EXTERNAL_IMAGE_SUFFIXES) and is_valid_2d_image(path)


def select_2d_image_asset(
    image_path: str | None,
    prepared_assets: dict[str, Any] | None,
) -> ImageAsset | None:
    assets = prepared_assets if isinstance(prepared_assets, dict) else {}
    for key in ("contact_sheet", "primary_image"):
        path = _asset_path(assets.get(key))
        if path and is_external_image_asset(path):
            return _image_asset(path, key, "image_2d")
    candidate = _asset_path(image_path)
    if candidate and is_external_image_asset(candidate):
        return _image_asset(candidate, "input_image", "image_2d")
    return None


def select_input_asset(
    image_path: str | None,
    prepared_assets: dict[str, Any] | None,
    input_capabilities: list[str] | tuple[str, ...] | set[str] | None,
) -> ImageAsset | None:
    assets = prepared_assets if isinstance(prepared_assets, dict) else {}
    required = {str(item) for item in input_capabilities or [] if str(item)}
    capability_order = [
        capability
        for capability in ("image_2d", "volume", "feature_embedding")
        if not required or capability in required
    ]
    candidates = {
        "image_2d": (
            ("contact_sheet", _asset_path(assets.get("contact_sheet"))),
            ("primary_image", _asset_path(assets.get("primary_image"))),
            ("input_image", _asset_path(image_path)),
        ),
        "volume": (
            ("volume_path", _asset_path(assets.get("volume_path"))),
            ("input_volume", _asset_path(image_path)),
        ),
        "feature_embedding": (
            ("feature_path", _asset_path(assets.get("feature_path"))),
            ("wsi_feature_path", _asset_path(assets.get("wsi_feature_path"))),
            ("h5_feature_path", _asset_path(assets.get("h5_feature_path"))),
            ("histgen_feature_path", _asset_path(assets.get("histgen_feature_path"))),
            ("input_feature", _asset_path(image_path)),
        ),
    }
    validators = {
        "image_2d": is_valid_2d_image,
        "volume": is_valid_volume_asset,
        "feature_embedding": is_valid_feature_asset,
    }
    for capability in capability_order:
        for kind, path in candidates[capability]:
            if path and validators[capability](path):
                return _image_asset(path, kind, capability)
    return None


def available_input_capabilities(
    image_path: str | None,
    prepared_assets: dict[str, Any] | None,
) -> set[str] | None:
    if image_path is None and not prepared_assets:
        return None
    assets = prepared_assets if isinstance(prepared_assets, dict) else {}
    available: set[str] = set()
    paths = (
        _asset_path(assets.get("volume_path")),
        _asset_path(assets.get("contact_sheet")),
        _asset_path(assets.get("primary_image")),
        _asset_path(assets.get("feature_path")),
        _asset_path(assets.get("wsi_feature_path")),
        _asset_path(assets.get("h5_feature_path")),
        _asset_path(assets.get("histgen_feature_path")),
        _asset_path(image_path),
    )
    for path in paths:
        if not path:
            continue
        if is_valid_volume_asset(path):
            available.add("volume")
        elif is_valid_feature_asset(path):
            available.add("feature_embedding")
        elif is_valid_2d_image(path):
            available.add("image_2d")
    return available


def is_valid_2d_image(path: str) -> bool:
    candidate = Path(path).expanduser()
    if not is_existing_nonempty_file(str(candidate)) or not looks_like_2d_image(str(candidate)):
        return False
    return _validate_asset_cached(*_asset_cache_key(candidate), "image_2d")


def is_valid_volume_asset(path: str) -> bool:
    candidate = Path(path).expanduser()
    if not is_existing_nonempty_file(str(candidate)) or not looks_like_volume(str(candidate)):
        return False
    return _validate_asset_cached(*_asset_cache_key(candidate), "volume")


def is_valid_feature_asset(path: str) -> bool:
    candidate = Path(path).expanduser()
    if not is_existing_nonempty_file(str(candidate)) or not looks_like_feature_embedding(str(candidate)):
        return False
    return _validate_asset_cached(*_asset_cache_key(candidate), "feature_embedding")


def _asset_cache_key(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=512)
def _validate_asset_cached(
    path: str,
    mtime_ns: int,
    size_bytes: int,
    capability: str,
) -> bool:
    del mtime_ns, size_bytes
    if capability == "image_2d":
        return _decode_2d_image(Path(path))
    if capability == "volume":
        return _decode_volume(Path(path))
    if capability == "feature_embedding":
        return _validate_feature_signature(Path(path))
    return False


def _decode_2d_image(path: Path) -> bool:
    suffix = path.suffix.lower()
    try:
        if suffix in {".dcm", ".dicom"} or _has_dicom_preamble(path):
            import pydicom

            dataset = pydicom.dcmread(path, stop_before_pixels=False, force=True)
            rows = int(getattr(dataset, "Rows", 0) or 0)
            columns = int(getattr(dataset, "Columns", 0) or 0)
            has_pixels = any(
                field in dataset
                for field in ("PixelData", "FloatPixelData", "DoubleFloatPixelData")
            )
            if rows <= 0 or columns <= 0 or not has_pixels:
                return False
            pixels = dataset.pixel_array
            shape = tuple(int(value) for value in getattr(pixels, "shape", ()))
            dimensions_match = shape[-2:] == (rows, columns) or (
                len(shape) >= 3 and shape[-3:-1] == (rows, columns)
            )
            return int(getattr(pixels, "size", 0) or 0) > 0 and dimensions_match
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
            image.load()
        return width > 0 and height > 0
    except (ImportError, OSError, ValueError, TypeError, SyntaxError):
        return False
    except Exception:
        return False


def _has_dicom_preamble(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            stream.seek(128)
            return stream.read(4) == b"DICM"
    except OSError:
        return False


def _decode_volume(path: Path) -> bool:
    lower = str(path).lower()
    try:
        if lower.endswith(".npy"):
            import numpy as np

            array = np.load(path, mmap_mode="r", allow_pickle=False)
            return array.ndim >= 3 and array.size > 0
        if lower.endswith(".npz"):
            import numpy as np

            with np.load(path, allow_pickle=False) as archive:
                if not archive.files:
                    return False
                has_volume = False
                for key in archive.files:
                    array = archive[key]
                    if array.ndim >= 3 and array.size > 0:
                        has_volume = True
                return has_volume
        import SimpleITK as sitk

        image = sitk.ReadImage(str(path))
        size = image.GetSize()
        return image.GetDimension() >= 3 and bool(size) and all(int(value) > 0 for value in size)
    except (ImportError, OSError, ValueError, TypeError):
        return False
    except Exception:
        return False


def _validate_feature_signature(path: Path) -> bool:
    lower = str(path).lower()
    if lower.endswith((".h5", ".hdf5")):
        return _validate_hdf5_container(path)
    if lower.endswith((".pt", ".pth")):
        return _validate_torch_container(path)
    return False


def _validate_hdf5_container(path: Path) -> bool:
    try:
        import h5py

        has_dataset = False
        with h5py.File(path, "r") as handle:
            def inspect(_name: str, value: Any) -> None:
                nonlocal has_dataset
                if has_dataset or not isinstance(value, h5py.Dataset) or int(value.size) <= 0:
                    return
                index = tuple(0 for _ in value.shape) if value.shape else ()
                value[index]
                has_dataset = True

            handle.visititems(inspect)
        return has_dataset
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _validate_torch_container(path: Path) -> bool:
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None:
                    return False
                data_pickle = next(
                    (name for name in archive.namelist() if name == "data.pkl" or name.endswith("/data.pkl")),
                    None,
                )
                return bool(data_pickle and _is_complete_pickle(archive.read(data_pickle)))
        return _is_complete_pickle(path.read_bytes())
    except (OSError, RuntimeError, TypeError, ValueError, zipfile.BadZipFile):
        return False


def _is_complete_pickle(payload: bytes) -> bool:
    if not payload:
        return False
    try:
        operations = list(pickletools.genops(payload))
    except (IndexError, ValueError):
        return False
    return bool(operations and operations[-1][0].name == "STOP")


def _image_asset(path: str, kind: str, capability: str) -> ImageAsset:
    candidate = Path(path).expanduser()
    stat = candidate.stat()
    return ImageAsset(
        path=str(candidate),
        kind=kind,
        capability=capability,
        sha256=_asset_sha256_cached(str(candidate.resolve()), stat.st_mtime_ns, stat.st_size),
        size_bytes=stat.st_size,
    )


@lru_cache(maxsize=512)
def _asset_sha256_cached(path: str, mtime_ns: int, size_bytes: int) -> str:
    del mtime_ns, size_bytes
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_path(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = [
    "ImageAsset",
    "available_input_capabilities",
    "is_existing_nonempty_file",
    "is_external_image_asset",
    "is_valid_2d_image",
    "is_valid_feature_asset",
    "is_valid_volume_asset",
    "looks_like_2d_image",
    "looks_like_feature_embedding",
    "looks_like_volume",
    "select_2d_image_asset",
    "select_input_asset",
]
