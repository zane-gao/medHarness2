from __future__ import annotations

import json

from medharness2.workflows.education import _report_suggestions


class _RecordingClient:
    def __init__(self):
        self.calls = []

    def call(self, prompt, image_path=None, **kwargs):
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        return json.dumps(kwargs["response_json"], ensure_ascii=False)


def test_education_external_prompt_excludes_report_text_phi_and_paths():
    client = _RecordingClient()
    payload = {
        "human_evaluation": {
            "likert": {
                "Completeness and Accuracy": {"score": 2, "explanation": "missing finding"},
                "Conciseness and Clarity": {"score": 3, "explanation": "ok"},
                "Terminological Accuracy": {"score": 3, "explanation": "ok"},
                "Structure and Style": {"score": 3, "explanation": "ok"},
                "Overall Writing Quality": {"score": 3, "explanation": "ok"},
            },
            "finding_graph": {
                "findings": [
                    {
                        "id": "f1",
                        "observation": "nodule",
                        "text": "姓名：张三 PATIENT_CANARY_9271 /nfsdata_a40/private/report.txt",
                    }
                ]
            },
        },
        "rankings": [{"model": "model-a", "selected_top_n": True}],
        "pairwise_comparisons": [],
    }

    result = _report_suggestions(payload, client)

    prompt = client.calls[0]["prompt"]
    assert "PATIENT_CANARY_9271" not in prompt
    assert "姓名" not in prompt
    assert "/nfsdata_a40" not in prompt
    assert "f1" in prompt
    assert client.calls[0]["kwargs"]["payload_classification"] == "deidentified_structured"
    assert result["suggestions"][0]["finding_id"] == "f1"
