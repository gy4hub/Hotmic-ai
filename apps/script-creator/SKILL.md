---
name: hotmic-script-creator
description: >
  口播脚本创作引擎。从选题到完整9件套交付（双平台脚本+合规自检+标题+封面+简介+Tags+首评）。
  内置采访流程挖掘创作者独家视角，支持传播款/收藏款两种脚本结构，自动加载风格学习库适配创作者偏好。
  当用户说"写稿""出脚本""创作""帮我策划一篇内容""写口播""给我写个视频脚本""这个选题帮我写""出一篇"
  或给出选题信息、标题、话题方向时立即使用。是 HotMic AI（开麦） 套件的核心模块，优先级最高。
metadata:
  openclaw:
    commands:
      - name: /hotmic-write
        description: 从选题生成口播脚本 9 件套
        usage: /hotmic-write <选题标题或话题方向>
      - name: /hotmic-publish-pack
        description: 从脚本生成各平台发布包
        usage: /hotmic-publish-pack <脚本文件路径>
    dependencies:
      - python3
    tags:
      - writing
      - content-creation
      - video-script
      - chinese
  cowork:
    slot: on_demand
    requires_files: true
    output_format: markdown
    examples:
      - 帮我把这个选题写成脚本
      - 出一篇关于医保集采的视频稿
      - 这个选题帮我写成视频号和抖音双平台版本
---

# hotmic-script-creator — 口播脚本创作引擎

## 概述

从选题到完整9件套交付的口播脚本创作引擎。内置采访流程、合规自检、双平台适配。
这是整个 HotMic AI（开麦）套件的**核心差异化模块**——方法论是护城河。

## 快速开始

```bash
# 加载风格规则（创作前必须执行）
python scripts/load_style_rules.py --db ../../shared/style_db.json

# 创作完成后生成发布包
python scripts/generate_publish_pack.py --input output/script.md --output output/publish_pack/
```

## 工作流程

详见 `references/methodology.md`

## 文件结构

```
hotmic-script-creator/
├── SKILL.md                          # 本文件
├── references/
│   ├── methodology.md                # 前置四件事+创作七步法完整说明
│   ├── spread_template.md            # 传播款脚本结构模板
│   ├── collect_template.md           # 收藏款脚本结构模板
│   ├── compliance_rules.md           # 合规红线完整清单
│   └── platform_diff.md              # 视频号vs抖音差异化规则
└── scripts/
    ├── load_style_rules.py           # 从style_db.json加载高置信度规则
    └── generate_publish_pack.py      # 从script.md生成平台发布包
```

## 输出文件

- `output/script.md` — 完整9件套脚本正文
- `output/script_meta.json` — 元数据（选题、类型、合规结果）
- `output/publish_pack/wechat_video.txt` — 视频号复制粘贴包
- `output/publish_pack/douyin.txt` — 抖音复制粘贴包

执行完成后，内容条目自动写入 `../../shared/content_log.json`。
