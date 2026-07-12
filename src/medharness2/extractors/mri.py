from medharness2.extractors.rules import RuleFindingExtractor, sequence_attributes


MRI_OBSERVATIONS = {
    "white_matter_hyperintensity": [
        "white matter hyperintensity",
        "white matter high signal",
        "T2-FLAIR高信号",
        "FLAIR高信号",
        "白质高信号",
    ],
    "acute_infarct": ["acute infarct", "acute infarction", "急性梗死", "急性梗塞"],
    "infarct": ["infarct", "infarction", "梗死", "梗塞"],
    "hemorrhage": ["hemorrhage", "haemorrhage", "出血"],
    "mass": ["mass", "tumor", "肿块", "占位"],
    "edema": ["edema", "水肿"],
    "demyelination": ["demyelination", "脱髓鞘"],
    "cerebral_atrophy": ["cerebral atrophy", "brain atrophy", "脑萎缩"],
    "ventriculomegaly": ["ventriculomegaly", "ventricular dilatation", "脑室扩张"],
    "mucosal_thickening": ["mucosal thickening", "黏膜增厚", "粘膜增厚"],
}

MRI_LOCATIONS = {
    "periventricular_white_matter": ["periventricular white matter", "脑室旁白质", "侧脑室旁白质", "脑室旁"],
    "right frontal lobe": ["right frontal lobe", "右额叶"],
    "left frontal lobe": ["left frontal lobe", "左额叶"],
    "frontal lobe": ["frontal lobe", "额叶"],
    "temporal lobe": ["temporal lobe", "颞叶"],
    "parietal lobe": ["parietal lobe", "顶叶"],
    "occipital lobe": ["occipital lobe", "枕叶"],
    "brainstem": ["brainstem", "脑干"],
    "cerebellum": ["cerebellum", "小脑"],
    "brain": ["brain", "cerebral", "脑", "颅脑"],
    "sinus": ["sinus", "筛窦", "上颌窦", "额窦", "蝶窦"],
}

MRI_EXTRACTOR = RuleFindingExtractor(
    backend="mri_rule",
    modalities=("mri", "mr"),
    observation_aliases=MRI_OBSERVATIONS,
    location_aliases=MRI_LOCATIONS,
    fallback_reported_finding=False,
    attribute_resolver=sequence_attributes,
)
