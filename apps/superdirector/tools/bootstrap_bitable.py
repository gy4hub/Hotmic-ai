#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from core.logging import configure_logging, get_logger
from core.config import (
    BITABLE_APP_TOKEN,
    FEISHU_BASE_URL,
    FRAMES_TABLE_ID,
    TOPICS_TABLE_ID,
)
from pipeline.utils import request_with_retry
from integrations.feishu_auth import get_tenant_access_token

configure_logging()
logger = get_logger(__name__)

TOPICS_FIELDS = [
    ("topic_id", 1),
    ("date", 1),
    ("angle_type", 1),
    ("platform_priority", 1),
    ("content_type", 1),
    ("status", 1),
    ("url", 1),
    ("source", 1),
    ("timestamp", 1),
    ("summary", 1),
    ("keywords", 1),
    ("competitor_angle", 1),
    ("angle_gap", 1),
    ("score_total", 2),
    ("score_emotion", 2),
    ("score_timely", 2),
    ("score_subvert", 2),
    ("score_relate", 2),
    ("score_spread", 2),
    ("score_tension", 2),
    ("score_depth", 2),
    ("pipeline_run_id", 2),
    ("model_version", 1),
    ("publish_status", 1),
    ("publish_url", 1),
    ("publish_at", 1),
    ("frame_status", 1),
    ("frame_rejection_reason", 1),
    ("perf_views", 2),
    ("perf_likes", 2),
    ("perf_collects", 2),
    ("perf_watch_rate", 2),
    ("perf_favorite_rate", 2),
    ("perf_comments", 2),
    ("perf_shares", 2),
    ("creator_notes", 1),
    ("publish_match_terms", 1),
    ("review_status", 1),
    ("errors", 1),
    ("synced_at", 1),
]

FRAMES_FIELDS = [
    ("topic_id", 1),
    ("date", 1),
    ("platform_priority", 1),
    ("hook", 1),
    ("outline", 1),
    ("cta", 1),
    ("monetize_hook", 1),
    ("platform_tips", 1),
    ("pipeline_run_id", 2),
    ("model_version", 1),
    ("status", 1),
    ("errors", 1),
    ("synced_at", 1),
]

TOPICS_VIEWS = [
    {"targets": ["表格", "表格视图 1"], "name": "全部选题", "create_if_missing": False},
    {"targets": ["Top Topics"], "name": "今日 Top 选题", "create_if_missing": False},
    {"targets": [], "name": "今日 Top 选题", "create_if_missing": True},
]

FRAMES_VIEWS = [
    {"targets": ["表格", "表格视图 1"], "name": "全部框架", "create_if_missing": False},
    {"targets": [], "name": "今日脚本框架", "create_if_missing": True},
]


def _service_path() -> Path:
    return Path("/home/gchyang/.config/systemd/user/superdirector.service")


