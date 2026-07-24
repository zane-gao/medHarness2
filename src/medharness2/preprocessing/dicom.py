from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from medharness2.modality import normalize_modality
from medharness2.schema import CaseManifest, PreparedCase


def prepare_case_assets(case_manifest: CaseManifest | dict[str, Any], output_dir: str | Path) -> PreparedCase:
    case = case_manifest if isinstance(case_manifest, CaseManifest) else CaseManifest.from_json(case_manifest)
    modality = normalize_modality(case.modality)
    out_dir = Path(output_dir) / case.case_id
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    if modality == "cxr":
        pngs = _convert_single_images(case.image_paths, out_dir / "images", warnings)
        derived = {"png_images": pngs}
        if pngs:
            derived["primary_image"] = pngs[0]
        return PreparedCase(
            case_id=case.case_id,
            modality=modality,
            body_part=case.body_part,
            image_paths=pngs or case.image_paths,
            volume_path=None,
            derived_assets=derived,
            warnings=warnings,
        )

    groups = _group_series(case.image_paths) if case.image_paths else {}
    selected, selection = _select_series(groups, modality, case.body_part)
    if not selected and case.image_paths:
        selected = case.image_paths
    volume_path = _write_series_volume(selected, out_dir / "volume.nii.gz", warnings) if selected else None
    provided_volume = str(case.volume_path or "")
    if not volume_path and provided_volume:
        if Path(provided_volume).is_file():
            volume_path = provided_volume
        else:
            warnings.append("volume_path_missing")
    contact_sheet = _write_contact_sheet(selected, out_dir / "contact_sheet.png", warnings) if selected else None
    contact_sheet_source = "dicom_series" if contact_sheet else ""
    if not contact_sheet and volume_path:
        contact_sheet = _write_volume_contact_sheet(volume_path, out_dir / "contact_sheet.png", warnings)
        contact_sheet_source = "volume" if contact_sheet else ""
    derived = {"series_count": len(groups), **selection}
    if contact_sheet:
        derived["contact_sheet"] = contact_sheet
        derived["primary_image"] = contact_sheet
        derived["contact_sheet_source"] = contact_sheet_source
    if volume_path:
        derived["volume_path"] = volume_path
    return PreparedCase(
        case_id=case.case_id,
        modality=modality,
        body_part=case.body_part,
        image_paths=[contact_sheet] if contact_sheet else case.image_paths,
        volume_path=volume_path,
        derived_assets=derived,
        warnings=warnings,
    )


def _convert_single_images(image_paths: list[str], output_dir: Path, warnings: list[str]) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pngs: list[str] = []
    for idx, image_path in enumerate(image_paths, start=1):
        arr = _read_dicom_array(image_path, warnings)
        if arr is None:
            continue
        if arr.ndim == 3:
            arr = arr[0]
        out = output_dir / f"image_{idx:02d}.png"
        Image.fromarray(_normalize_uint8(arr)).convert("L").save(out)
        pngs.append(str(out))
    if image_paths and not pngs:
        warnings.append("dicom_png_conversion_failed")
    return pngs


def _group_series(image_paths: list[str]) -> dict[str, list[str]]:
    try:
        import pydicom
    except Exception:
        return {"unknown": image_paths}
    groups: dict[str, list[str]] = defaultdict(list)
    for path in image_paths:
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True, force=True, specific_tags=["SeriesInstanceUID", "Rows", "Columns", "InstanceNumber"])
            key = f"{getattr(ds, 'SeriesInstanceUID', 'unknown')}:{getattr(ds, 'Rows', '')}x{getattr(ds, 'Columns', '')}"
        except Exception:
            key = "unknown"
        groups[key].append(path)
    return {key: _sort_by_instance(paths) for key, paths in groups.items()}


def _select_series(groups: dict[str, list[str]], modality: str, body_part: str | None) -> tuple[list[str], dict[str, Any]]:
    modality = normalize_modality(modality)
    if not groups:
        return [], {}
    ranked = [
        (key, paths, _series_metadata(paths[0]) if paths else {})
        for key, paths in groups.items()
    ]
    selected_key, selected_paths, selected_meta = max(ranked, key=lambda item: len(item[1]))
    reason = "largest_series"
    selected_type = "largest"
    if modality == "mri" and (body_part or "").lower() == "brain":
        flair_candidates = [
            (key, paths, meta, _brain_mri_series_score(meta))
            for key, paths, meta in ranked
            if _brain_mri_series_score(meta) > 0
        ]
        if flair_candidates:
            selected_key, selected_paths, selected_meta, _score = max(
                flair_candidates,
                key=lambda item: (item[3], len(item[1])),
            )
            selected_type = _brain_mri_series_type(selected_meta)
            reason = f"brain_mri_{selected_type}_preferred"
    selection = {
        "selected_series_key": selected_key,
        "selected_series_count": len(selected_paths),
        "series_selection_reason": reason,
        "selected_series_type": selected_type,
    }
    description = selected_meta.get("series_description")
    if description:
        selection["selected_series_description"] = description
    return selected_paths, selection


def _series_metadata(path: str) -> dict[str, str]:
    try:
        import pydicom

        ds = pydicom.dcmread(
            path,
            stop_before_pixels=True,
            force=True,
            specific_tags=["SeriesDescription", "ProtocolName", "SequenceName"],
        )
    except Exception:
        return {}
    return {
        "series_description": str(getattr(ds, "SeriesDescription", "") or ""),
        "protocol_name": str(getattr(ds, "ProtocolName", "") or ""),
        "sequence_name": str(getattr(ds, "SequenceName", "") or ""),
    }


