#!/usr/bin/env python3
"""
init_project.py — 一键初始化 HotMic AI 项目目录结构

在指定目录下创建完整的 hotmic-ai/ 目录结构，包括：
- shared/ 基础数据文件（从模板初始化）
- skills/ 各技能目录的符号链接或空占位目录
- output/ 生成内容输出目录

用法:
  python init_project.py                          # 在当前目录初始化
  python init_project.py --dir /path/to/project  # 在指定目录初始化
  python init_project.py --force                  # 覆盖已有文件
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


# =========================
# 默认JSON模板
# =========================

DEFAULT_CONFIG = {
    "feishu": {
        "app_id": "",
        "app_secret_env": "FEISHU_APP_SECRET",
        "folder_token": "",
        "doc_name_pattern": "MMDD 标题关键词"
    },
    "style_db": {
        "path": "shared/style_db.json",
        "confidence_threshold": 0.6
    },
    "content_log": {
        "path": "shared/content_log.json"
    },
    "persona": {
        "path": "shared/persona.json"
    },
    "platforms": {
        "wechat_video": {
            "max_title_length": 30,
            "max_description_length": 1000,
            "max_tags": 10,
            "script_target_length": 1000
        },
        "douyin": {
            "max_title_length": 55,
            "max_description_length": 500,
            "max_tags": 10,
            "script_target_length_ratio": 0.82
        }
    }
}

DEFAULT_PERSONA = {
    "account_id": "default",
    "positioning": {
        "one_liner": "[身份] + [讲什么] + [讲给谁]",
        "identity": "请替换为创作者身份（如：内科医生、健康博主）",
        "topic": "请替换为内容领域（如：医疗科普、健康消费）",
        "audience": "请替换为目标受众（如：关注健康的中产家庭用户）"
    },
    "capability_boundary": {
        "can_discuss": ["请填写能讲的话题领域"],
        "never_touch": [
            "无执照行医建议",
            "具体诊断结论",
            "投资、理财、保险相关建议"
        ]
    },
    "dual_audience_model": {
        "decision_layer": {
            "who": "决策层受众描述（如：家庭健康决策者）",
            "drives": "决定选题方向"
        },
        "spread_layer": {
            "who": "传播层受众描述（如：泛健康关注者）",
            "drives": "决定语言风格"
        }
    },
    "content_mix": {
        "lines": [
            {
                "name": "内容主线一",
                "weight": 0.5,
                "description": "描述主线定位和目标"
            },
            {
                "name": "内容主线二",
                "weight": 0.3,
                "description": "描述主线定位和目标"
            },
            {
                "name": "内容主线三",
                "weight": 0.2,
                "description": "描述主线定位和目标"
            }
        ]
    },
    "creator_notes": "创作者个性化备注（风格偏好、禁忌词、特殊要求等）"
}

DEFAULT_STYLE_DB = {
    "version": "1.0",
    "last_updated": "",
    "statistics": {
        "total_diffs_analyzed": 0,
        "avg_edit_ratio": 0.0,
        "edit_ratio_history": []
    },
    "rules": []
}

DEFAULT_CONTENT_LOG = {
    "version": "1.0",
    "entries": []
}


# =========================
# 目录结构定义
# =========================

DIRECTORY_STRUCTURE = [
    "shared",
    "skills",
    "skills/hotmic-video-cutter",
    "skills/hotmic-script-creator",
    "skills/hotmic-publish-kit",
    "skills/hotmic-style-learner",
    "skills/hotmic-review-engine",
    "output",
    "output/scripts",
    "output/publish_packs",
    "output/video",
    "output/reviews",
]

SHARED_FILES = {
    "shared/config.json": DEFAULT_CONFIG,
    "shared/persona.json": DEFAULT_PERSONA,
    "shared/style_db.json": DEFAULT_STYLE_DB,
    "shared/content_log.json": DEFAULT_CONTENT_LOG
}


def create_directory(path: Path, dry_run: bool = False) -> bool:
    """创建目录，返回是否新建。"""
    if path.exists():
        return False
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)
    return True


def write_json_file(path: Path, data: dict, force: bool = False, dry_run: bool = False) -> str:
    """
    写入JSON文件。

    Args:
        path: 文件路径
        data: 数据字典
        force: 是否覆盖已有文件
        dry_run: 只打印不实际写入

    Returns:
        "created" / "skipped" / "overwritten"
    """
    if path.exists() and not force:
        return "skipped"

    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 如果是content_log，更新version时间戳
        if path.name == "style_db.json":
            data_copy = dict(data)
            data_copy["last_updated"] = datetime.now().strftime("%Y-%m-%d")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data_copy, f, ensure_ascii=False, indent=2)

    return "overwritten" if path.exists() else "created"


def create_readme(base_path: Path, dry_run: bool = False):
    """在output/下创建README提示文件。"""
    readme_path = base_path / "output" / "README.md"
    if readme_path.exists():
        return
    content = """# output/ — HotMic AI 生成内容输出

