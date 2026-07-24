from medharness2.extractors.rules import RuleFindingExtractor


CT_OBSERVATIONS = {
    "ground_glass_opacity": ["ground-glass opacity", "ground glass opacity", "磨玻璃影", "磨玻璃密度影"],
    "low_density_lesion": ["hypodense lesion", "low-density lesion", "低密度灶", "低密度影"],
    "high_density_lesion": ["hyperdense lesion", "high-density lesion", "高密度灶", "高密度影"],
    "nodule": ["nodule", "nodules", "结节", "结节影"],
    "mass": ["mass", "tumor", "肿块", "占位"],
    "cyst": ["cyst", "cystic lesion", "囊肿", "囊性灶"],
    "hemorrhage": ["hemorrhage", "haemorrhage", "bleeding", "出血"],
    "infarct": ["infarct", "infarction", "梗死", "梗塞"],
    "fracture": ["fracture", "骨折"],
    "lymphadenopathy": ["lymphadenopathy", "enlarged lymph node", "淋巴结肿大", "肿大淋巴结"],
    "bowel_obstruction": ["bowel obstruction", "intestinal obstruction", "肠梗阻"],
    "bowel_dilation": ["bowel dilatation", "bowel dilation", "肠管扩张", "肠腔扩张"],
    "calculus": ["calculus", "stone", "结石"],
    "ascites": ["ascites", "腹水", "腹腔积液"],
    "pleural_effusion": ["pleural effusion", "胸腔积液"],
    "consolidation": ["consolidation", "实变"],
    "atelectasis": ["atelectasis", "肺不张", "不张"],
}

CT_LOCATIONS = {
    "liver": ["right hepatic lobe", "left hepatic lobe", "liver", "肝右叶", "肝左叶", "肝脏", "肝"],
    "gallbladder": ["gallbladder", "胆囊"],
    "pancreas": ["pancreas", "胰腺"],
    "spleen": ["spleen", "脾脏", "脾"],
    "right kidney": ["right kidney", "右肾"],
    "left kidney": ["left kidney", "左肾"],
    "bilateral kidneys": ["both kidneys", "bilateral kidneys", "双肾"],
    "adrenal": ["adrenal", "肾上腺"],
    "bowel": ["bowel", "intestine", "肠管", "肠腔", "小肠", "结肠"],
    "bladder": ["urinary bladder", "bladder", "膀胱"],
    "peritoneum": ["peritoneal", "peritoneum", "腹腔"],
    "brain": ["brain", "cerebral", "颅脑", "脑"],
    "right upper lobe": ["right upper lobe", "右肺上叶"],
    "right lower lobe": ["right lower lobe", "右肺下叶", "右下肺"],
    "left upper lobe": ["left upper lobe", "左肺上叶"],
    "left lower lobe": ["left lower lobe", "左肺下叶", "左下肺"],
    "bilateral lungs": ["both lungs", "bilateral lungs", "双肺"],
    "mediastinum": ["mediastinum", "纵隔"],
    "bone": ["bone", "osseous", "骨质", "骨"],
}

CT_EXTRACTOR = RuleFindingExtractor(
    backend="ct_rule",
    modalities=("ct",),
    observation_aliases=CT_OBSERVATIONS,
    location_aliases=CT_LOCATIONS,
    fallback_reported_finding=False,
)
