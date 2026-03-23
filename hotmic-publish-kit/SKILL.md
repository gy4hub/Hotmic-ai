---
name: hotmic-publish-kit
description: >
  内容发布工具包。将定稿脚本归档到飞书云文档，同时生成可直接复制到平台后台的发布物料包。
  当用户说"发到飞书""归档""定稿了""生成发布包""发布""准备发布""内容做好了"时立即使用。
  一次命令完成：飞书归档 + 视频号发布包 + 抖音发布包，三件事一步到位。
  是 HotMic AI（开麦） 套件的发布模块。
metadata:
  openclaw:
    dependencies:
      - python3
    env:
      - FEISHU_APP_SECRET
    tags:
      - publishing
      - feishu
      - content-creation
---

# hotmic-publish-kit — 内容发布工具包

## 概述

将定稿脚本归档到飞书云文档，同时生成两份"复制粘贴即用"的平台发布包。

## 快速开始

```bash
# 完整发布流程（飞书归档 + 生成发布包）
python scripts/publish_to_feishu.py --input output/script.md --title "MMDD 关键词"

# 只生成发布包（不归档飞书）
python scripts/generate_publish_pack.py --input output/script.md --output output/publish_pack/
```

## 环境变量配置

```bash
export FEISHU_APP_SECRET="your_feishu_app_secret"
```

App ID 和 folder token 已在 `../shared/config.json` 中配置：
- App ID: `cli_a90560c5a239dbd6`
- 目标文件夹 Token: `T257f7rBel8LEvd1A5gcbKrznke`

## 文件结构

```
hotmic-publish-kit/
├── SKILL.md
├── scripts/
│   ├── publish_to_feishu.py        # 飞书归档（含完整9件套）
│   └── generate_publish_pack.py    # 从script.md提取发布包
└── references/
    └── platform_specs.md           # 各平台字数限制、Tag规范等
```

## 输出文件

- `output/publish_pack/wechat_video.txt` — 视频号发布包（复制粘贴即用）
- `output/publish_pack/douyin.txt` — 抖音发布包（复制粘贴即用）
- 飞书文档链接（归档后自动输出）

## 命名规范

飞书文档命名格式：`MMDD 标题关键词`
例：`0323 外泌体风险提示`
