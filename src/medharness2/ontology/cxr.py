from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Literal


CXR_ONTOLOGY_VERSION = "cxr-controlled-v1"


@dataclass(frozen=True)
class CXRConcept:
    anatomy: str
    aliases: tuple[str, ...]
    normal_aliases: tuple[str, ...] = ()
    matchable: bool = True


_CONCEPTS: dict[str, CXRConcept] = {
    "opacity": CXRConcept(
        anatomy="lung",
        aliases=(
            "opacity",
            "opacities",
            "pulmonary opacity",
            "airspace opacity",
            "density opacity",
            "infiltrate",
        ),
        normal_aliases=(
            "clear lung",
            "clear lungs",
            "lungs are clear",
            "lung is clear",
            "no focal opacity",
            "no pulmonary opacity",
            "no abnormal pulmonary density",
            "no acute pulmonary disease",
            "未见异常密度影",
        ),
    ),
    "nodule": CXRConcept(
        anatomy="lung",
        aliases=("nodule", "nodules", "pulmonary nodule", "nodular opacity"),
    ),
    "mass": CXRConcept(
        anatomy="lung",
        aliases=("mass", "masses", "pulmonary mass"),
    ),
    "consolidation": CXRConcept(
        anatomy="lung",
        aliases=("consolidation", "airspace consolidation"),
    ),
    "atelectasis": CXRConcept(
        anatomy="lung",
        aliases=("atelectasis", "lobar collapse", "lung collapse"),
    ),
    "edema": CXRConcept(
        anatomy="lung",
        aliases=("edema", "pulmonary edema", "interstitial edema"),
    ),
    "interstitial_change": CXRConcept(
        anatomy="lung",
        aliases=("interstitial change", "interstitial changes", "interstitial opacity"),
    ),
    "increased_lung_markings": CXRConcept(
        anatomy="lung",
        aliases=(
            "increased lung markings",
            "increased pulmonary markings",
            "coarse lung markings",
            "coarse pulmonary markings",
            "肺纹理增多",
            "肺纹理增粗",
            "双肺纹理增强",
        ),
        normal_aliases=(
            "normal lung markings",
            "clear pulmonary markings",
            "肺纹理清晰",
            "纹理清晰",
        ),
    ),
    "low_lung_volume": CXRConcept(
        anatomy="lung",
        aliases=("low lung volume", "low lung volumes", "hypoinflation"),
        normal_aliases=("well expanded lungs", "lungs are well expanded", "normal lung volume"),
    ),
    "cardiopulmonary_abnormality": CXRConcept(
        anatomy="cardiopulmonary",
        aliases=(
            "acute cardiopulmonary abnormality",
            "cardiopulmonary abnormality",
            "acute cardiopulmonary disease",
        ),
        normal_aliases=(
            "no acute cardiopulmonary abnormality",
            "no acute cardiopulmonary disease",
            "no acute disease",
            "normal chest radiograph",
            "normal chest x ray",
            "心肺未见明显异常",
            "心肺未见异常",
            "胸片未见明显异常",
        ),
    ),
    "effusion": CXRConcept(
        anatomy="pleura",
        aliases=("effusion", "pleural effusion", "pleural fluid"),
    ),
    "pneumothorax": CXRConcept(
        anatomy="pleura",
        aliases=("pneumothorax",),
    ),
    "pleural_thickening": CXRConcept(
        anatomy="pleura",
        aliases=("pleural thickening",),
    ),
    "costophrenic_angle_blunting": CXRConcept(
        anatomy="costophrenic_angle",
        aliases=("costophrenic angle blunting", "blunted costophrenic angle"),
        normal_aliases=(
            "sharp costophrenic angle",
            "sharp costophrenic angles",
            "肋膈角锐利",
        ),
    ),
    "cardiomegaly": CXRConcept(
        anatomy="heart",
        aliases=("cardiomegaly", "cardiac enlargement", "enlarged cardiac silhouette"),
        normal_aliases=(
            "normal cardiac silhouette",
            "normal cardiomediastinal silhouette",
            "cardiomediastinal silhouette is normal",
            "cardiomediastinal silhouette is within normal limits",
            "cardiomediastinal silhouette is unremarkable",
            "normal heart size",
            "no cardiac enlargement",
            "心影不大",
            "心影大小未见异常",
            "心影形态、大小未见异常",
        ),
    ),
    "cardiac_morphology_abnormality": CXRConcept(
        anatomy="heart",
        aliases=("cardiac morphology abnormality", "cardiac contour abnormality"),
        normal_aliases=(
            "normal cardiac morphology",
            "no abnormal cardiac morphology",
            "心影形态未见异常",
        ),
    ),
    "mediastinal_shift": CXRConcept(
        anatomy="mediastinum",
        aliases=("mediastinal shift",),
        normal_aliases=(
            "mediastinum is midline",
            "midline mediastinum",
            "纵隔居中",
        ),
    ),
    "mediastinal_widening": CXRConcept(
        anatomy="mediastinum",
        aliases=("mediastinal widening", "widened mediastinum"),
    ),
    "tracheal_deviation": CXRConcept(
        anatomy="trachea",
        aliases=("tracheal deviation", "deviated trachea"),
        normal_aliases=(
            "trachea is midline",
            "midline trachea",
            "气管及纵隔居中",
            "气管居中",
        ),
    ),
    "hilar_enlargement": CXRConcept(
        anatomy="pulmonary_hilum",
        aliases=("hilar enlargement", "enlarged hilum", "enlarged hila"),
        normal_aliases=(
            "hila are not enlarged",
            "no hilar enlargement",
            "双侧肺门未见增大",
            "肺门未见增大",
            "双侧肺门不大",
            "肺门不大",
        ),
    ),
    "hilar_prominence": CXRConcept(
        anatomy="pulmonary_hilum",
        aliases=("hilar prominence", "prominent hilum", "increased hilar density"),
        normal_aliases=(
            "no hilar prominence",
            "no increased hilar density",
            "肺门未见增浓",
            "未见增浓",
        ),
    ),
    "aortic_abnormality": CXRConcept(
        anatomy="aorta",
        aliases=("aortic abnormality", "abnormal aortic contour"),
        normal_aliases=(
            "no aortic abnormality",
            "normal aorta",
            "normal aortic contour",
            "主动脉未见异常",
        ),
    ),
    "diaphragm_abnormality": CXRConcept(
        anatomy="diaphragm",
        aliases=("diaphragm abnormality", "abnormal diaphragmatic contour"),
        normal_aliases=(
            "smooth diaphragm",
            "smooth diaphragms",
            "normal diaphragm",
            "双侧膈肌光整",
            "膈肌光整",
        ),
    ),
    "osseous_abnormality": CXRConcept(
        anatomy="bone",
        aliases=(
            "osseous abnormality",
            "osseous abnormalities",
            "bone abnormality",
            "bone abnormalities",
            "acute osseous abnormality",
            "acute osseous abnormalities",
        ),
        normal_aliases=(
            "no acute osseous abnormality",
            "no acute osseous abnormalities",
            "no osseous abnormality",
            "no osseous abnormalities",
        ),
    ),
    "thoracic_cage_asymmetry": CXRConcept(
        anatomy="thoracic_cage",
        aliases=("thoracic cage asymmetry", "asymmetric bony thorax"),
        normal_aliases=(
            "symmetric bony thorax",
            "symmetric thoracic cage",
            "骨性胸廓双侧基本对称",
            "骨性胸廓双侧对称",
        ),
    ),
    "device_abnormality": CXRConcept(
        anatomy="device",
        aliases=("device abnormality", "malpositioned device", "line malposition"),
    ),
    "other_finding": CXRConcept(
        anatomy="unspecified",
        aliases=(),
        matchable=False,
    ),
}


