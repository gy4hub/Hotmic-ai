---
name: hotmic-review-engine
description: >
  自媒体内容数据复盘工具。导入平台数据后自动生成复盘报告、趋势分析和策略建议。
  输出选题权重调整补丁和创作风格调整建议，实现数据驱动的内容迭代。
  当用户说"复盘""看看数据""分析最近的内容"或上传平台数据文件时使用。
  是 HotMic AI（开麦） 套件的一部分。
metadata:
  openclaw:
    commands:
      - name: /hotmic-review
        description: 导入平台数据并生成复盘报告
        usage: /hotmic-review <数据文件路径> [--period week|month]
      - name: /hotmic-patches
        description: 生成选题权重调整补丁
        usage: /hotmic-patches <数据文件路径>
    dependencies:
      - python3
    tags:
      - analytics
      - content-creation
      - reporting
  cowork:
    slot: on_demand
    requires_files: true
    output_format: markdown
    examples:
      - 复盘一下最近的视频数据
      - 用这份导出的后台数据出一版周报
      - 看看最近哪些题材更值得继续做
---

# hotmic-review-engine — 自媒体数据复盘引擎

## 概述

从平台后台导出的数据（视频号、抖音等）自动生成深度复盘报告，提供可操作的选题策略建议。
输出三类产物：单条复盘、周期性报告（周报/月报）、选题权重调整补丁（JSON格式）。

## 快速开始

```bash
# 导入数据（支持JSON/CSV）
python scripts/import_data.py --input data.json --output content_data.json

# 单条复盘
python scripts/analyze_single.py --data content_data.json --id 0 --output report.md

# 周报/月报
python scripts/analyze_period.py --data content_data.json --period week --output weekly_report.md

# 生成权重调整补丁
python scripts/generate_patches.py --data content_data.json --output patches.json

# 导出完整报告
python scripts/export_report.py --data content_data.json --output full_report.md
```

## 输入数据格式

```json
{
  "platform": "视频号",
  "entries": [
    {
      "title": "315点名的外泌体",
      "date": "2026-03-18",
      "content_line": "健康消费避坑",
      "content_type": "传播款",
      "views": 460000,
      "completion_rate": 0.42,
      "likes": 8500,
      "comments": 1200,
      "shares": 3400,
      "followers_gained": 850,
      "publish_time": "20:00"
    }
  ]
}
```

## 文件结构

```
hotmic-review-engine/
├── SKILL.md
├── scripts/
│   ├── import_data.py           # 数据导入（JSON/CSV/手动）
│   ├── analyze_single.py        # 单条复盘
│   ├── analyze_period.py        # 周报/月报
│   ├── generate_patches.py      # 生成权重调整补丁
│   └── export_report.py         # 导出Markdown报告
└── references/
    └── metrics_guide.md         # 指标计算方式和基准值
```

## 输出说明

| 产物 | 格式 | 说明 |
|------|------|------|
| 单条复盘报告 | Markdown | 数据概览 + 归因分析 + 同类对比 |
| 周报/月报 | Markdown | 趋势分析 + ROI对比 + 最佳发布时间 |
| 权重调整补丁 | JSON | 选题权重delta + 风格规则建议 |

## 指标说明

详见 `references/metrics_guide.md`
