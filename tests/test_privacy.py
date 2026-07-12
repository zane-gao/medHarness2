from __future__ import annotations

import json

import pytest

from medharness2.config import AppConfig, LLMConfig, PrivacyConfig
from medharness2.llm_client import LLMClient
from medharness2.privacy import ExternalPayloadPolicy, PrivacyViolation


def test_privacy_scanner_detects_phi_paths_uids_and_canaries():
    policy = ExternalPayloadPolicy()
    result = policy.scan(
        "姓名：张三 住院号：26041983 path=/nfsdata_a40/private/case.dcm "
        "uid=1.2.840.113619.2.55.3.604688435.12 PATIENT_CANARY_9271"
    )

    assert result.allowed is False
    assert {finding.category for finding in result.findings} >= {
        "labeled_identifier",
        "absolute_path",
        "dicom_uid",
        "privacy_canary",
    }


def test_privacy_policy_allows_minimal_structured_hazard_payload():
    policy = ExternalPayloadPolicy()
    payload = policy.sanitize_hazard_candidates(
        [
            {
                "error_type": "omission_finding",
                "observation": "pulmonary nodule",
                "location": "right upper lobe",
                "measurement": "8 mm",
                "text": "姓名：张三",
                "source_path": "/private/case.dcm",
            }
        ]
    )

    assert payload == [
        {
            "error_type": "omission_finding",
            "observation": "pulmonary nodule",
            "location": "right upper lobe",
            "measurement": "8 mm",
        }
    ]
    assert policy.scan(json.dumps(payload)).allowed is True


def test_llm_client_blocks_unclassified_external_payload_before_network(monkeypatch):
    monkeypatch.setenv("DMX_API_KEY", "test-key")
    called = False

    def fail_post(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network should not be called")

    monkeypatch.setattr("requests.post", fail_post)
    client = LLMClient(
        AppConfig(
            llm=LLMConfig(provider="chat_completions", api_key_env="DMX_API_KEY"),
            privacy=PrivacyConfig(enforce_external=True),
        )
    )

    with pytest.raises(PrivacyViolation):
        client.call("Return JSON for this report: patient has a nodule.")

    assert called is False


def test_llm_client_blocks_external_images_even_when_classified(monkeypatch, tmp_path):
    monkeypatch.setenv("DMX_API_KEY", "test-key")
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    client = LLMClient(
        AppConfig(
            llm=LLMConfig(provider="chat_completions", api_key_env="DMX_API_KEY"),
            privacy=PrivacyConfig(enforce_external=True, block_external_images=True),
        )
    )

    with pytest.raises(PrivacyViolation):
        client.call("Describe image", image_path=str(image), payload_classification="deidentified_structured")