_NEGATION_RE = re.compile(
    r"(?:\b(?:no|without|negative for|no evidence of|absent|free of|not seen|not identified|cannot identify)\b|未见|无|未发现|未提示)",
    re.I,
)

_CONTRAST_BOUNDARY_RE = re.compile(
    r"(?:\b(?:but|however|yet|nevertheless|though)\b|但是|但|然而|不过|而|却)",
    re.I,
)

_GENERIC_OBSERVATION_TEXT = {
    "finding",
    "normal",
    "observation",
    "reported finding",
}

_BROAD_CONCEPT_CODES = {"cardiopulmonary_abnormality"}

_GENERIC_ANATOMY_ALIASES = {
    "lung": {
        "bilateral lung",
        "bilateral lungs",
        "both lung",
        "both lungs",
        "lung",
        "lungs",
        "pulmonary",
    },
    "pleura": {"bilateral pleura", "pleura", "pleural", "pleural space"},
    "heart": {"cardiac", "cardiomediastinal", "cardiomediastinum", "heart"},
    "mediastinum": {"mediastinal", "mediastinum"},
    "trachea": {"trachea", "tracheal"},
    "pulmonary_hilum": {"hila", "hilum", "pulmonary hila", "pulmonary hilum"},
    "aorta": {"aorta", "aortic"},
    "diaphragm": {"diaphragm", "diaphragmatic", "diaphragms"},
    "bone": {"bone", "bones", "osseous"},
    "thoracic_cage": {"bony thorax", "thoracic cage"},
    "device": {"device", "devices", "line", "lines"},
    "cardiopulmonary": {"cardiopulmonary", "chest", "thorax"},
}


