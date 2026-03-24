---
name: superdirector
description: >
  选题发现引擎（SuperDirector）。自动采集多平台热点、AI 分析评分、总编选题、生成创作框架。
  当用户说“选题”“今日热点”“看看有什么选题”“帮我找选题”“跑一轮选题”时触发。
  也可以手动调起反馈回收、权重调参、选题回测等高级能力。
metadata:
  openclaw:
    commands:
      - name: /sd-run
        description: 执行完整选题流程（采集 -> 分析 -> 评分 -> 选题 -> 框架）
        usage: /sd-run [--platform douyin|shipinhao|xiaohongshu]
      - name: /sd-script
        description: 按今日排名一键生成 HotMic 创作输入
        usage: /sd-script <排名数字>
      - name: /sd-published
        description: 确认选题已发布并回写平台链接
        usage: /sd-published <排名数字> <发布URL>
      - name: /sd-tune
        description: 用自然语言调整评分或总编权重
        usage: /sd-tune <自然语言指令>
      - name: /sd-feedback
        description: 查看多平台反馈回收状态
        usage: /sd-feedback
    dependencies:
      - python3
    env:
      - GEMINI_API_KEY
      - TELEGRAM_BOT_TOKEN
      - TELEGRAM_CHAT_ID
      - QWEN_API_KEY
      - BRAVE_SEARCH_API_KEY
      - BRAVE_SEARCH_API_KEY_2
      - TAVILY_API_KEY
    tags:
      - topic-discovery
      - analytics
      - content-creation
      - scheduling
  cowork:
    slot: scheduled
    requires_files: false
    output_format: json
    requires_service: true
    service_command: cd apps/superdirector && ./.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8100
    health_check: http://127.0.0.1:8100/health
    examples:
      - 帮我跑一轮今天的选题
      - 看看今天有什么值得做的热点
      - 把第 1 条选题直接送去写稿
---

# superdirector - 选题发现引擎

## 概述

SuperDirector 是 HotMic AI 的选题源头模块。它负责多信源采集、AI 分析、七维评分、总编筛选和创作框架生成，并将高优先级题目直接桥接到 HotMic 创作链路。

## 运行模式

### 模式 A：作为独立 API 服务

```bash
cd apps/superdirector
./.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8100
```

### 模式 B：作为 skill 手动触发

在可运行 async Python 的上下文中：

```python
import sys

sys.path.insert(0, "apps/superdirector")

from pipeline.pipeline import run_pipeline

result = await run_pipeline()
```

## 核心接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/pipeline/run` | 执行完整采集 -> 分析 -> 评分 -> 选题 -> 框架流程 |
| POST | `/topics/today/{rank}/create-script` | 按排名一键启动 HotMic 创作 |
| POST | `/topics/{topic_id}/publish-confirm` | 确认发布并回写状态 |
| GET | `/topics/today` | 获取今日选题列表 |
| GET | `/feedback/status` | 查看多平台反馈回收状态 |
| POST | `/scoring/apply-review-patch` | 应用复盘反馈补丁 |

## 目录提示

- `main.py`：FastAPI 入口
- `api/routes.py`：全部 HTTP API
- `pipeline/`：采集、分析、评分、总编、框架、反馈闭环
- `config/`：创作者画像、总编 hints、评分权重
- `db/`：SQLAlchemy async 模型与 CRUD
- `tests/`：SD 相关测试
