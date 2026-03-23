#!/usr/bin/env python3
"""
generate_publish_pack.py
从完整的 9件套 script.md 中提取两份"复制粘贴即用"的发布包。
输出：
  - output/publish_pack/wechat_video.txt
  - output/publish_pack/douyin.txt

本文件是 hotmic-publish-kit 模块专属版本。
与 hotmic-script-creator 中的同名文件功能相同，为发布模块独立提供，避免跨模块依赖。

使用方式：
  python scripts/generate_publish_pack.py --input output/script.md --output output/publish_pack/
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime


# ─── 章节解析 ──────────────────────────────────────────────────────────────

SECTION_MAP = {
    "wechat_video_script":    ["## 视频号版脚本"],
    "douyin_script":          ["## 抖音版脚本"],
    "titles_wechat":          ["### 视频号", "### 视频号标题"],
    "titles_douyin":          ["### 抖音", "### 抖音标题"],
    "cover":                  ["## 视频封面标题"],
    "desc_wechat":            ["### 视频号简介"],
    "desc_douyin":            ["### 抖音简介"],
    "tags_wechat":            ["### 视频号Tags", "### 视频号 Tags"],
    "tags_douyin":            ["### 抖音Tags", "### 抖音 Tags"],
    "comment_wechat":         ["### 视频号首评"],
    "comment_douyin":         ["### 抖音首评"],
}


def parse_script_md(script_path: str) -> dict:
    """解析 script.md，提取各章节内容"""
    with open(script_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    sections = {}
    current_section = None
    current_lines = []

    heading_to_key = {}
    for key, headings in SECTION_MAP.items():
        for heading in headings:
            heading_to_key[heading.strip().lower()] = key

    def save_current():
        if current_section:
            sections[current_section] = "\n".join(current_lines).strip()

    for line in lines:
        stripped = line.strip()
        matched_key = None
        for heading, key in heading_to_key.items():
            if stripped.lower() == heading.lower():
                matched_key = key
                break

        if matched_key:
            save_current()
            current_section = matched_key
            current_lines = []
        elif current_section:
            current_lines.append(line)

    save_current()
    return sections


def extract_titles(text: str) -> list:
    """从标题建议文本中提取编号标题"""
    titles = []
    for line in text.split("\n"):
        line = line.strip()
        match = re.match(r"^[1-9][.、．]\s*(.+)$", line)
        if match:
            titles.append(match.group(1).strip())
    return titles


def extract_cover_blocks(text: str) -> list:
    """从封面标题文本中提取封面方案"""
    covers = []
    current_cover = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            if current_cover:
                covers.append(current_cover)
                current_cover = {}
            continue
        if re.match(r"^(套[A-Za-z一二三]|方案[一二三\d])[：:]\s*", line):
            if current_cover:
                covers.append(current_cover)
            current_cover = {"label": line}
        elif "主标题" in line:
            current_cover["main"] = re.sub(r"^主标题[（(]\S+[）)][：:]\s*", "", line).strip("[]【】")
        elif "副标题" in line:
            current_cover["sub"] = re.sub(r"^副标题[（(]\S+[）)][：:]\s*", "", line).strip("[]【】")
    if current_cover:
        covers.append(current_cover)
    return covers


def format_cover_text(covers: list) -> str:
    """格式化封面方案"""
    if not covers:
        return "（请在 script.md 中填写封面标题）"
    lines = []
    for cover in covers:
        label = cover.get("label", "")
        main = cover.get("main", "")
        sub = cover.get("sub", "")
        if label:
            lines.append(label)
        if main:
            lines.append(f"  主标题（大字）：{main}")
        if sub:
            lines.append(f"  副标题（小字）：{sub}")
    return "\n".join(lines)


def validate_platform_specs(sections: dict, platform: str) -> list:
    """
    校验发布包是否符合平台规范。
    返回警告列表（不阻止生成，只提示）。
    """
    warnings = []

    if platform == "wechat_video":
        title_key, desc_key, tags_key = "titles_wechat", "desc_wechat", "tags_wechat"
        max_title = 30
        max_desc = 1000
    else:
        title_key, desc_key, tags_key = "titles_douyin", "desc_douyin", "tags_douyin"
        max_title = 55
        max_desc = 500

    # 校验标题长度
    titles = extract_titles(sections.get(title_key, ""))
    for i, title in enumerate(titles, 1):
        if len(title) > max_title:
            warnings.append(f"标题{i}超过{max_title}字限制（当前{len(title)}字）: {title}")

    # 校验简介长度
    desc = sections.get(desc_key, "")
    if len(desc) > max_desc:
        warnings.append(f"简介超过{max_desc}字限制（当前{len(desc)}字）")

    return warnings


WECHAT_TEMPLATE = """\
===== 视频号发布包 =====
生成时间：{generated_at}

📌 标题（3选1）：
{titles}

