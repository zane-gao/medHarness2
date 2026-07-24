from __future__ import annotations

import io
import pickle
from pathlib import Path
import zipfile

import numpy as np
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from medharness2.generators.assets import (
    is_valid_2d_image,
    is_valid_feature_asset,
    is_valid_volume_asset,
)


HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"


def _write_minimal_dicom(path: Path, *, pixel_data: bytes | None = None) -> None:
    sop_instance_uid = generate_uid()
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()

    dataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = SecondaryCaptureImageStorage
    dataset.SOPInstanceUID = sop_instance_uid
    dataset.Modality = "OT"
    dataset.Rows = 2
    dataset.Columns = 2
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 8
    dataset.BitsStored = 8
    dataset.HighBit = 7
    dataset.PixelRepresentation = 0
    dataset.PixelData = pixel_data if pixel_data is not None else np.arange(4, dtype=np.uint8).tobytes()
    dataset.save_as(path, enforce_file_format=True)


def _write_npy_volume(path: Path) -> None:
    np.save(path, np.arange(24, dtype=np.float32).reshape(2, 3, 4))


def _write_npz_volume(path: Path) -> None:
    np.savez(path, volume=np.arange(24, dtype=np.int16).reshape(2, 3, 4))


def _write_nifti(path: Path, *, dimensions: int = 3) -> None:
    sitk = pytest.importorskip("SimpleITK", reason="SimpleITK is required for NIfTI tests")
    shape = (2,) * dimensions
    image = sitk.GetImageFromArray(np.arange(2**dimensions, dtype=np.int16).reshape(shape))
    sitk.WriteImage(image, str(path))


def _write_truncated_copy(source: Path, destination: Path, *, keep_bytes: int) -> None:
    payload = source.read_bytes()
    assert len(payload) > keep_bytes
    destination.write_bytes(payload[:keep_bytes])


def test_valid_dicom_is_accepted_as_2d_image(tmp_path: Path) -> None:
    path = tmp_path / "image.dcm"
    _write_minimal_dicom(path)

    assert path.read_bytes()[128:132] == b"DICM"
    assert is_valid_2d_image(str(path))


def test_truncated_dicom_is_rejected(tmp_path: Path) -> None:
    valid_path = tmp_path / "valid.dcm"
    corrupt_path = tmp_path / "corrupt.dcm"
    _write_minimal_dicom(valid_path)
    _write_truncated_copy(valid_path, corrupt_path, keep_bytes=132)

    assert corrupt_path.read_bytes()[128:132] == b"DICM"
    assert not is_valid_2d_image(str(corrupt_path))


def test_dicom_with_truncated_pixel_payload_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "short-pixels.dcm"
    _write_minimal_dicom(path, pixel_data=b"\x00")

    assert not is_valid_2d_image(str(path))


def test_extensionless_dicom_is_accepted_as_2d_image(tmp_path: Path) -> None:
    path = tmp_path / "Y1"
    _write_minimal_dicom(path)

    assert path.suffix == ""
    assert path.read_bytes()[128:132] == b"DICM"
    assert is_valid_2d_image(str(path))


def test_extensionless_text_is_rejected_as_2d_image(tmp_path: Path) -> None:
    path = tmp_path / "notes"
    path.write_text("not a medical image", encoding="utf-8")

    assert path.suffix == ""
    assert not is_valid_2d_image(str(path))


def test_valid_npy_volume_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "volume.npy"
    _write_npy_volume(path)

    assert is_valid_volume_asset(str(path))


def test_two_dimensional_npy_is_rejected_as_volume(tmp_path: Path) -> None:
    path = tmp_path / "matrix.npy"
    np.save(path, np.ones((2, 3), dtype=np.float32))

    assert not is_valid_volume_asset(str(path))


def test_truncated_npy_volume_is_rejected(tmp_path: Path) -> None:
    valid_path = tmp_path / "valid.npy"
    corrupt_path = tmp_path / "corrupt.npy"
    _write_npy_volume(valid_path)
    _write_truncated_copy(valid_path, corrupt_path, keep_bytes=valid_path.stat().st_size - 1)

    assert not is_valid_volume_asset(str(corrupt_path))


def test_valid_npz_volume_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "volume.npz"
    _write_npz_volume(path)

    assert is_valid_volume_asset(str(path))


