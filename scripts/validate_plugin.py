#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
PLUGIN_PATH = ROOT_DIR / "plugin.json"
SKILL_PATHS = (
    ROOT_DIR / "apps" / "script-creator" / "SKILL.md",
    ROOT_DIR / "apps" / "video-cutter" / "SKILL.md",
    ROOT_DIR / "apps" / "publish-kit" / "SKILL.md",
    ROOT_DIR / "apps" / "review-engine" / "SKILL.md",
    ROOT_DIR / "apps" / "style-learner" / "SKILL.md",
    ROOT_DIR / "apps" / "superdirector" / "SKILL.md",
)


def load_plugin() -> dict:
    with PLUGIN_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("plugin.json must contain a JSON object")
    return payload


def load_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path} is missing YAML frontmatter")
    _, _, remainder = text.partition("---\n")
    frontmatter, separator, _body = remainder.partition("\n---\n")
    if not separator:
        raise ValueError(f"{path} frontmatter is not terminated")
    data = yaml.safe_load(frontmatter) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} frontmatter must be a mapping")
    return data


def validate_plugin_paths(plugin: dict) -> None:
    skills = plugin.get("skills")
    if not isinstance(skills, list) or not skills:
        raise ValueError("plugin.json must define a non-empty skills array")
    for skill in skills:
        if not isinstance(skill, dict):
            raise ValueError("Each plugin skill entry must be an object")
        rel_path = skill.get("path")
        if not rel_path:
            raise ValueError("Each plugin skill must define path")
        target = ROOT_DIR / str(rel_path)
        if not target.exists():
            raise ValueError(f"Plugin skill path does not exist: {rel_path}")
        triggers = skill.get("triggers")
        if not isinstance(triggers, list) or not triggers:
            raise ValueError(f"Plugin skill {skill.get('id')} must define triggers")


def validate_skills() -> None:
    command_names: set[str] = set()
    for path in SKILL_PATHS:
        data = load_frontmatter(path)
        metadata = data.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError(f"{path} metadata must be a mapping")

        openclaw = metadata.get("openclaw") or {}
        cowork = metadata.get("cowork") or {}
        if not isinstance(openclaw, dict) or not isinstance(cowork, dict):
            raise ValueError(f"{path} openclaw/cowork metadata must be mappings")

        commands = openclaw.get("commands") or []
        if not isinstance(commands, list) or not commands:
            raise ValueError(f"{path} must define metadata.openclaw.commands")
        for command in commands:
            if not isinstance(command, dict):
                raise ValueError(f"{path} command entries must be objects")
            name = str(command.get("name") or "")
            if not name.startswith(("/hotmic-", "/sd-")):
                raise ValueError(f"{path} has invalid command prefix: {name}")
            if name in command_names:
                raise ValueError(f"Duplicate command detected: {name}")
            command_names.add(name)

        examples = cowork.get("examples") or []
        if len(examples) < 2:
            raise ValueError(f"{path} must define at least two cowork examples")


def main() -> int:
    plugin = load_plugin()
    validate_plugin_paths(plugin)
    validate_skills()
    print("plugin packaging validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
