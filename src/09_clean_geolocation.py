"""从原始 CSV 导出代表坐标、客户卖家关联表和核对报告。"""

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from customers_cleaning import REFERENCE_PATH
from geolocation_cleaning import (
    GEO_KEY, LATITUDE_SCREEN, LONGITUDE_SCREEN, QUALITY_FLAGS, STATE_COL, ZIP_COL,
    attach_geolocation, build_geo_reference, prepare_geolocation,
    reconcile_geolocation_join, summarize_address_coverage,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCREEN_SOURCE = "https://anuario.ibge.gov.br/images/aeb/2024/s1/2_pdf/s1t1101.pdf"


def read_source(path):
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig",
                       keep_default_na=False, na_values=[""])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_DIR.parent / "archive")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data" / "processed" / "geolocation_v1")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_DIR / "reports" / "geolocation_v1")
    args = parser.parse_args()

    geo_path = args.data_dir / "olist_geolocation_dataset.csv"
    geo_raw = read_source(geo_path)
    geo = prepare_geolocation(geo_raw)
    reference = build_geo_reference(geo)
    exclusions = geo.loc[~geo["coordinate_candidate"]]
    states_per_zip = geo.groupby(ZIP_COL)[STATE_COL].nunique()
    conflict_zips = states_per_zip.loc[states_per_zip.gt(1)].index
    conflicts = (
        geo.loc[geo[ZIP_COL].isin(conflict_zips)]
        .groupby(GEO_KEY, as_index=False)
        .agg(source_rows=("coordinate_candidate", "size"),
             candidate_rows=("coordinate_candidate", "sum"))
    )

    outputs = {"geo_reference_v1.csv": reference}
    coverage, controls = {}, {}
    source_paths = [geo_path]
    for entity, label in [("customer", "客户表"), ("seller", "卖家表")]:
        plural = entity + "s"
        path = args.data_dir / ("olist_" + plural + "_dataset.csv")
        source_paths.append(path)
        raw = read_source(path)
        joined = attach_geolocation(raw, reference, entity)
        coverage[label] = summarize_address_coverage(raw, geo, reference, entity)
        controls[label] = reconcile_geolocation_join(raw, joined, coverage[label], entity)
        outputs[plural + "_with_geo_v1.csv"] = joined

    coordinate_counts = pd.Series({
        "原表行数": len(geo_raw),
        "整行重复数": len(geo_raw) - len(geo),
        "去重后行数": len(geo),
        "未进入候选集的记录数": len(exclusions),
        "候选记录数": len(geo) - len(exclusions),
        "代表坐标组数": len(reference),
        **{flag: int(geo[flag].sum()) for flag in QUALITY_FLAGS},
    })
    metrics = {
        "representative_key": GEO_KEY,
        "representative_method": "coordinate-wise median of eligible exact-row-deduplicated records",
        "latitude_screen": LATITUDE_SCREEN,
        "longitude_screen": LONGITUDE_SCREEN,
        "screen_reference_url": SCREEN_SOURCE,
        "cross_state_prefixes": len(conflict_zips),
        "coordinate_checks": {name: int(value) for name, value in coordinate_counts.items()},
        "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_paths + [REFERENCE_PATH]
        },
    }
    report = "\n".join([
        "# 地理阶段报告 v1", "",
        "项目粗筛矩形为纬度 {} 到 {}、经度 {} 到 {}。矩形内的点仍需结合地区信息复核。"
        " [IBGE 地理极点表]({})".format(*LATITUDE_SCREEN, *LONGITUDE_SCREEN, SCREEN_SOURCE), "",
        "地理原表有 {:,} 行。整行去重后有 {:,} 行，其中 {:,} 行进入坐标候选集。".format(
            len(geo_raw), len(geo), len(geo) - len(exclusions)),
        "每组分别取经纬度中位数，得到 {:,} 组「邮编前缀＋州」代表点。".format(len(reference)),
        "原始地区标签中有 {:,} 个邮编前缀对应多个州。".format(len(conflict_zips)), "",
        "| 来源 | 关联前行数 | 关联后行数 | 匹配到代表坐标 | 未匹配 |",
        "| --- | ---: | ---: | ---: | ---: |",
        *[
            "| {} | {:,} | {:,} | {:,} | {:,} |".format(
                label, check["关联前行数"], check["关联后行数"],
                check["匹配到代表坐标"], check["未匹配到代表坐标"],
            )
            for label, check in controls.items()
        ], "",
        "关联以客户、卖家原表为左表。未匹配记录的新增坐标为空。"
        "覆盖分类见 address_coverage_v1.csv，异常坐标和跨州前缀分别保存在核查清单中。", "",
    ])

    # 先完成检查和临时文件写入，再逐个替换同盘的正式文件。
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output_dir) as data_tmp, TemporaryDirectory(dir=args.report_dir) as report_tmp:
        data_stage, report_stage = Path(data_tmp), Path(report_tmp)
        for name, frame in outputs.items():
            frame.to_csv(data_stage / name, index=False, encoding="utf-8-sig")
        for name, frame in [
            ("coordinate_checks_v1.csv", coordinate_counts.rename("数量").to_frame()),
            ("address_coverage_v1.csv", pd.DataFrame(coverage)),
            ("geo_join_controls_v1.csv", pd.DataFrame(controls)),
        ]:
            frame.to_csv(report_stage / name, index_label="检查项", encoding="utf-8-sig")
        exclusions.to_csv(report_stage / "coordinate_exclusions_v1.csv", index=False, encoding="utf-8-sig")
        conflicts.to_csv(report_stage / "cross_state_prefixes_v1.csv", index=False, encoding="utf-8-sig")
        (report_stage / "metrics_v1.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        (report_stage / "地理阶段报告_v1.md").write_text(report, encoding="utf-8")
        for staged, target in [(data_stage, args.output_dir), (report_stage, args.report_dir)]:
            for file in staged.iterdir():
                file.replace(target / file.name)

    print("代表坐标 {:,} 组，客户和卖家关联行数差额均为 0。".format(len(reference)))
    print("报告目录 " + str(args.report_dir.resolve()))


if __name__ == "__main__":
    main()