async def _headers(client: httpx.AsyncClient) -> dict[str, str]:
    token = await get_tenant_access_token(client)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    payload: dict | None = None,
) -> dict:
    headers = await _headers(client)
    resp = await request_with_retry(client, method, url, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Feishu API error: code={data.get('code')} msg={data.get('msg')}")
    return data


async def create_base(client: httpx.AsyncClient, base_name: str, folder_token: str) -> dict:
    url = f"{FEISHU_BASE_URL}/open-apis/bitable/v1/apps"
    payload = {
        "name": base_name,
        "folder_token": folder_token,
    }
    data = await _request_json(client, "POST", url, payload=payload)
    return data["data"]["app"]


async def list_tables(client: httpx.AsyncClient, app_token: str) -> list[dict]:
    url = f"{FEISHU_BASE_URL}/open-apis/bitable/v1/apps/{app_token}/tables"
    data = await _request_json(client, "GET", url)
    return data["data"]["items"]


async def rename_table(client: httpx.AsyncClient, app_token: str, table_id: str, name: str) -> None:
    url = f"{FEISHU_BASE_URL}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}"
    await _request_json(client, "PATCH", url, payload={"name": name})


async def create_table(client: httpx.AsyncClient, app_token: str, name: str) -> str:
    url = f"{FEISHU_BASE_URL}/open-apis/bitable/v1/apps/{app_token}/tables"
    data = await _request_json(client, "POST", url, payload={"table": {"name": name}})
    return data["data"]["table_id"]


async def list_views(client: httpx.AsyncClient, app_token: str, table_id: str) -> list[dict]:
    url = f"{FEISHU_BASE_URL}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/views"
    data = await _request_json(client, "GET", url)
    return data["data"]["items"]


async def create_view(client: httpx.AsyncClient, app_token: str, table_id: str, view_name: str) -> None:
    url = f"{FEISHU_BASE_URL}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/views"
    await _request_json(client, "POST", url, payload={"view_name": view_name, "view_type": "grid"})


async def rename_view(
    client: httpx.AsyncClient,
    app_token: str,
    table_id: str,
    view_id: str,
    view_name: str,
) -> None:
    url = f"{FEISHU_BASE_URL}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/views/{view_id}"
    await _request_json(client, "PATCH", url, payload={"view_name": view_name})


async def list_fields(client: httpx.AsyncClient, app_token: str, table_id: str) -> list[dict]:
    url = f"{FEISHU_BASE_URL}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    data = await _request_json(client, "GET", url)
    return data["data"]["items"]


async def create_field(
    client: httpx.AsyncClient,
    app_token: str,
    table_id: str,
    field_name: str,
    field_type: int,
) -> None:
    url = f"{FEISHU_BASE_URL}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    await _request_json(client, "POST", url, payload={"field_name": field_name, "type": field_type})


async def ensure_table_fields(
    client: httpx.AsyncClient,
    app_token: str,
    table_id: str,
    field_specs: list[tuple[str, int]],
) -> None:
    fields = await list_fields(client, app_token, table_id)
    existing = {field["field_name"] for field in fields}
    for field_name, field_type in field_specs:
        if field_name in existing:
            continue
        await create_field(client, app_token, table_id, field_name, field_type)


async def ensure_views(
    client: httpx.AsyncClient,
    app_token: str,
    table_id: str,
    specs: list[dict],
) -> None:
    views = await list_views(client, app_token, table_id)
    by_name = {view["view_name"]: view for view in views}

    for spec in specs:
        targets = spec.get("targets") or []
        name = spec["name"]
        create_if_missing = spec.get("create_if_missing", False)

        if name in by_name:
            continue
        for target in targets:
            if target in by_name:
                await rename_view(client, app_token, table_id, by_name[target]["view_id"], name)
                views = await list_views(client, app_token, table_id)
                by_name = {view["view_name"]: view for view in views}
                break
        if name in by_name:
            continue
        if create_if_missing:
            await create_view(client, app_token, table_id, name)
            views = await list_views(client, app_token, table_id)
            by_name = {view["view_name"]: view for view in views}


async def ensure_schema(
    client: httpx.AsyncClient,
    *,
    folder_token: str,
    base_name: str,
    app_token: str | None,
) -> dict:
    created_new_base = False
    if app_token:
        tables = await list_tables(client, app_token)
        if not tables:
            raise RuntimeError(f"Bitable app {app_token} has no tables")
        default_table_id = tables[0]["table_id"]
    else:
        app = await create_base(client, base_name, folder_token)
        app_token = app["app_token"]
        default_table_id = app["default_table_id"]
        created_new_base = True

    tables = await list_tables(client, app_token)
    table_by_name = {table["name"]: table["table_id"] for table in tables}

    topics_table_id = table_by_name.get("topics")
    if not topics_table_id:
        await rename_table(client, app_token, default_table_id, "topics")
        topics_table_id = default_table_id

    tables = await list_tables(client, app_token)
    table_by_name = {table["name"]: table["table_id"] for table in tables}

    frames_table_id = table_by_name.get("content_frames")
    if not frames_table_id:
        frames_table_id = await create_table(client, app_token, "content_frames")

    await ensure_table_fields(client, app_token, topics_table_id, TOPICS_FIELDS)
    await ensure_table_fields(client, app_token, frames_table_id, FRAMES_FIELDS)
    await ensure_views(client, app_token, topics_table_id, TOPICS_VIEWS)
    await ensure_views(client, app_token, frames_table_id, FRAMES_VIEWS)

    return {
        "created_new_base": created_new_base,
        "app_token": app_token,
        "topics_table_id": topics_table_id,
        "frames_table_id": frames_table_id,
        "folder_token": folder_token,
        "base_url": f"https://wcnlpn0avt8q.feishu.cn/base/{app_token}",
    }


def update_service_env(app_token: str, topics_table_id: str, frames_table_id: str) -> None:
    service_path = _service_path()
    text = service_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    replacements = {
        "Environment=BITABLE_APP_TOKEN=": f"Environment=BITABLE_APP_TOKEN={app_token}",
        "Environment=TOPICS_TABLE_ID=": f"Environment=TOPICS_TABLE_ID={topics_table_id}",
        "Environment=FRAMES_TABLE_ID=": f"Environment=FRAMES_TABLE_ID={frames_table_id}",
    }

    updated: list[str] = []
    seen = set()
    for line in lines:
        replaced = False
        for prefix, value in replacements.items():
            if line.startswith(prefix):
                updated.append(value)
                seen.add(prefix)
                replaced = True
                break
        if not replaced:
            updated.append(line)

    for prefix, value in replacements.items():
        if prefix not in seen:
            install_idx = next(
                (idx for idx, line in enumerate(updated) if line.strip() == "[Install]"),
                len(updated),
            )
            updated.insert(install_idx, value)

    service_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Feishu Bitable for SuperDirector")
    parser.add_argument(
        "--folder-token",
        default=os.getenv("BITABLE_FOLDER_TOKEN", "JZlJfMq3klMY1sdl6DVc4cm5nyb"),
        help="Target Feishu Drive folder token",
    )
    parser.add_argument(
        "--base-name",
        default="SuperDirector",
        help="Name of the new Bitable base",
    )
    parser.add_argument(
        "--app-token",
        default=BITABLE_APP_TOKEN,
        help="Reuse an existing Bitable app token if already created",
    )
    parser.add_argument(
        "--write-service-env",
        action="store_true",
        help="Write generated BITABLE_* values into superdirector.service",
    )
    args = parser.parse_args()

    async with httpx.AsyncClient(timeout=30) as client:
        result = await ensure_schema(
            client,
            folder_token=args.folder_token,
            base_name=args.base_name,
            app_token=args.app_token,
        )

    if args.write_service_env:
        update_service_env(
            result["app_token"],
            result["topics_table_id"],
            result["frames_table_id"],
        )

    logger.info("Bitable bootstrap result:\n%s", json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
