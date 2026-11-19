"""按入库清单生成 Parquet，并逐表回读核对。"""

import argparse
import hashlib
import json
from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory
from uuid import uuid4

import pandas as pd

from mysql_input import (
    MANIFEST_PATH, PROJECT_DIR, check_input_relationships, load_input_table, read_manifest,
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish_file(source, destination):
    # 在目标目录创建普通文件以继承该目录权限。直接移动私有临时
    # 目录中的文件会在 Windows 上保留它原来的访问权限。
    pending = destination.with_name("." + destination.name + "." + uuid4().hex + ".tmp")
    with source.open("rb") as source_stream:
        target_stream = pending.open("xb")
        try:
            with target_stream:
                copyfileobj(source_stream, target_stream)
            pending.replace(destination)
        finally:
            if pending.exists():
                pending.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data" / "processed" / "mysql_input_v1")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_DIR / "reports" / "mysql_input_v1")
    args = parser.parse_args()
    try:
        import pyarrow
    except ImportError as exc:
        raise SystemExit("请使用已安装 PyArrow 的项目虚拟环境运行本脚本。") from exc

    manifest = read_manifest()
    specs = manifest["tables"]
    tables = {name: load_input_table(args.processed_dir, name, spec) for name, spec in specs.items()}
    relationships = check_input_relationships(tables, manifest["relationships"])

    checks = []
    amount_checks = []
    files = {}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output_dir) as data_tmp, TemporaryDirectory(dir=args.report_dir) as report_tmp:
        data_stage, report_stage = Path(data_tmp), Path(report_tmp)
        for name, frame in tables.items():
            spec = specs[name]
            path = data_stage / (name + ".parquet")

            # 业务主键已在数据列中，因此省略 DataFrame 的索引。
            frame.to_parquet(path, engine="pyarrow", compression="snappy", index=False)
            reread = pd.read_parquet(path, engine="pyarrow")
            pd.testing.assert_frame_equal(frame, reread, check_dtype=True, check_exact=True)
            checks.append({
                "表": name,
                "导出前行数": len(frame),
                "回读行数": len(reread),
                "行数差额": len(reread) - len(frame),
                "回读主键重复数": int(reread.duplicated(spec["primary_key"]).sum()),
                "回读缺失单元格数": int(reread.isna().sum().sum()),
                "字段类型与值一致": True,
                "文件字节数": path.stat().st_size,
            })
            for column, expected in spec.get("expected_totals", {}).items():
                actual = int(reread[column].sum())
                amount_checks.append({
                    "字段": name + "." + column,
                    "基准金额（分）": expected,
                    "回读金额（分）": actual,
                    "差额（分）": actual - expected,
                })
            files[name] = {
                "file": path.name,
                "rows": len(reread),
                "primary_key": spec["primary_key"],
                "source_csv_sha256": sha256(args.processed_dir / spec["source"]),
                "parquet_sha256": sha256(path),
            }

        for filename, frame in [
            ("parquet_roundtrip_v1.csv", pd.DataFrame(checks)),
            ("amount_controls_v1.csv", pd.DataFrame(amount_checks)),
            ("relationship_checks_v1.csv", relationships),
        ]:
            frame.to_csv(report_stage / filename, index=False, encoding="utf-8-sig")
        run_info = {
            "manifest_version": manifest["version"],
            "manifest_sha256": sha256(MANIFEST_PATH),
            "pandas": pd.__version__,
            "pyarrow": pyarrow.__version__,
            "compression": "snappy",
            "tables": files,
        }
        (report_stage / "parquet_run_info_v1.json").write_text(
            json.dumps(run_info, ensure_ascii=False, indent=2), encoding="utf-8")

        # 所有表通过回读比较之后发布文件。
        for staged, target in [(data_stage, args.output_dir), (report_stage, args.report_dir)]:
            for path in staged.iterdir():
                publish_file(path, target / path.name)

    print("已导出并回读核对 {} 张 Parquet 表。".format(len(checks)))
    print("数据目录 " + str(args.output_dir.resolve()))
    print("报告目录 " + str(args.report_dir.resolve()))


if __name__ == "__main__":
    main()
