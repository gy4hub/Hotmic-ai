# SuperDirector

SuperDirector is a Python pipeline for Casey's topic planning workflow. It collects candidate topics, analyzes them with Qwen or Gemini, scores them, generates content frames, and syncs results to Feishu Bitable.

## What It Does

- Collects topics from RSS and Brave Search
- Analyzes topics with `qwen-plus` first, Gemini as fallback
- Scores topics with 7-dimension weights per platform
- Generates content frames for `douyin`, `xiaohongshu`, and `shipinhao`
- Exposes FastAPI endpoints for Casey's `/sd` commands
- Tracks API token usage and estimated cost
- Syncs topics and frames to Feishu Bitable
- Supports feedback sync from Bitable back into SQLite

## Project Layout

```text
apps/superdirector/
├── main.py
├── config.py
├── scheduler.py
├── pipeline/
├── tools/
├── db/
├── config/
└── tests/
```

## Runtime Requirements

- Python 3.14
- `httpx`, `fastapi`, `sqlalchemy`, `aiosqlite`, `apscheduler`
- Qwen API key or Gemini API key
- Brave Search API key
- Optional Feishu app credentials for Bitable sync

## Environment Variables

Core runtime:

```bash
QWEN_API_KEY=...
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
GEMINI_API_KEY=...
GEMINI_FLASH_MODEL=gemini-flash-latest
BRAVE_SEARCH_API_KEY=...
HTTP_PROXY=http://your-proxy:port
HTTPS_PROXY=http://your-proxy:port
```

Feishu sync:

```bash
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
BITABLE_APP_TOKEN=...
TOPICS_TABLE_ID=...
FRAMES_TABLE_ID=...
```

## Local Run

```bash
cd /path/to/Hotmic-ai/apps/superdirector
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8100
```

## Tests

```bash
cd /path/to/Hotmic-ai/apps/superdirector
. .venv/bin/activate
pytest -q
```

## Main API Endpoints

- `POST /pipeline/run`
- `GET /topics/today`
- `POST /topics/{topic_id}/regen`
- `POST /topics/{topic_id}/frame/{platform}`
- `GET /cost`
- `GET /status`
- `POST /feedback/sync`
- `GET /feedback/summary`

## Feishu Bitable

Current Stage 3 setup creates and writes to a Feishu Bitable base with:

- `topics`
- `content_frames`

It also supports feedback fields on `topics`, including publish status and performance metrics.

## Notes

- RSS internal sources use a no-proxy client
- Brave and Gemini use the external proxy client
- Qwen calls use the internal no-proxy client
- Cost tracking is estimated from provider token usage metadata
- Bitable sync failures degrade to a SQLite outbox for retry

## Status

Current repo milestone inside the unified HotMic AI monorepo.

Canonical location: `apps/superdirector/`
Compatibility path still available: `superdirector/`
- Stage 1 complete: pipeline core
- Stage 2 complete: Casey `/sd` command integration
- Stage 3 complete: Feishu Bitable sync
- Feedback sync available

## Monorepo Note

- SuperDirector is now part of the unified `Hotmic-ai` workspace
- Shared creator profile comes from `shared/persona.json` -> `apps/superdirector/config/casey_profile.json`
- For new docs, scripts, and integrations, use `apps/superdirector/` as the canonical path