📝 简介：
{description}

🏷 Tags（复制全部）：
{tags}

🖼 封面标题建议：
{cover}

💬 首评（发布后立即评论置顶）：
{first_comment}

===== 复制到此结束 =====
"""

DOUYIN_TEMPLATE = """\
===== 抖音发布包 =====
生成时间：{generated_at}

📌 标题（3选1）：
{titles}

📝 简介：
{description}

🏷 Tags（复制全部）：
{tags}

🖼 封面标题建议：
{cover}

💬 首评（发布后立即评论置顶）：
{first_comment}

===== 复制到此结束 =====
"""


def build_pack(sections: dict, platform: str) -> tuple[str, list]:
    """
    生成发布包内容。

    Returns:
        (发布包文本, 警告列表)
    """
    if platform == "wechat_video":
        title_key, desc_key, tags_key, comment_key = (
            "titles_wechat", "desc_wechat", "tags_wechat", "comment_wechat"
        )
        template = WECHAT_TEMPLATE
    else:
        title_key, desc_key, tags_key, comment_key = (
            "titles_douyin", "desc_douyin", "tags_douyin", "comment_douyin"
        )
        template = DOUYIN_TEMPLATE

    titles = extract_titles(sections.get(title_key, ""))
    title_text = (
        "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
        if titles
        else "（未解析到标题）"
    )

    covers = extract_cover_blocks(sections.get("cover", ""))
    cover_text = format_cover_text(covers)

    warnings = validate_platform_specs(sections, platform)

    content = template.format(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        titles=title_text,
        description=sections.get(desc_key, "（未找到简介）"),
        tags=sections.get(tags_key, "（未找到Tags）"),
        cover=cover_text,
        first_comment=sections.get(comment_key, "（未找到首评内容）"),
    )

    return content, warnings


def write_pack(content: str, output_path: str) -> None:
    """写入发布包文件"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ 已生成: {output_path}")


def update_content_log(script_path: str, meta_path: str = None) -> None:
    """将内容条目写入 shared/content_log.json"""
    project_root = Path(__file__).parent.parent.parent
    log_path = project_root / "shared" / "content_log.json"

    meta = {}
    if meta_path and Path(meta_path).exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)
    else:
        log = {"version": "1.0", "entries": []}

    # 检查是否已存在该脚本的条目
    script_str = str(script_path)
    for entry in log.get("entries", []):
        if entry.get("script_path") == script_str:
            entry["publish_pack_generated"] = True
            entry["publish_pack_generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)
            return

    # 新增条目
    entry = {
        "id": meta.get("id", f"content_{datetime.now().strftime('%Y%m%d_%H%M%S')}"),
        "title": meta.get("title", Path(script_path).stem),
        "content_type": meta.get("content_type", "unknown"),
        "created_at": meta.get("created_at", datetime.now().strftime("%Y-%m-%d")),
        "script_path": script_str,
        "platforms": meta.get("platforms", ["wechat_video", "douyin"]),
        "compliance_passed": meta.get("compliance_passed", None),
        "publish_pack_generated": True,
        "publish_pack_generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    log["entries"].append(entry)

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

    print(f"✅ 已写入 content_log.json: {entry['id']}")


def main():
    parser = argparse.ArgumentParser(description="从 script.md 生成平台发布包")
    parser.add_argument("--input", required=True, help="script.md 路径")
    parser.add_argument("--output", default="output/publish_pack", help="输出目录")
    parser.add_argument("--meta", default=None, help="script_meta.json 路径（可选）")
    parser.add_argument("--no-log", action="store_true", help="不写入 content_log.json")

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"错误：找不到输入文件: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"📄 解析脚本: {args.input}")
    sections = parse_script_md(args.input)

    # 生成视频号包
    wechat_content, wechat_warnings = build_pack(sections, "wechat_video")
    write_pack(wechat_content, os.path.join(args.output, "wechat_video.txt"))
    if wechat_warnings:
        print("⚠️  视频号规范警告：")
        for w in wechat_warnings:
            print(f"   - {w}")

    # 生成抖音包
    douyin_content, douyin_warnings = build_pack(sections, "douyin")
    write_pack(douyin_content, os.path.join(args.output, "douyin.txt"))
    if douyin_warnings:
        print("⚠️  抖音规范警告：")
        for w in douyin_warnings:
            print(f"   - {w}")

    # 更新 content log
    if not args.no_log:
        meta_path = args.meta
        if meta_path is None:
            guessed = Path(args.input).parent / "script_meta.json"
            if guessed.exists():
                meta_path = str(guessed)
        update_content_log(args.input, meta_path)

    print(f"\n🎉 发布包生成完成！")
    print(f"   视频号: {args.output}/wechat_video.txt")
    print(f"   抖音:   {args.output}/douyin.txt")


if __name__ == "__main__":
    main()
