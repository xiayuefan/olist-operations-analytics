"""地理坐标粗筛、代表坐标和地址覆盖检查。"""

import pandas as pd

from customers_cleaning import STATE_CODES


ZIP_COL = "geolocation_zip_code_prefix"
STATE_COL = "geolocation_state"
GEO_KEY = [ZIP_COL, STATE_COL]
SOURCE_COLS = GEO_KEY + ["geolocation_city", "geolocation_lat", "geolocation_lng"]
LATITUDE_SCREEN = (-35, 6)
LONGITUDE_SCREEN = (-75, -28)
REPRESENTATIVE_COORDS = ["representative_latitude", "representative_longitude"]
MATCHED_LABEL = "匹配到含候选坐标的州组合"
QUALITY_FLAGS = [
    "flag_missing_or_unparsed_coordinate",
    "flag_outside_world_range",
    "flag_outside_brazil_screen",
    "flag_invalid_zip_state",
]


def prepare_geolocation(raw):
    """按原始字段整行去重，保留坐标文本及候选资格标记。"""
    missing = set(SOURCE_COLS) - set(raw.columns)
    if missing:
        raise ValueError("地理原表缺少字段 " + ", ".join(sorted(missing)))

    geo = raw[SOURCE_COLS].drop_duplicates().copy()
    geo[ZIP_COL] = geo[ZIP_COL].str.strip()
    geo[STATE_COL] = geo[STATE_COL].str.strip().str.upper()
    geo["city_label"] = geo["geolocation_city"].str.strip().str.lower().replace("", pd.NA)
    geo["latitude"] = pd.to_numeric(geo["geolocation_lat"], errors="coerce")
    geo["longitude"] = pd.to_numeric(geo["geolocation_lng"], errors="coerce")

    lat = geo["latitude"]
    lng = geo["longitude"]
    parsed = lat.notna() & lng.notna()
    world_ok = lat.between(-90, 90) & lng.between(-180, 180)
    inside_screen = lat.between(*LATITUDE_SCREEN) & lng.between(*LONGITUDE_SCREEN)
    key_ok = geo[ZIP_COL].str.fullmatch("[0-9]{5}", na=False) & geo[STATE_COL].isin(STATE_CODES)

    # 坐标解析、全球范围和项目粗筛分别检查。键格式另行记录。
    geo["flag_missing_or_unparsed_coordinate"] = ~parsed
    geo["flag_outside_world_range"] = parsed & ~world_ok
    geo["flag_outside_brazil_screen"] = world_ok & ~inside_screen
    geo["flag_invalid_zip_state"] = ~key_ok
    geo["coordinate_candidate"] = world_ok & inside_screen & key_ok
    return geo


def build_geo_reference(geo):
    """按邮编前缀与州分别计算纬度和经度中位数。"""
    candidates = geo.loc[geo["coordinate_candidate"], GEO_KEY + ["latitude", "longitude", "city_label"]]
    reference = candidates.groupby(GEO_KEY, as_index=False).agg(
        representative_latitude=("latitude", "median"),
        representative_longitude=("longitude", "median"),
        candidate_record_count=("latitude", "size"),
        candidate_city_label_count=("city_label", "nunique"),
    )
    if reference[GEO_KEY].isna().any().any() or reference.duplicated(GEO_KEY).any():
        raise ValueError("代表坐标组合主键缺失或重复")
    if reference["candidate_record_count"].sum() != len(candidates):
        raise ValueError("代表坐标表的候选记录数与来源不一致")
    return reference


def _address_keys(raw, entity):
    # 临时键用于匹配。原表的邮编与州字段保留在结果中。
    return pd.DataFrame({
        ZIP_COL: raw[entity + "_zip_code_prefix"].str.strip(),
        STATE_COL: raw[entity + "_state"].str.strip().str.upper(),
    }, index=raw.index)


def attach_geolocation(raw, reference, entity):
    """按邮编前缀与州向客户或卖家左关联代表坐标。"""
    ids = raw[entity + "_id"]
    if ids.isna().any() or ids.astype(str).str.strip().eq("").any() or ids.duplicated().any():
        raise ValueError("来源 ID 必须非空且唯一")
    keys = _address_keys(raw, entity)
    join_names = {ZIP_COL: "geo_zip_key", STATE_COL: "geo_state_key"}
    joined = raw.assign(**keys.rename(columns=join_names)).merge(
        reference.rename(columns=join_names), on=list(join_names.values()),
        how="left", validate="many_to_one", indicator="geo_match",
    ).drop(columns=list(join_names.values()))
    if not joined[raw.columns].equals(raw.reset_index(drop=True)):
        raise ValueError("关联后的来源记录与输入不一致")

    # 匹配记录应有两个坐标值。未匹配记录的两个坐标都为空。
    matched = joined["geo_match"].eq("both")
    missing_coords = joined[REPRESENTATIVE_COORDS].isna().sum(axis=1)
    if not missing_coords.eq(2 * (~matched).astype(int)).all():
        raise ValueError("坐标缺失状态与匹配结果不一致")
    return joined


def summarize_address_coverage(raw, geo, reference, entity):
    """将每条来源地址分入四种覆盖状态之一。"""
    keys = _address_keys(raw, entity)
    address_pairs = pd.MultiIndex.from_frame(keys)
    source_pairs = pd.MultiIndex.from_frame(geo[GEO_KEY].drop_duplicates())
    reference_pairs = pd.MultiIndex.from_frame(reference[GEO_KEY])
    prefix_hit = keys[ZIP_COL].isin(geo[ZIP_COL].dropna().unique())
    pair_hit = pd.Series(address_pairs.isin(source_pairs), index=keys.index)
    matched = pd.Series(address_pairs.isin(reference_pairs), index=keys.index)
    counts = pd.Series({
        "地理表缺少邮编前缀": int((~prefix_hit).sum()),
        "邮编前缀存在但州组合缺失": int((prefix_hit & ~pair_hit).sum()),
        "州组合存在但没有候选坐标": int((pair_hit & ~matched).sum()),
        MATCHED_LABEL: int(matched.sum()),
    })
    if counts.sum() != len(raw):
        raise ValueError("覆盖分类合计与来源记录数不一致")
    return counts


def reconcile_geolocation_join(raw, joined, coverage, entity):
    """核对关联结果的行数、主键和覆盖数。"""
    matched = int(joined["geo_match"].eq("both").sum())
    difference = len(joined) - len(raw)
    duplicated_ids = int(joined[entity + "_id"].duplicated().sum())
    if difference or duplicated_ids or matched != coverage[MATCHED_LABEL]:
        raise ValueError("地理关联行数、主键或覆盖数不一致")
    return pd.Series({
        "关联前行数": len(raw),
        "关联后行数": len(joined),
        "行数差额": difference,
        "关联后主键重复数": duplicated_ids,
        "匹配到代表坐标": matched,
        "未匹配到代表坐标": len(joined) - matched,
    })