def canonicalize_cxr_finding(
    *,
    observation_code: str,
    observation_text: str,
    evidence: str,
    anatomy_code: str | None,
    location_text: str | None,
    certainty: Literal["present", "absent", "uncertain"],
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    original_code = observation_code.strip()
    original_certainty = certainty
    code, matched_as = _resolve_concept_fields(
        observation_code=observation_code,
        observation_text=observation_text,
        evidence=evidence,
    )
    concept = _CONCEPTS[code]
    if matched_as != "normal" and _matches_normal_statement(
        concept,
        observation_text=observation_text,
        evidence=evidence,
    ):
        matched_as = "normal"
    canonical_certainty = certainty
    if matched_as == "normal":
        canonical_certainty = "absent"
    elif certainty != "uncertain" and _is_concept_negated(evidence, code, concept):
        canonical_certainty = "absent"
    canonical_anatomy = _canonicalize_anatomy(anatomy_code, default=concept.anatomy)
    merged_attributes = copy.deepcopy(attributes or {})
    merged_attributes.update(
        {
            "ontology_version": CXR_ONTOLOGY_VERSION,
            "ontology_match": matched_as,
            "ontology_matchable": concept.matchable,
            "original_observation_code": original_code,
            "original_certainty": original_certainty,
            "original_anatomy_code": anatomy_code,
        }
    )
    return {
        "observation_code": code,
        "anatomy_code": canonical_anatomy,
        "location_text": location_text,
        "certainty": canonical_certainty,
        "attributes": merged_attributes,
    }


def cxr_prompt_catalog() -> dict[str, Any]:
    return {
        "version": CXR_ONTOLOGY_VERSION,
        "orientation": "abnormality",
        "normal_statement_policy": (
            "Encode normal or negative language as the corresponding abnormality "
            "concept with certainty=absent. Never emit a generic normal concept."
        ),
        "concepts": {
            code: {
                "anatomy": concept.anatomy,
                "orientation": "abnormality",
                "matchable": concept.matchable,
            }
            for code, concept in _CONCEPTS.items()
        },
    }


def cxr_rule_observation_aliases() -> dict[str, list[str]]:
    return {
        code: sorted(
            {
                code.replace("_", " "),
                *concept.aliases,
                *concept.normal_aliases,
            },
            key=lambda value: (-len(value), value),
        )
        for code, concept in _CONCEPTS.items()
        if concept.matchable
    }


def is_matchable_cxr_concept(code: str) -> bool:
    concept = _CONCEPTS.get(_normalized_text(code).replace(" ", "_"))
    return bool(concept and concept.matchable)


def _resolve_concept(searchable: str) -> tuple[str, str]:
    candidates: list[tuple[int, int, str, str]] = []
    for code, concept in _CONCEPTS.items():
        if code == "other_finding":
            continue
        for alias in concept.normal_aliases:
            if _contains_alias(searchable, alias):
                candidates.append((len(_normalized_text(alias)), 1, code, "normal"))
        for alias in concept.aliases:
            if _contains_alias(searchable, alias):
                candidates.append((len(_normalized_text(alias)), 0, code, "canonical"))
        code_alias = code.replace("_", " ")
        if _contains_alias(searchable, code_alias):
            candidates.append((len(code_alias), 0, code, "canonical"))
    if not candidates:
        return "other_finding", "unmapped"
    _, _, code, matched_as = max(candidates, key=lambda item: (item[0], item[1], item[2]))
    return code, matched_as


def _resolve_concept_fields(
    *,
    observation_code: str,
    observation_text: str,
    evidence: str,
) -> tuple[str, str]:
    broad_match: tuple[str, str] | None = None
    for index, value in enumerate((observation_code, observation_text, evidence)):
        normalized = _normalized_text(value)
        if not normalized:
            continue
        if index < 2 and normalized in _GENERIC_OBSERVATION_TEXT:
            continue
        code, matched_as = _resolve_concept(normalized)
        if code == "other_finding":
            continue
        if code in _BROAD_CONCEPT_CODES:
            if broad_match is None or matched_as == "normal":
                broad_match = (code, matched_as)
            continue
        return code, matched_as
    return broad_match or ("other_finding", "unmapped")


def _matches_normal_statement(
    concept: CXRConcept,
    *,
    observation_text: str,
    evidence: str,
) -> bool:
    return any(
        _contains_alias(_normalized_text(value), alias)
        for value in (observation_text, evidence)
        for alias in concept.normal_aliases
    )


def _is_concept_negated(evidence: str, code: str, concept: CXRConcept) -> bool:
    mentions: list[bool] = []
    aliases = {
        code.replace("_", " "),
        *concept.aliases,
        *concept.normal_aliases,
    }
    for alias in sorted(aliases, key=len, reverse=True):
        for match in _alias_matches(evidence, alias):
            prefix = evidence[: match.start()]
            sentence_start = max(
                prefix.rfind(mark)
                for mark in ("。", ".", "；", ";", "\n")
            ) + 1
            clause = prefix[sentence_start:]
            boundaries = list(_CONTRAST_BOUNDARY_RE.finditer(clause))
            if boundaries:
                clause = clause[boundaries[-1].end() :]
            mentions.append(bool(_NEGATION_RE.search(clause)))
    return bool(mentions) and all(mentions)


def _alias_matches(text: str, alias: str) -> list[re.Match[str]]:
    tokens = [token for token in re.split(r"\s+", alias.strip()) if token]
    if not tokens:
        return []
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    if alias.isascii():
        pattern = rf"(?<!\w){pattern}(?!\w)"
    return list(re.finditer(pattern, text, flags=re.I))


def _canonicalize_anatomy(anatomy_code: str | None, *, default: str) -> str | None:
    if anatomy_code is None or not anatomy_code.strip():
        return None if default == "unspecified" else default
    normalized = _normalized_text(anatomy_code)
    for canonical, aliases in _GENERIC_ANATOMY_ALIASES.items():
        if normalized in aliases:
            return canonical
    return anatomy_code.strip()


def _contains_alias(text: str, alias: str) -> bool:
    normalized = _normalized_text(alias)
    if not normalized:
        return False
    if re.search(r"[\u4e00-\u9fff]", normalized):
        return normalized in text
    return bool(re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", text))


def _normalized_text(value: str) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    return " ".join(text.split())
