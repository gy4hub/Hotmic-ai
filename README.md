# HotMic AI（开麦）— 智能口播内容创作套件

> **HotMic** 是面向中文口播视频创作者的 AI 辅助套件，覆盖创作→剪辑→发布→复盘全链路。
> 兼容 [AgentSkills / ClawHub](https://openclaw.ai) 发布标准。

---

## 套件组成

| Skill | 功能 | 状态 |
|-------|------|------|
| `hotmic-script-creator` | 口播脚本创作（9件套交付） | ✅ 已完成 |
| `hotmic-video-cutter` | 视频粗剪（自动去重复段落） | ✅ 已完成 |
| `hotmic-publish-kit` | 发布包生成、多平台适配 | ✅ 已完成 |
| `hotmic-style-learner` | 风格学习库维护 | ✅ 已完成 |
| `hotmic-review-engine` | 数据复盘与策略建议 | ✅ 已完成 |

---

## 安装

### 前置条件

- Python 3.8+
- FFmpeg（仅 video-cutter 需要）
- Groq API Key（免费注册：https://console.groq.com）

### 快速安装

```bash
# 1. 克隆项目
git clone <repo-url>
cd Hotmic-ai

# 2. 初始化项目结构
python shared/init_project.py

# 3. 配置环境变量
export GROQ_API_KEY=your_groq_api_key_here

# 4. 安装 video-cutter 依赖
bash hotmic-video-cutter/scripts/install_deps.sh

# 5. 验证 shared/ 配置文件
python shared/validate_shared.py

# 6. 编辑创作者定位
# 打开 shared/persona.json，填入您的身份定位
```

---

## 使用说明

### 模块 A：video-cutter（口播视频粗剪）

**适用场景**：录完口播视频后，自动剪去重复段落（同一句话录了多遍）

```bash
cd hotmic-video-cutter/scripts

# Step 1: 提取音频
python extract_audio.py --input /path/to/video.MOV --output audio.wav

# Step 2: Groq Whisper 转录
python transcribe_groq.py --input audio.wav --output transcript.json

# Step 3 (有脚本): 脚本-转录对齐
python align_script.py --transcript transcript.json --script script.md --output alignment.json

# Step 4: 重复段检测 + 选优
python detect_repeats.py --alignment alignment.json --transcript transcript.json --output cut_decisions.json

# Step 5: 静音检测
python detect_silence.py --transcript transcript.json --decisions cut_decisions.json

# Step 6: 生成审核报告（人工确认）
python generate_review.py --decisions cut_decisions.json --transcript transcript.json --output cut_report.md

# Step 7: 执行剪辑
python execute_cut.py --input /path/to/video.MOV --decisions cut_decisions.json --output video_cut.mp4
```

**无脚本模式（未准备定稿脚本时）**:

```bash
python detect_repeats.py --transcript transcript.json --no-script --output cut_decisions.json
```

### 模块 B：review-engine（数据复盘）

**适用场景**：将平台后台数据导出后，生成复盘报告和选题策略建议

```bash
cd hotmic-review-engine/scripts

# 导入数据
python import_data.py --input platform_export.json --output content_data.json

# 单条复盘
python analyze_single.py --data content_data.json --id 0 --output single_report.md

# 周报（最近7天）
python analyze_period.py --data content_data.json --period week --output weekly.md

# 月报
python analyze_period.py --data content_data.json --period month --output monthly.md

# 生成选题权重调整补丁
python generate_patches.py --data content_data.json --output patches.json

# 导出完整报告
python export_report.py --data content_data.json --patches patches.json --output full_report.md
```

**输入数据格式（JSON）**:

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

### 模块 C：shared/ 基础设施

```bash
# 初始化新项目
python shared/init_project.py --dir /path/to/new-project

# 验证所有配置文件
python shared/validate_shared.py --dir shared/

# 查看帮助
python shared/init_project.py --help
```

---

## 运行测试

```bash
# video-cutter 单元测试
cd hotmic-video-cutter/tests
python -m pytest test_align_script.py test_detect_repeats.py -v

# review-engine 单元测试
cd hotmic-review-engine/tests
python -m pytest test_review_engine.py -v

# 运行全部测试
python -m pytest hotmic-video-cutter/tests/ hotmic-review-engine/tests/ -v
```

---

## 项目结构

```
Hotmic-ai/
├── shared/                          # 基础设施
│   ├── config.json                  # 平台配置
│   ├── persona.json                 # 创作者定位
│   ├── style_db.json               # 风格规则库
│   ├── content_log.json            # 内容发布记录
│   ├── validate_shared.py          # JSON验证脚本
│   └── init_project.py             # 项目初始化脚本
│
├── hotmic-video-cutter/             # 模块A: 视频粗剪
│   ├── SKILL.md                    # AgentSkills标准描述
│   ├── scripts/
│   │   ├── extract_audio.py        # Step 1: 音频提取
│   │   ├── transcribe_groq.py      # Step 2: Groq Whisper转录
│   │   ├── align_script.py         # Step 3: 脚本-转录对齐（核心）
│   │   ├── detect_repeats.py       # Step 4: 重复检测+选优
│   │   ├── detect_silence.py       # Step 5: 静音处理
│   │   ├── generate_review.py      # Step 6: 审核报告
│   │   ├── execute_cut.py          # Step 7: FFmpeg剪辑
│   │   └── install_deps.sh
│   ├── references/cut_rules.md
│   └── tests/
│       ├── test_align_script.py
│       ├── test_detect_repeats.py
│       └── sample_data/
│
├── hotmic-review-engine/            # 模块B: 数据复盘
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── import_data.py          # 数据导入
│   │   ├── analyze_single.py       # 单条复盘
│   │   ├── analyze_period.py       # 周报/月报
│   │   ├── generate_patches.py     # 权重调整补丁
│   │   └── export_report.py        # 完整报告导出
│   ├── references/metrics_guide.md
│   └── tests/
│       ├── test_review_engine.py
│       └── sample_data/
│
├── hotmic-script-creator/           # 脚本创作引擎
├── hotmic-publish-kit/              # 发布包生成
├── hotmic-style-learner/            # 风格学习
└── README.md
```

---

## 依赖说明

### video-cutter

| 依赖 | 用途 | 安装 |
|------|------|------|
| FFmpeg | 音视频处理 | `brew install ffmpeg` / `apt install ffmpeg` |
| groq | Groq API Python SDK | `pip install groq` |
| python-Levenshtein | 编辑距离加速 | `pip install python-Levenshtein` |
| numpy | 数值计算 | `pip install numpy` |

### review-engine

- 标准库：`json`, `csv`, `collections`, `datetime`
- 无需外部API

---

## 环境变量

| 变量名 | 必填 | 用途 |
|--------|------|------|
| `GROQ_API_KEY` | video-cutter 必填 | Groq Whisper API认证 |
| `FEISHU_APP_SECRET` | 可选 | 飞书文档同步 |

---

## 算法说明

### 重复段检测算法（video-cutter核心）

1. **有脚本模式**：对每个脚本句，用归一化Levenshtein编辑距离（阈值0.4）找出所有匹配的转录segment
2. **无脚本模式**：相邻segment字符级2-gram余弦相似度 > 0.85 视为重复

**选优评分**（综合分 = 文本准确度×0.6 + 流利度×0.4）：
- 文本准确度：`1 - normalized_levenshtein(segment_text, script_sentence)`
- 流利度：`1 / (停顿次数 + 词间隔标准差 + 1)`

### 权重调整逻辑（review-engine核心）

触发条件触发时自动生成补丁（建议由用户确认后手动应用到persona.json）：

| 条件 | 权重调整 |
|------|----------|
| 连续3条播放量 > 10万 | 该主线 +0.05 |
| 连续2条完播率 < 25% | 该主线 -0.03 |
| 连续3条涨粉效率 > 20/万播 | 该主线 +0.03 |
| 连续3条涨粉效率 < 5/万播 | 该主线 -0.05 |

---

## License

MIT

---

*由 HotMic AI（开麦）Codex 开发团队构建 · 2026*
