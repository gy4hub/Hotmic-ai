---
name: hotmic-video-cutter
description: >
  AI口播视频粗剪工具。自动检测并删除重复段落（同一句话录了多遍，保留最流利版本），
  去除过长静音。支持"脚本对齐"模式（提供定稿脚本时精度更高）。
  当用户说"剪视频""粗剪""去重复""帮我剪口播"或上传视频文件时使用。
  是 HotMic AI（开麦） 套件的一部分。
metadata:
  openclaw:
    dependencies:
      - ffmpeg
      - python3
    env:
      - GROQ_API_KEY
    install: scripts/install_deps.sh
    tags:
      - video
      - editing
      - speech
      - content-creation
---

# hotmic-video-cutter — AI口播视频粗剪工具

## 概述

口播视频粗剪自动化工具。核心功能：**检测并剪除重复段落**（同一句话录了多遍，自动保留最流利版本），辅助功能：去除过长静音。支持"脚本对齐"精准模式（提供定稿脚本时）和"无脚本"自动检测模式。

## 前置条件

- FFmpeg（已安装在系统中）
- Python 3.8+
- Groq API Key（设置环境变量 `GROQ_API_KEY`）
- 运行 `scripts/install_deps.sh` 安装Python依赖

## 快速开始

```bash
# 安装依赖
bash scripts/install_deps.sh

# 有脚本模式（推荐，精度更高）
python scripts/extract_audio.py --input video.MOV --output audio.wav
python scripts/transcribe_groq.py --input audio.wav --output transcript.json
python scripts/align_script.py --transcript transcript.json --script script.md --output alignment.json
python scripts/detect_repeats.py --alignment alignment.json --output cut_decisions.json
python scripts/detect_silence.py --transcript transcript.json --decisions cut_decisions.json
python scripts/generate_review.py --decisions cut_decisions.json --transcript transcript.json --output cut_report.md
# 审核 cut_report.md 后执行剪辑
python scripts/execute_cut.py --input video.MOV --decisions cut_decisions.json --output video_cut.mp4

# 无脚本模式（自动检测重复）
python scripts/detect_repeats.py --transcript transcript.json --no-script --output cut_decisions.json
```

## 完整工作流

```
输入: video.MOV + script.md（可选）
  ↓
Step 1: extract_audio.py        → audio.wav
  ↓
Step 2: transcribe_groq.py      → transcript.json（含word/segment时间戳）
  ↓
Step 3: align_script.py         → alignment.json（脚本句↔转录段映射）
  ↓
Step 4: detect_repeats.py       → cut_decisions.json（重复检测+选优）
  ↓
Step 5: detect_silence.py       → cut_decisions.json（追加静音标记）
  ↓
Step 6: generate_review.py      → cut_report.md（人工审核）
  ↓
Step 7: execute_cut.py          → video_cut.mp4（最终粗剪视频）
```

## 文件结构

```
hotmic-video-cutter/
├── SKILL.md
├── scripts/
│   ├── extract_audio.py         # Step 1: FFmpeg提取音频
│   ├── transcribe_groq.py       # Step 2: Groq Whisper转录
│   ├── align_script.py          # Step 3: 脚本-转录对齐（核心算法）
│   ├── detect_repeats.py        # Step 4: 重复检测+综合评分选优
│   ├── detect_silence.py        # Step 5: 过长静音检测
│   ├── generate_review.py       # Step 6: 生成Markdown审核报告
│   ├── execute_cut.py           # Step 7: FFmpeg执行剪辑
│   └── install_deps.sh          # 一键安装依赖
├── references/
│   └── cut_rules.md             # 剪辑规则说明文档
├── assets/
│   └── review_template.html     # HTML审核界面（可选）
└── tests/
    ├── test_align_script.py
    ├── test_detect_repeats.py
    └── sample_data/
        ├── sample_transcript.json
        └── sample_script.md
```

## 输出文件

| 文件 | 说明 |
|------|------|
| `audio.wav` | 提取的16kHz单声道音频 |
| `transcript.json` | Groq Whisper转录结果（含时间戳） |
| `alignment.json` | 脚本句与转录段的对齐映射 |
| `cut_decisions.json` | 每段的保留/删除决策及原因 |
| `cut_report.md` | 人类可读的审核报告 |
| `video_cut.mp4` | 粗剪后的视频 |

## 重复检测算法说明

详见 `references/cut_rules.md`
