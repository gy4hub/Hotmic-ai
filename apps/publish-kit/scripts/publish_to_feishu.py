#!/usr/bin/env python3
"""
publish_to_feishu.py
将定稿脚本归档到飞书云文档。

功能：
1. 获取 tenant_access_token
2. 在目标文件夹创建新文档
3. 写入完整 9 件套内容块
4. 返回文档链接

配置：
- App ID: shared/config.json 中的 feishu.app_id
- App Secret: 环境变量 FEISHU_APP_SECRET
- 目标文件夹: shared/config.json 中的 feishu.folder_token

使用方式：
  python scripts/publish_to_feishu.py --input output/script.md --title "0323 外泌体风险提示"
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

try:
    import urllib.request
    import urllib.error
    import urllib.parse
except ImportError:
    print("错误：需要 Python 3 标准库", file=sys.stderr)
    sys.exit(1)


def _resolve_project_root() -> Path:
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / "shared" / "config.json").exists():
            return candidate
    return start.parent.parent


# ─── 配置加载 ────────────────────────────────────────────────────────────────

def load_config(config_path: str = None) -> dict:
    """加载 shared/config.json"""
    if config_path is None:
        config_path = _resolve_project_root() / "shared" / "config.json"

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_feishu_config(config: dict) -> dict:
    """从全局配置中提取飞书配置"""
    fc = config.get("feishu", {})
    app_secret = os.environ.get(fc.get("app_secret_env", "FEISHU_APP_SECRET"), "")

    if not app_secret:
        raise ValueError(
            f"未找到飞书 App Secret。请设置环境变量: "
            f"{fc.get('app_secret_env', 'FEISHU_APP_SECRET')}"
        )

    return {
        "app_id": fc.get("app_id", ""),
        "app_secret": app_secret,
        "folder_token": fc.get("folder_token", ""),
    }


# ─── 飞书 API 封装 ───────────────────────────────────────────────────────────

FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"


def feishu_request(
    method: str,
    path: str,
    data: dict = None,
    headers: dict = None,
    token: str = None,
) -> dict:
    """
    发送飞书 API 请求。

    Args:
        method: HTTP 方法（GET/POST）
        path: API 路径（不含 base URL）
        data: 请求体
        headers: 额外请求头
        token: tenant_access_token

    Returns:
        响应 JSON（已解析）
    """
    url = f"{FEISHU_BASE_URL}{path}"
    req_headers = {"Content-Type": "application/json; charset=utf-8"}

    if token:
        req_headers["Authorization"] = f"Bearer {token}"

    if headers:
        req_headers.update(headers)

    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_body = resp.read().decode("utf-8")
            return json.loads(response_body)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        raise RuntimeError(f"飞书 API 请求失败: HTTP {e.code}, {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"飞书 API 网络错误: {e.reason}")


def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    """
    获取 tenant_access_token。
    """
    resp = feishu_request(
        method="POST",
        path="/auth/v3/tenant_access_token/internal",
        data={"app_id": app_id, "app_secret": app_secret},
    )

    if resp.get("code") != 0:
        raise RuntimeError(f"获取 token 失败: {resp.get('msg')}")

    token = resp.get("tenant_access_token", "")
    expire = resp.get("expire", 7200)
    print(f"✅ 已获取 tenant_access_token（有效期 {expire}s）")
    return token


def create_doc(token: str, folder_token: str, title: str) -> dict:
    """
    在目标文件夹创建新的飞书文档。

    Returns:
        {document_id, url}
    """
    resp = feishu_request(
        method="POST",
        path="/docx/v1/documents",
        data={
            "folder_token": folder_token,
            "title": title,
        },
        token=token,
    )

    if resp.get("code") != 0:
        raise RuntimeError(f"创建文档失败: {resp.get('msg')}")

    doc_info = resp.get("data", {}).get("document", {})
    document_id = doc_info.get("document_id", "")
    doc_url = f"https://bytedance.feishu.cn/docx/{document_id}"

    print(f"✅ 文档已创建: {title}")
    print(f"   文档 ID: {document_id}")
    return {"document_id": document_id, "url": doc_url}


def build_blocks_from_markdown(markdown_content: str) -> list:
    """
    将 Markdown 内容转换为飞书文档 blocks。
    简化版：支持标题（#/##/###）、段落、代码块。
    """
    blocks = []
    lines = markdown_content.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # 处理代码块
        if line.strip().startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            code_content = "\n".join(code_lines)
            blocks.append({
                "block_type": 4,  # code block
                "code": {
                    "elements": [{"text_run": {"content": code_content}}],
                    "style": {"language": 1},  # plain text
                }
            })
            i += 1
            continue

        # 处理标题
        if line.startswith("# "):
            blocks.append(_make_heading_block(line[2:].strip(), level=1))
        elif line.startswith("## "):
            blocks.append(_make_heading_block(line[3:].strip(), level=2))
        elif line.startswith("### "):
            blocks.append(_make_heading_block(line[4:].strip(), level=3))
        elif line.strip() == "":
            # 空行 → 空段落
            if blocks and blocks[-1].get("block_type") not in [1, 2, 3]:
                blocks.append(_make_paragraph_block(""))
        else:
            # 普通段落
            blocks.append(_make_paragraph_block(line))

        i += 1

    return blocks


def _make_heading_block(text: str, level: int = 1) -> dict:
    """创建标题 block"""
    block_type_map = {1: 2, 2: 3, 3: 4}  # heading 1/2/3
    return {
        "block_type": block_type_map.get(level, 2),
        f"heading{level}": {
            "elements": [{"text_run": {"content": text}}],
            "style": {},
        }
    }


def _make_paragraph_block(text: str) -> dict:
    """创建段落 block"""
    return {
        "block_type": 2,  # paragraph
        "text": {
            "elements": [{"text_run": {"content": text}}],
            "style": {},
        }
    }


def write_blocks_to_doc(token: str, document_id: str, blocks: list) -> None:
    """
    将内容块写入飞书文档。
    飞书 API 限制每次最多写入 50 个 block，分批处理。
    """
    batch_size = 50
    total_blocks = len(blocks)

    for start in range(0, total_blocks, batch_size):
        batch = blocks[start:start + batch_size]

        resp = feishu_request(
            method="POST",
            path=f"/docx/v1/documents/{document_id}/blocks/batch_create",
            data={
                "children": batch,
                "index": start,
            },
            token=token,
        )

        if resp.get("code") != 0:
            raise RuntimeError(f"写入内容块失败（batch {start}-{start+len(batch)}）: {resp.get('msg')}")

        print(f"   已写入 block {start+1}-{start+len(batch)}/{total_blocks}")
        # 避免触发限流
        if start + batch_size < total_blocks:
            time.sleep(0.3)

    print(f"✅ 内容写入完成（共 {total_blocks} 个 block）")


# ─── 主流程 ──────────────────────────────────────────────────────────────────

def load_script(script_path: str) -> str:
    """读取脚本文件"""
    with open(script_path, "r", encoding="utf-8") as f:
        return f.read()


def generate_doc_title(script_path: str, custom_title: str = None) -> str:
    """
    生成飞书文档标题。
    格式：MMDD 关键词
    """
    if custom_title:
        return custom_title

    today = datetime.now().strftime("%m%d")
    stem = Path(script_path).stem.replace("_", " ")[:20]
    return f"{today} {stem}"


def update_content_log(script_path: str, doc_url: str) -> None:
    """将飞书归档记录写入 content_log.json"""
    project_root = _resolve_project_root()
    log_path = project_root / "shared" / "content_log.json"

    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)
    else:
        log = {"version": "1.0", "entries": []}

    # 查找已有条目并更新，或新增
    script_str = str(script_path)
    for entry in log.get("entries", []):
        if entry.get("script_path") == script_str:
            entry["feishu_url"] = doc_url
            entry["archived_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)
            return

    # 新增条目
    log["entries"].append({
        "id": f"content_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "script_path": script_str,
        "feishu_url": doc_url,
        "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def publish_to_feishu(
    script_path: str,
    doc_title: str = None,
    config_path: str = None,
    dry_run: bool = False,
) -> dict:
    """
    完整飞书归档流程。

    Args:
        script_path: script.md 路径
        doc_title: 文档标题（不指定则自动生成）
        config_path: shared/config.json 路径
        dry_run: 试运行模式，不实际创建文档

    Returns:
        {document_id, url, title}
    """
    config = load_config(config_path)
    fc = get_feishu_config(config)

    script_content = load_script(script_path)
    title = generate_doc_title(script_path, doc_title)
    blocks = build_blocks_from_markdown(script_content)

    print(f"📄 准备归档: {title}")
    print(f"   内容 blocks: {len(blocks)} 个")
    print(f"   目标文件夹: {fc['folder_token']}")

    if dry_run:
        print("（dry-run 模式，跳过实际API调用）")
        return {"document_id": "dry_run", "url": "https://example.com/dry_run", "title": title}

    # Step 1: 获取 token
    token = get_tenant_access_token(fc["app_id"], fc["app_secret"])

    # Step 2: 创建文档
    doc_info = create_doc(token, fc["folder_token"], title)

    # Step 3: 写入内容
    write_blocks_to_doc(token, doc_info["document_id"], blocks)

    # Step 4: 更新 content_log
    update_content_log(script_path, doc_info["url"])

    result = {
        "document_id": doc_info["document_id"],
        "url": doc_info["url"],
        "title": title,
    }

    print(f"\n🎉 飞书归档完成！")
    print(f"   文档链接: {doc_info['url']}")

    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="将脚本归档到飞书云文档")
    parser.add_argument("--input", required=True, help="script.md 路径")
    parser.add_argument("--title", default=None, help="飞书文档标题（格式：MMDD 关键词）")
    parser.add_argument("--config", default=None, help="config.json 路径")
    parser.add_argument("--dry-run", action="store_true", help="试运行，不实际调用API")

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"错误：找不到脚本文件: {args.input}", file=sys.stderr)
        sys.exit(1)

    try:
        result = publish_to_feishu(
            script_path=args.input,
            doc_title=args.title,
            config_path=args.config,
            dry_run=args.dry_run,
        )
        print(f"\n飞书文档链接: {result['url']}")
    except ValueError as e:
        print(f"配置错误: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"API 错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
