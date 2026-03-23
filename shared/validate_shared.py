#!/usr/bin/env python3
"""
validate_shared.py — 验证shared/目录下所有JSON文件的格式正确性

检查：
  - config.json：平台配置、路径引用
  - persona.json：定位、内容混合权重汇总
  - style_db.json：规则格式
  - content_log.json：条目格式

用法:
  python validate_shared.py
  python validate_shared.py --dir /path/to/shared/
"""

import argparse
import json
import sys
from pathlib import Path


# ========================
# JSON Schema定义
# ========================

CONFIG_SCHEMA = {
    "required": ["style_db", "content_log", "persona", "platforms"],
    "style_db": {"required": ["path", "confidence_threshold"]},
    "content_log": {"required": ["path"]},
    "persona": {"required": ["path"]},
    "platforms": {"type": "dict", "min_entries": 1}
}

PERSONA_SCHEMA = {
    "required": ["account_id", "positioning", "content_mix"],
    "positioning": {"required": ["one_liner", "identity", "topic", "audience"]},
    "content_mix": {"required": ["lines"]},
    "content_mix.lines": {
        "type": "list",
        "each_required": ["name", "weight", "description"],
        "weight_sum": 1.0,  # 所有权重之和应为1.0（允许±0.05误差）
    }
}

STYLE_DB_SCHEMA = {
    "required": ["version", "rules"],
    "rules": {
        "type": "list",
        "each_required": ["description", "confidence"]
    }
}

CONTENT_LOG_SCHEMA = {
    "required": ["version", "entries"],
    "entries": {
        "type": "list",
        "each_required": ["title", "date"]
    }
}


# ========================
# 验证函数
# ========================

def check_required_keys(data: dict, required_keys: list[str], path: str) -> list[str]:
    """检查字典中是否包含所有必要的key。"""
    errors = []
    for key in required_keys:
        if key not in data:
            errors.append(f"[{path}] 缺少必填字段: '{key}'")
    return errors


def validate_config(data: dict) -> list[str]:
    """验证config.json格式。"""
    errors = []
    errors.extend(check_required_keys(data, CONFIG_SCHEMA["required"], "config"))

    if "style_db" in data:
        errors.extend(check_required_keys(data["style_db"],
                                          CONFIG_SCHEMA["style_db"]["required"],
                                          "config.style_db"))
        threshold = data["style_db"].get("confidence_threshold")
        if threshold is not None and not (0 <= float(threshold) <= 1):
            errors.append("[config.style_db] confidence_threshold 应在0-1之间")

    if "content_log" in data:
        errors.extend(check_required_keys(data["content_log"],
                                          CONFIG_SCHEMA["content_log"]["required"],
                                          "config.content_log"))

    if "platforms" in data:
        if not isinstance(data["platforms"], dict) or len(data["platforms"]) == 0:
            errors.append("[config.platforms] 至少应配置一个平台")

    return errors


def validate_persona(data: dict) -> list[str]:
    """验证persona.json格式。"""
    errors = []
    errors.extend(check_required_keys(data, PERSONA_SCHEMA["required"], "persona"))

    if "positioning" in data:
        errors.extend(check_required_keys(data["positioning"],
                                          PERSONA_SCHEMA["positioning"]["required"],
                                          "persona.positioning"))

    if "content_mix" in data:
        mix = data["content_mix"]
        if "lines" not in mix:
            errors.append("[persona.content_mix] 缺少 'lines' 字段")
        else:
            lines = mix["lines"]
            if not isinstance(lines, list):
                errors.append("[persona.content_mix.lines] 应为数组")
            else:
                for i, line in enumerate(lines):
                    errors.extend(check_required_keys(
                        line,
                        PERSONA_SCHEMA["content_mix.lines"]["each_required"],
                        f"persona.content_mix.lines[{i}]"
                    ))
                # 权重之和检查
                weights = [line.get("weight", 0) for line in lines
                           if isinstance(line.get("weight"), (int, float))]
                if weights:
                    weight_sum = sum(weights)
                    if abs(weight_sum - 1.0) > 0.05:
                        errors.append(
                            f"[persona.content_mix.lines] 所有主线的weight之和为{weight_sum:.3f}，"
                            "应等于1.0（允许±0.05误差）"
                        )

    return errors


def validate_style_db(data: dict) -> list[str]:
    """验证style_db.json格式。"""
    errors = []
    errors.extend(check_required_keys(data, STYLE_DB_SCHEMA["required"], "style_db"))

    if "rules" in data:
        rules = data["rules"]
        if not isinstance(rules, list):
            errors.append("[style_db.rules] 应为数组")
        else:
            for i, rule in enumerate(rules):
                errors.extend(check_required_keys(
                    rule,
                    STYLE_DB_SCHEMA["rules"]["each_required"],
                    f"style_db.rules[{i}]"
                ))
                # 置信度范围检查
                confidence = rule.get("confidence")
                if confidence is not None:
                    try:
                        if not (0 <= float(confidence) <= 1):
                            errors.append(f"[style_db.rules[{i}]] confidence 应在0-1之间")
                    except (TypeError, ValueError):
                        errors.append(f"[style_db.rules[{i}]] confidence 应为数字")

    return errors


def validate_content_log(data: dict) -> list[str]:
    """验证content_log.json格式。"""
    errors = []
    errors.extend(check_required_keys(data, CONTENT_LOG_SCHEMA["required"], "content_log"))

    if "entries" in data:
        entries = data["entries"]
        if not isinstance(entries, list):
            errors.append("[content_log.entries] 应为数组")
        else:
            for i, entry in enumerate(entries):
                errors.extend(check_required_keys(
                    entry,
                    CONTENT_LOG_SCHEMA["entries"]["each_required"],
                    f"content_log.entries[{i}]"
                ))

    return errors


# ========================
# 主验证流程
# ========================

VALIDATORS = {
    "config.json": validate_config,
    "persona.json": validate_persona,
    "style_db.json": validate_style_db,
    "content_log.json": validate_content_log
}


def validate_all(shared_dir: str) -> bool:
    """
    验证shared/目录下所有JSON文件。

    Args:
        shared_dir: shared目录路径

    Returns:
        所有文件验证通过返回True，否则False
    """
    shared_path = Path(shared_dir)
    all_passed = True
    total_errors = 0

    print(f"=== 验证 shared/ 目录: {shared_path.resolve()} ===\n")

    for filename, validator in VALIDATORS.items():
        file_path = shared_path / filename
        print(f"📄 {filename}")

        if not file_path.exists():
            print(f"  ❌ 文件不存在: {file_path}")
            all_passed = False
            total_errors += 1
            continue

        # 解析JSON
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"  ❌ JSON解析失败: {e}")
            all_passed = False
            total_errors += 1
            continue

        # 运行schema验证
        errors = validator(data)

        if errors:
            all_passed = False
            total_errors += len(errors)
            for err in errors:
                print(f"  ❌ {err}")
        else:
            print(f"  ✅ 验证通过")

        print()

    # 汇总
    if all_passed:
        print("=" * 40)
        print("✅ 所有文件验证通过！shared/基础设施就绪。")
    else:
        print("=" * 40)
        print(f"❌ 发现 {total_errors} 个问题，请按上述提示修复。")

    return all_passed


def main():
    parser = argparse.ArgumentParser(description="验证shared/目录下的JSON文件格式")
    parser.add_argument(
        "--dir", "-d", default="shared",
        help="shared目录路径（默认: shared）"
    )
    args = parser.parse_args()

    passed = validate_all(args.dir)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
