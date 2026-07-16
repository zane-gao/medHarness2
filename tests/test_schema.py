
from __future__ import annotations

import pytest

from medharness2.schema import CaseManifest


@pytest.mark.parametrize("field", ["image_paths", "warnings"])
@pytest.mark.parametrize("bad", ["/tmp/file", {"x": 1}, ["ok", 2]])
def test_case_manifest_rejects_non_string_lists(field, bad):
    payload = {"case_id": "case-1", field: bad}
    with pytest.raises(ValueError, match=field):
        CaseManifest.from_json(payload)


def test_case_manifest_preserves_string_lists():
    manifest = CaseManifest.from_json(
        {"case_id": "case-1", "image_paths": ["a.dcm"], "warnings": ["warning"]}
    )
    assert manifest.image_paths == ["a.dcm"]
    assert manifest.warnings == ["warning"]