def test_npz_without_three_dimensional_array_is_rejected_as_volume(tmp_path: Path) -> None:
    path = tmp_path / "matrices.npz"
    np.savez(path, first=np.ones((2, 3)), second=np.arange(4))

    assert not is_valid_volume_asset(str(path))


def test_truncated_npz_volume_is_rejected(tmp_path: Path) -> None:
    valid_path = tmp_path / "valid.npz"
    corrupt_path = tmp_path / "corrupt.npz"
    _write_npz_volume(valid_path)
    _write_truncated_copy(valid_path, corrupt_path, keep_bytes=valid_path.stat().st_size - 22)

    assert not is_valid_volume_asset(str(corrupt_path))


def test_npz_with_valid_volume_and_corrupt_member_is_rejected(tmp_path: Path) -> None:
    valid_member = io.BytesIO()
    np.save(valid_member, np.arange(24, dtype=np.int16).reshape(2, 3, 4))
    path = tmp_path / "partially-corrupt.npz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("valid.npy", valid_member.getvalue())
        archive.writestr("broken.npy", b"not-a-numpy-array")

    assert not is_valid_volume_asset(str(path))


def test_valid_nifti_volume_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "volume.nii.gz"
    _write_nifti(path)

    assert is_valid_volume_asset(str(path))


def test_two_dimensional_nifti_is_rejected_as_volume(tmp_path: Path) -> None:
    path = tmp_path / "slice.nii.gz"
    _write_nifti(path, dimensions=2)

    assert not is_valid_volume_asset(str(path))


def test_truncated_nifti_volume_is_rejected(tmp_path: Path) -> None:
    valid_path = tmp_path / "valid.nii.gz"
    corrupt_path = tmp_path / "corrupt.nii.gz"
    _write_nifti(valid_path)
    _write_truncated_copy(valid_path, corrupt_path, keep_bytes=16)

    assert not is_valid_volume_asset(str(corrupt_path))


@pytest.mark.parametrize("suffix", [".h5", ".hdf5"])
def test_valid_hdf5_feature_dataset_is_accepted(tmp_path: Path, suffix: str) -> None:
    h5py = pytest.importorskip("h5py", reason="h5py is required for HDF5 validation")
    path = tmp_path / f"features{suffix}"
    with h5py.File(path, "w") as handle:
        handle.create_dataset("features", data=np.arange(12, dtype=np.float32).reshape(3, 4))

    assert is_valid_feature_asset(str(path))


@pytest.mark.parametrize("suffix", [".h5", ".hdf5"])
def test_corrupt_hdf5_signature_is_rejected(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"features{suffix}"
    path.write_bytes(b"\x89HDF\r\n\x1aX")

    assert not is_valid_feature_asset(str(path))


@pytest.mark.parametrize("suffix", [".h5", ".hdf5"])
def test_header_only_hdf5_file_is_rejected(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"truncated{suffix}"
    path.write_bytes(HDF5_SIGNATURE)

    assert not is_valid_feature_asset(str(path))


@pytest.mark.parametrize(
    ("suffix", "container"),
    [(".pt", "zip"), (".pth", "pickle")],
    ids=["zip-pt", "pickle-pth"],
)
def test_valid_torch_serialization_container_is_accepted(
    tmp_path: Path,
    suffix: str,
    container: str,
) -> None:
    path = tmp_path / f"features{suffix}"
    payload = pickle.dumps({"features": [1.0, 2.0]}, protocol=4)
    if container == "zip":
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("archive/data.pkl", payload)
            archive.writestr("archive/version", "3\n")
    else:
        path.write_bytes(payload)

    assert is_valid_feature_asset(str(path))


@pytest.mark.parametrize("suffix", [".pt", ".pth"])
def test_corrupt_torch_signature_is_rejected(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"features{suffix}"
    path.write_bytes(b"not-a-torch-feature")

    assert not is_valid_feature_asset(str(path))


@pytest.mark.parametrize("suffix,header", [(".pt", b"PK\x03\x04"), (".pth", b"\x80\x04")])
def test_header_only_torch_file_is_rejected(tmp_path: Path, suffix: str, header: bytes) -> None:
    path = tmp_path / f"truncated{suffix}"
    path.write_bytes(header)

    assert not is_valid_feature_asset(str(path))
