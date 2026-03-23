#!/usr/bin/env python3
"""
diff_analyzer.py
文本 diff 分析：识别原稿与改稿之间的所有修改点。
输出结构化的修改记录，供 classify_edit.py 进行分类。
"""

import difflib
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class EditPoint:
    """单个修改点的结构化表示"""
    edit_id: str                    # 修改点唯一ID
    original_text: str              # 原始文本
    revised_text: str               # 修改后文本
    original_line_start: int        # 原始行号（起始）
    original_line_end: int          # 原始行号（结束）
    context_before: str             # 前文上下文（2行）
    context_after: str              # 后文上下文（2行）
    char_count_original: int        # 原始字符数
    char_count_revised: int         # 修改后字符数
    category: Optional[str] = None  # 分类（由 classify_edit.py 填充）


def load_text(path: str) -> str:
    """读取文本文件"""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def calculate_edit_ratio(original: str, revised: str) -> float:
    """
    计算改稿比例（修改字数/原始总字数）。
    用于统计 style_db 中的 edit_ratio_history。
    """
    original_chars = len(original.replace("\n", "").replace(" ", ""))
    if original_chars == 0:
        return 0.0

    # 使用 difflib 计算实际变更量
    matcher = difflib.SequenceMatcher(None, original, revised)
    changed_chars = sum(
        max(j2 - j1, i2 - i1)
        for opcode, i1, i2, j1, j2 in matcher.get_opcodes()
        if opcode != "equal"
    )
    return min(changed_chars / original_chars, 1.0)


def extract_edit_points(original: str, revised: str, diff_id: str = "diff") -> List[EditPoint]:
    """
    提取两个文本之间的所有修改点。

    Args:
        original: 原始文本
        revised: 修改后文本
        diff_id: diff 标识符（用于生成 edit_id）

    Returns:
        EditPoint 列表
    """
    original_lines = original.splitlines(keepends=True)
    revised_lines = revised.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(None, original_lines, revised_lines, autojunk=False)
    opcodes = matcher.get_opcodes()

    edit_points = []
    edit_counter = 0

    for opcode, i1, i2, j1, j2 in opcodes:
        if opcode == "equal":
            continue

        # 提取上下文（前后各2行）
        ctx_start = max(0, i1 - 2)
        ctx_before = "".join(original_lines[ctx_start:i1])
        ctx_end = min(len(original_lines), i2 + 2)
        ctx_after = "".join(original_lines[i2:ctx_end])

        original_text = "".join(original_lines[i1:i2])
        revised_text = "".join(revised_lines[j1:j2])

        edit_counter += 1
        edit_point = EditPoint(
            edit_id=f"{diff_id}_edit{edit_counter:03d}",
            original_text=original_text.strip(),
            revised_text=revised_text.strip(),
            original_line_start=i1 + 1,
            original_line_end=i2,
            context_before=ctx_before.strip(),
            context_after=ctx_after.strip(),
            char_count_original=len(original_text.replace("\n", "")),
            char_count_revised=len(revised_text.replace("\n", "")),
        )
        edit_points.append(edit_point)

    return edit_points


def merge_adjacent_edits(edit_points: List[EditPoint], gap_threshold: int = 3) -> List[EditPoint]:
    """
    合并距离过近的修改点，避免将一个大改拆成多个小改。
    gap_threshold：相邻两个 edit 之间允许的最大行间距
    """
    if len(edit_points) <= 1:
        return edit_points

    merged = [edit_points[0]]
    for current in edit_points[1:]:
        prev = merged[-1]
        gap = current.original_line_start - prev.original_line_end
        if gap <= gap_threshold:
            # 合并
            merged[-1] = EditPoint(
                edit_id=prev.edit_id,
                original_text=prev.original_text + "\n" + current.original_text,
                revised_text=prev.revised_text + "\n" + current.revised_text,
                original_line_start=prev.original_line_start,
                original_line_end=current.original_line_end,
                context_before=prev.context_before,
                context_after=current.context_after,
                char_count_original=prev.char_count_original + current.char_count_original,
                char_count_revised=prev.char_count_revised + current.char_count_revised,
            )
        else:
            merged.append(current)

    return merged


def analyze_diff(
    original_path: str,
    revised_path: str,
    diff_id: str = None,
    output_path: str = None,
) -> dict:
    """
    主分析函数：加载文件，提取修改点，输出分析结果。

    Returns:
        分析结果字典
    """
    original = load_text(original_path)
    revised = load_text(revised_path)

    if diff_id is None:
        from datetime import datetime
        diff_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    edit_ratio = calculate_edit_ratio(original, revised)
    edit_points = extract_edit_points(original, revised, diff_id)
    edit_points = merge_adjacent_edits(edit_points)

    result = {
        "diff_id": diff_id,
        "original_path": original_path,
        "revised_path": revised_path,
        "edit_ratio": round(edit_ratio, 4),
        "total_edits": len(edit_points),
        "original_char_count": len(original.replace("\n", "")),
        "revised_char_count": len(revised.replace("\n", "")),
        "edit_points": [asdict(ep) for ep in edit_points],
    }

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"diff 分析结果已写入: {output_path}")

    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="文本 diff 分析")
    parser.add_argument("--original", required=True, help="原稿路径")
    parser.add_argument("--revised", required=True, help="改稿路径")
    parser.add_argument("--diff-id", default=None, help="diff ID（不指定则自动生成）")
    parser.add_argument("--output", default=None, help="输出 JSON 路径")
    parser.add_argument("--summary", action="store_true", help="只打印摘要")

    args = parser.parse_args()

    result = analyze_diff(
        original_path=args.original,
        revised_path=args.revised,
        diff_id=args.diff_id,
        output_path=args.output,
    )

    if args.summary or not args.output:
        print(f"diff ID: {result['diff_id']}")
        print(f"改稿比例: {result['edit_ratio'] * 100:.1f}%")
        print(f"修改点数: {result['total_edits']}")
        if not args.summary:
            for ep in result["edit_points"]:
                print(f"\n--- {ep['edit_id']} (行 {ep['original_line_start']}-{ep['original_line_end']}) ---")
                print(f"原文: {ep['original_text'][:80]}{'...' if len(ep['original_text']) > 80 else ''}")
                print(f"改后: {ep['revised_text'][:80]}{'...' if len(ep['revised_text']) > 80 else ''}")


if __name__ == "__main__":
    main()
