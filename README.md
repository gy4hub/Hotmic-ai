# HotMic AI（开麦）Monorepo

> **HotMic AI** 现在采用统一 monorepo 结构，覆盖选题 → 创作 → 剪辑 → 发布 → 复盘全链路。
> `apps/` 是规范入口，根目录保留兼容链接，方便旧脚本和后续 OpenClaw 接入继续工作。

## 迁移标注

- 2026-03 起，仓库正式以 `Hotmic-ai` 根目录作为唯一工作区
- `apps/` 是唯一规范代码入口，新增开发和文档请优先落在 `apps/<app-name>/`
- 根目录的 `superdirector`、`hotmic-*` 为兼容链接，仅用于兼容旧路径
- `shared/persona.json` 指向 `apps/superdirector/config/casey_profile.json`，作为全系统统一创作者画像

---

## 系统组成

| Skill | 功能 | 状态 |
|-------|------|------|
| `apps/superdirector` | 选题发现、评分、框架生成、反馈回流 | ✅ 已集成 |
| `apps/script-creator` | 口播脚本创作（9件套交付） | ✅ 已完成 |
| `apps/video-cutter` | 视频粗剪（自动去重复段落） | ✅ 已完成 |
| `apps/publish-kit` | 发布包生成、多平台适配 | ✅ 已完成 |
| `apps/style-learner` | 风格学习库维护 | ✅ 已完成 |
| `apps/review-engine` | 数据复盘与策略建议 | ✅ 已完成 |

## Monorepo 约定

- 规范目录是 `apps/ + shared/ + scripts/ + legacy/`
- `shared/` 是全系统单一事实源
- 根目录的 `superdirector`、`hotmic-*` 都是兼容链接，不再是主目录
- 新增脚本和文档时，优先使用 `apps/<app-name>/...` 作为绝对路径

---

## 安装

### 前置条件

- Python 3.8+
- FFmpeg（仅 video-cutter 需要）
- Groq API Key（免费注册：https://console.groq.com）

### 快速安装

```bash
# 1. 进入项目根目录
cd Hotmic-ai

# 2. 验证 shared/ 配置文件
python shared/validate_shared.py

# 3. 配置环境变量
export GROQ_API_KEY=your_groq_api_key_here

# 4. 安装 video-cutter 依赖
bash hotmic-video-cutter/scripts/install_deps.sh

# 5. 如需启动选题系统
cd apps/superdirector
python -m uvicorn main:app --host 127.0.0.1 --port 8100
```

也可以直接使用工作区脚本：

```bash
./scripts/dev_superdirector.sh
```

---

## 使用说明

### 模块 A：video-cutter（口播视频粗剪）

**适用场景**：录完口播视频后，自动剪去重复段落（同一句话录了多遍）

```bash
cd apps/video-cutter/scripts

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
cd apps/review-engine/scripts

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
# 运行整个工作区回归
./scripts/test_all.sh

# 或按应用分别运行
python -m pytest apps/superdirector/tests -q
python -m pytest apps/review-engine/tests -q
python -m pytest apps/script-creator/tests -q
python -m pytest apps/video-cutter/tests -q
```

---

## 项目结构

```
Hotmic-ai/
├── apps/                            # 规范运行目录
│   ├── superdirector/               # 选题系统
│   ├── script-creator/              # 脚本创作引擎
│   ├── review-engine/               # 数据复盘
│   ├── style-learner/               # 风格学习
│   ├── video-cutter/                # 视频粗剪
│   └── publish-kit/                 # 发布包生成
│
├── shared/                          # 全系统共享配置
│   ├── config.json                  # 平台配置
│   ├── persona.json                 # 统一创作者画像（链接到 apps/superdirector/config/casey_profile.json）
│   ├── style_db.json               # 风格规则库
│   ├── content_log.json            # 内容发布记录
│   ├── validate_shared.py          # JSON验证脚本
│   └── init_project.py             # 项目初始化脚本
│
├── scripts/                         # 工作区级启动/测试脚本
├── legacy/                          # 历史结构说明与迁移备注
│
├── superdirector -> apps/superdirector
├── hotmic-script-creator -> apps/script-creator
├── hotmic-review-engine -> apps/review-engine
├── hotmic-style-learner -> apps/style-learner
├── hotmic-video-cutter -> apps/video-cutter
└── hotmic-publish-kit -> apps/publish-kit
```

## 一体化约定

- 系统根目录就是 `Hotmic-ai/`
- `shared/` 是所有模块共用的单一事实源
- `apps/superdirector/` 负责选题、评分、框架和反馈闭环
- 其余 `apps/*` 目录负责创作、剪辑、发布和风格/复盘能力
- 根目录旧名字保留为兼容链接，不再作为主维护位置

## 推荐工作方式

```bash
# 启动 SD API
./scripts/dev_superdirector.sh

# 跑整个工作区回归
./scripts/test_all.sh

# 直接进入规范代码目录
cd apps/superdirector
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
