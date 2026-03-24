---
name: hotmic-style-learner
description: >
  创作风格自进化学习模块。自动分析用户对AI生成稿件的修改，提取写作偏好规则，
  累积到风格学习库中。高置信度规则自动注入下次创作，实现"越用越准"。
  当用户提交改稿、返回修改后的脚本、说"我改了一些"时自动触发。
  用户说"校准风格""看看学到了什么""调整偏好""回顾规则""规则管理"时进入手动校准模式。
  是 HotMic AI（开麦） 套件的进化引擎，让系统越用越懂创作者。
metadata:
  openclaw:
    commands:
      - name: /hotmic-learn
        description: 分析改稿差异并提取写作偏好规则
        usage: /hotmic-learn <原稿路径> <改稿路径>
      - name: /hotmic-calibrate
        description: 手动校准风格规则库
        usage: /hotmic-calibrate
    dependencies:
      - python3
    tags:
      - learning
      - writing-style
      - personalization
      - content-creation
  cowork:
    slot: on_file_change
    requires_files: true
    output_format: json
    examples:
      - 我改了一些，你帮我学一下这些偏好
      - 校准一下我最近的写作风格
      - 看看这次改稿学到了什么规则
---

# hotmic-style-learner — 创作风格自进化学习模块

## 概述

从用户改稿行为中自动学习偏好，持续优化创作质量。
是系统"越用越准"的核心机制。

## 两种触发模式

### 自动模式（改稿时触发）
用户返回修改后的脚本时自动执行：
```bash
python scripts/update_style_db.py \
  --original output/script.md \
  --revised revised_script.md \
  --db ../../shared/style_db.json
```

### 手动校准模式（用户主动调用）
```bash
python scripts/calibrate.py --db ../../shared/style_db.json
```

## 文件结构

```
hotmic-style-learner/
├── SKILL.md
├── scripts/
│   ├── diff_analyzer.py        # 文本diff + 修改点识别
│   ├── classify_edit.py        # 修改分类（7类）
│   ├── rule_extractor.py       # 从diff中提取规则候选
│   ├── update_style_db.py      # 更新style_db.json（自动模式主入口）
│   ├── calibrate.py            # 手动校准流程
│   └── inject_rules.py         # 生成prompt补丁（供script-creator调用）
└── references/
    └── diff_categories.md      # 7类修改的定义、示例、识别规则
```

## 数据存储

所有规则存储在 `../../shared/style_db.json`，格式见 `references/diff_categories.md`。