def _brain_mri_series_score(metadata: dict[str, str]) -> int:
    series_type = _brain_mri_series_type(metadata)
    if series_type == "flair":
        return 100
    if series_type == "t2":
        return 20
    return 0


def _brain_mri_series_type(metadata: dict[str, str]) -> str:
    text = " ".join(metadata.values()).lower()
    if "flair" in text:
        return "flair"
    if "t2" in text:
        return "t2"
    return ""


def _sort_by_instance(paths: list[str]) -> list[str]:
    try:
        import pydicom
    except Exception:
        return sorted(paths)

    def key(path: str) -> tuple[int, str]:
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True, force=True, specific_tags=["InstanceNumber"])
            return int(getattr(ds, "InstanceNumber", 0) or 0), path
        except Exception:
            return 0, path

    return sorted(paths, key=key)


def _write_series_volume(image_paths: list[str], output_path: Path, warnings: list[str]) -> str | None:
    if not image_paths:
        return None
    try:
        import SimpleITK as sitk

        reader = sitk.ImageSeriesReader()
        reader.SetFileNames(image_paths)
        image = reader.Execute()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sitk.WriteImage(image, str(output_path))
        return str(output_path)
    except Exception as exc:
        warnings.append(f"dicom_series_to_nifti_failed:{type(exc).__name__}")
        return None


def _write_contact_sheet(image_paths: list[str], output_path: Path, warnings: list[str], *, num_slices: int = 9) -> str | None:
    if not image_paths:
        return None
    arrays: list[tuple[int, np.ndarray]] = []
    indices = np.linspace(0, len(image_paths) - 1, min(num_slices, len(image_paths))).astype(int)
    for index in indices:
        arr = _read_dicom_array(image_paths[int(index)], warnings)
        if arr is None:
            continue
        arrays.append((int(index), np.squeeze(arr)))
    if not arrays:
        warnings.append("contact_sheet_failed")
        return None
    return _write_array_contact_sheet(arrays, output_path)


def _write_volume_contact_sheet(
    volume_path: str,
    output_path: Path,
    warnings: list[str],
    *,
    num_slices: int = 9,
) -> str | None:
    volume = _read_volume_array(volume_path, warnings)
    if volume is None:
        return None
    array = np.squeeze(np.asarray(volume))
    while array.ndim > 3:
        array = array[0]
    if array.ndim == 2:
        array = array[np.newaxis, ...]
    if array.ndim != 3 or array.shape[0] == 0:
        warnings.append("volume_contact_sheet_invalid_shape")
        return None
    indices = np.linspace(0, array.shape[0] - 1, min(num_slices, array.shape[0])).astype(int)
    return _write_array_contact_sheet(
        [(int(index), np.asarray(array[int(index)])) for index in indices],
        output_path,
    )


def _write_array_contact_sheet(
    indexed_arrays: list[tuple[int, np.ndarray]],
    output_path: Path,
) -> str:
    tiles = [(index, _normalize_uint8(array)) for index, array in indexed_arrays]
    tile_h, tile_w = tiles[0][1].shape[-2], tiles[0][1].shape[-1]
    cols = int(np.ceil(np.sqrt(len(tiles))))
    rows = int(np.ceil(len(tiles) / cols))
    canvas = Image.new("RGB", (cols * tile_w, rows * tile_h), "black")
    draw = ImageDraw.Draw(canvas)
    for idx, (slice_index, tile) in enumerate(tiles):
        image = Image.fromarray(tile).convert("RGB")
        x = (idx % cols) * tile_w
        y = (idx // cols) * tile_h
        canvas.paste(image, (x, y))
        draw.text((x + 4, y + 4), str(slice_index), fill=(255, 255, 0))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return str(output_path)


def _read_volume_array(volume_path: str, warnings: list[str]) -> np.ndarray | None:
    path = Path(volume_path)
    try:
        if path.suffix.lower() == ".npy":
            return np.asarray(np.load(path, allow_pickle=False))
        if path.suffix.lower() == ".npz":
            with np.load(path, allow_pickle=False) as archive:
                if not archive.files:
                    raise ValueError("empty npz archive")
                return np.asarray(archive[archive.files[0]])
        import SimpleITK as sitk

        return sitk.GetArrayFromImage(sitk.ReadImage(str(path)))
    except Exception as exc:
        warnings.append(f"volume_preview_read_failed:{path.name}:{type(exc).__name__}")
        return None


def _read_dicom_array(image_path: str, warnings: list[str]) -> np.ndarray | None:
    try:
        import SimpleITK as sitk

        image = sitk.ReadImage(str(image_path))
        return sitk.GetArrayFromImage(image)
    except Exception as exc:
        warnings.append(f"dicom_read_failed:{Path(image_path).name}:{type(exc).__name__}")
        return None


def _normalize_uint8(arr: np.ndarray) -> np.ndarray:
    tile = np.squeeze(np.asarray(arr, dtype=np.float32))
    if tile.ndim != 2:
        tile = tile.reshape(tile.shape[-2], tile.shape[-1])
    lo, hi = np.percentile(tile, [1, 99])
    if hi <= lo:
        lo = float(tile.min())
        hi = float(tile.max() or 1.0)
    return (np.clip((tile - lo) / max(hi - lo, 1e-6), 0, 1) * 255).astype(np.uint8)