此目录由各Skill自动生成文件，请勿手动修改。

## 目录说明

| 目录 | 用途 |
|------|------|
| `scripts/` | hotmic-script-creator 生成的脚本 |
| `publish_packs/` | hotmic-publish-kit 生成的发布包 |
| `video/` | hotmic-video-cutter 生成的粗剪视频 |
| `reviews/` | hotmic-review-engine 生成的复盘报告 |
"""
    if not dry_run:
        readme_path.parent.mkdir(parents=True, exist_ok=True)
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(content)


def init_project(target_dir: str, force: bool = False, dry_run: bool = False):
    """
    初始化HotMic AI项目目录结构。

    Args:
        target_dir: 目标目录路径
        force: 是否强制覆盖已有JSON文件
        dry_run: 只打印不实际创建
    """
    base = Path(target_dir).resolve()
    mode = "[DRY-RUN] " if dry_run else ""

    print(f"{'='*50}")
    print(f"{mode}初始化 HotMic AI 项目结构")
    print(f"目标目录: {base}")
    print(f"{'='*50}\n")

    # 创建目录结构
    print("📁 创建目录结构:")
    dirs_created = 0
    for rel_dir in DIRECTORY_STRUCTURE:
        dir_path = base / rel_dir
        is_new = create_directory(dir_path, dry_run)
        status = "新建" if is_new else "已存在"
        icon = "✅" if is_new else "⏭️ "
        print(f"  {icon} {rel_dir}/ [{status}]")
        if is_new:
            dirs_created += 1

    print()

    # 写入JSON模板文件
    print("📄 初始化配置文件:")
    files_created = 0
    files_skipped = 0

    for rel_file, template in SHARED_FILES.items():
        file_path = base / rel_file
        status = write_json_file(file_path, template, force, dry_run)
        icons = {"created": "✅", "skipped": "⏭️ ", "overwritten": "🔄"}
        labels = {"created": "新建", "skipped": "已存在（跳过）", "overwritten": "已覆盖"}
        print(f"  {icons[status]} {rel_file} [{labels[status]}]")
        if status in ("created", "overwritten"):
            files_created += 1
        else:
            files_skipped += 1

    # 创建output README
    create_readme(base, dry_run)

    print()
    print(f"{'='*50}")
    print(f"✅ 初始化完成！")
    print(f"   新建目录: {dirs_created} 个")
    print(f"   新建/更新文件: {files_created} 个")
    if files_skipped:
        print(f"   跳过已有文件: {files_skipped} 个（使用 --force 覆盖）")
    print()
    print("下一步：")
    print(f"  1. 编辑 {base}/shared/persona.json，填入创作者定位")
    print(f"  2. 编辑 {base}/shared/config.json，配置飞书和平台参数")
    print(f"  3. 运行 python shared/validate_shared.py 验证配置")


def main():
    parser = argparse.ArgumentParser(
        description="一键初始化HotMic AI项目目录结构"
    )
    parser.add_argument(
        "--dir", "-d", default=".",
        help="目标目录路径（默认: 当前目录）"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="强制覆盖已有JSON文件（谨慎使用）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只打印将执行的操作，不实际创建"
    )
    args = parser.parse_args()

    init_project(args.dir, args.force, args.dry_run)


if __name__ == "__main__":
    main()
