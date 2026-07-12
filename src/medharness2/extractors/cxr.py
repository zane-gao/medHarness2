from medharness2.extractors.rules import RuleFindingExtractor
from medharness2.ontology.cxr import cxr_rule_observation_aliases


CXR_OBSERVATIONS = cxr_rule_observation_aliases()
_CXR_BILINGUAL_ALIASES = {
    "opacity": ["阴影", "斑片影", "密度影", "密度增高影"],
    "nodule": ["结节", "结节影"],
    "mass": ["肿块", "占位"],
    "effusion": ["胸腔积液", "积液"],
    "pneumothorax": ["气胸"],
    "edema": ["肺水肿", "水肿"],
    "consolidation": ["实变"],
    "atelectasis": ["肺不张", "不张"],
}
for _code, _aliases in _CXR_BILINGUAL_ALIASES.items():
    CXR_OBSERVATIONS[_code] = sorted(
        {*CXR_OBSERVATIONS.get(_code, []), *_aliases},
        key=lambda value: (-len(value), value),
    )

CXR_LOCATIONS = {
    "right upper lobe": ["right upper lobe", "right upper lung", "右上肺", "右肺上叶", "右上叶"],
    "right lower lobe": ["right lower lobe", "right lower lung", "右下肺", "右肺下叶", "右下叶"],
    "left upper lobe": ["left upper lobe", "left upper lung", "左上肺", "左肺上叶", "左上叶"],
    "left lower lobe": ["left lower lobe", "left lower lung", "左下肺", "左肺下叶", "左下叶"],
    "right pleural": ["right pleural space", "right pleural", "右侧胸腔", "右胸腔", "右侧胸膜", "右胸膜"],
    "left pleural": ["left pleural space", "left pleural", "左侧胸腔", "左胸腔", "左侧胸膜", "左胸膜"],
    "right lung": ["right lung", "右肺"],
    "left lung": ["left lung", "左肺"],
    "bilateral lungs": ["bilateral lungs", "both lungs", "双肺", "两肺"],
    "pleural": ["pleural", "pleura", "胸膜", "胸腔"],
    "heart": ["heart", "cardiac", "心影", "心脏"],
}

CXR_EXTRACTOR = RuleFindingExtractor(
    backend="cxr_rule",
    modalities=("cxr", "xray", "xr"),
    observation_aliases=CXR_OBSERVATIONS,
    location_aliases=CXR_LOCATIONS,
    fallback_reported_finding=True,
)
