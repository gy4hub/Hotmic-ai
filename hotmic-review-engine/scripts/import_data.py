#!/usr/bin/env python3
"""
import_data.py — 数据导入（JSON / CSV / 手动输入）

支持从以下来源导入内容数据：
1. JSON格式（平台数据直接导出）
2. CSV格式（电子表格整理后）
3. 交互式命令行输入（手动录入单条数据）

用法:
  python import_data.py --input data.json --output content_data.json
  python import_data.py --input data.csv --output content_data.json --format csv
  python import_data.py --manual --output content_data.json
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path


# 数据字段schema（用于验证）
REQUIRED_FIELDS = ["title", "date", "views"]
OPTIONAL_FIELDS = [
    "content_line", "content_type", "completion_rate",
    "likes", "comments", "shares", "followers_gained",
    "publish_time", "duration_seconds", "saves"
]
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


def validate_entry(entry: dict) -> tuple[bool, list[str]]:
    """
    验证单条数据的字段完整性和类型正确性。

    Args:
        entry: 单条内容数据字典

    Returns:
        (是否通过, 错误信息列表)
    """
    errors = []

    # 必填字段检查
    for field in REQUIRED_FIELDS:
        if field not in entry or entry[field] is None:
            errors.append(f"缺少必填字段: {field}")

    # 类型检查
    numeric_fields = ["views", "likes", "comments", "shares", "followers_gained",
                      "saves", "duration_seconds"]
    for field in numeric_fields:
        if field in entry and entry[field] is not None:
            try:
                float(entry[field])
            except (ValueError, TypeError):
                errors.append(f"字段 {field} 应为数字，得到: {entry[field]}")

    # 完播率范围检查
    if "completion_rate" in entry and entry.get("completion_rate") is not None:
        try:
            rate = float(entry["completion_rate"])
            if not 0 <= rate <= 1:
                errors.append(f"completion_rate 应在0-1之间，得到: {rate}")
        except (ValueError, TypeError):
            errors.append(f"completion_rate 应为数字")

    # 日期格式检查
    if "date" in entry and entry.get("date"):
        try:
            datetime.strptime(str(entry["date"]), "%Y-%m-%d")
        except ValueError:
            errors.append(f"date 格式应为 YYYY-MM-DD，得到: {entry['date']}")

    return len(errors) == 0, errors


def normalize_entry(entry: dict) -> dict:
    """
    标准化单条数据：确保数值字段为正确类型，缺失字段填充默认值。
    """
    normalized = {}

    for field in ALL_FIELDS:
        val = entry.get(field)
        normalized[field] = val

    # 数值类型转换
    int_fields = ["views", "likes", "comments", "shares", "followers_gained", "saves", "duration_seconds"]
    for field in int_fields:
        if normalized.get(field) is not None:
            try:
                normalized[field] = int(float(normalized[field]))
            except (ValueError, TypeError):
                normalized[field] = None

    if normalized.get("completion_rate") is not None:
        try:
            normalized["completion_rate"] = round(float(normalized["completion_rate"]), 4)
        except (ValueError, TypeError):
            normalized["completion_rate"] = None

    return normalized


def import_from_json(input_path: str) -> dict:
    """从JSON文件导入数据。"""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 支持两种格式：直接的entries列表 或 包含platform的完整格式
    if isinstance(data, list):
        return {"platform": "未知", "entries": data}
    elif isinstance(data, dict) and "entries" in data:
        return data
    else:
        raise ValueError("JSON格式不正确：应为 {platform, entries: [...]} 或直接的 [...]")


def import_from_csv(input_path: str, platform: str = "未知") -> dict:
    """
    从CSV文件导入数据。

    期望CSV列名与JSON字段名一致（英文字段名）。
    """
    entries = []
    with open(input_path, "r", encoding="utf-8-sig") as f:  # utf-8-sig处理BOM
        reader = csv.DictReader(f)
        for row in reader:
            # 过滤空行
            if not any(row.values()):
                continue
            # 转换空字符串为None
            entry = {k: (v if v != "" else None) for k, v in row.items()}
            entries.append(entry)

    return {"platform": platform, "entries": entries}


def import_manual() -> dict:
    """交互式命令行手动输入单条数据。"""
    print("=== 手动录入内容数据 ===")
    print("（按Enter跳过可选字段）\n")

    entry = {}

    # 必填字段
    entry["title"] = input("视频标题 [必填]: ").strip()
    entry["date"] = input("发布日期 YYYY-MM-DD [必填]: ").strip()
    views_str = input("播放量 [必填]: ").strip()
    entry["views"] = int(views_str) if views_str else 0

    # 可选字段
    entry["content_line"] = input("内容主线（如：健康消费避坑）[可选]: ").strip() or None
    entry["content_type"] = input("内容类型（传播款/收藏款）[可选]: ").strip() or None

    completion = input("完播率（0-1之间，如0.42）[可选]: ").strip()
    entry["completion_rate"] = float(completion) if completion else None

    likes = input("点赞数 [可选]: ").strip()
    entry["likes"] = int(likes) if likes else None

    comments = input("评论数 [可选]: ").strip()
    entry["comments"] = int(comments) if comments else None

    shares = input("分享数 [可选]: ").strip()
    entry["shares"] = int(shares) if shares else None

    followers = input("新增粉丝 [可选]: ").strip()
    entry["followers_gained"] = int(followers) if followers else None

    entry["publish_time"] = input("发布时间（如：20:00）[可选]: ").strip() or None

    platform = input("\n平台（视频号/抖音/bilibili等）[可选，默认：视频号]: ").strip() or "视频号"

    return {"platform": platform, "entries": [entry]}


def import_data(
    input_path: str | None,
    output_path: str,
    file_format: str = "json",
    manual: bool = False,
    platform: str = "未知"
) -> dict:
    """
    主导入函数：加载、验证、标准化并保存数据。

    Args:
        input_path: 输入文件路径
        output_path: 输出JSON文件路径
        file_format: 文件格式（json/csv）
        manual: 是否手动输入
        platform: 平台名称（CSV导入时使用）

    Returns:
        标准化后的数据字典
    """
    if manual:
        raw_data = import_manual()
    elif input_path:
        if file_format == "csv":
            raw_data = import_from_csv(input_path, platform)
        else:
            raw_data = import_from_json(input_path)
    else:
        raise ValueError("请提供 --input 文件路径 或使用 --manual 手动输入")

    # 验证和标准化
    validated_entries = []
    error_count = 0

    for i, entry in enumerate(raw_data.get("entries", [])):
        is_valid, errors = validate_entry(entry)
        if not is_valid:
            print(f"[WARN] 第{i+1}条数据验证失败:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            error_count += 1

        normalized = normalize_entry(entry)
        validated_entries.append(normalized)

    result = {
        "platform": raw_data.get("platform", "未知"),
        "imported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(validated_entries),
        "errors": error_count,
        "entries": validated_entries
    }

    # 保存
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path_obj, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[OK] 导入 {len(validated_entries)} 条（{error_count} 条有警告）→ {output_path}")
    return result


def main():
    parser = argparse.ArgumentParser(description="导入内容数据（JSON/CSV/手动输入）")
    parser.add_argument("--input", "-i", default=None, help="输入文件路径")
    parser.add_argument("--output", "-o", default="content_data.json", help="输出JSON文件路径")
    parser.add_argument("--format", "-f", default="json", choices=["json", "csv"], help="输入文件格式")
    parser.add_argument("--platform", "-p", default="未知", help="平台名称（CSV导入时使用）")
    parser.add_argument("--manual", action="store_true", help="交互式手动输入数据")
    args = parser.parse_args()

    try:
        import_data(args.input, args.output, args.format, args.manual, args.platform)
    except (ValueError, FileNotFoundError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
