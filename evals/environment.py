"""评测进程的本地环境变量兼容处理。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


_ENV_REFERENCE = re.compile(r"^env:([A-Za-z_][A-Za-z0-9_]*)$")


def _read_windows_user_environment(name: str) -> str | None:
    """读取当前 Windows 用户的环境变量，不输出变量值。"""

    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return value if isinstance(value, str) and value else None


def _collect_environment_references(value: Any, names: set[str]) -> None:
    if isinstance(value, str):
        match = _ENV_REFERENCE.fullmatch(value)
        if match:
            names.add(match.group(1))
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_environment_references(item, names)
        return
    if isinstance(value, list):
        for item in value:
            _collect_environment_references(item, names)


def hydrate_environment_from_project_config(data_roots: list[Path]) -> list[str]:
    """让评测进程继承项目配置引用的用户级环境变量。

    Windows 新开的 Python 进程通常只继承启动它的 Shell 环境；如果环境变量
    是在已有 Shell 之外配置的，用户级变量可能存在但不会出现在 ``os.environ``。
    这里只读取项目配置中的 ``env:NAME`` 引用，并从当前用户注册表补齐缺失项，
    不写入项目文件，也不记录任何密钥值。
    """

    names: set[str] = set()
    for root in data_roots:
        projects_path = root / "projects.json"
        if not projects_path.is_file():
            continue
        try:
            payload = json.loads(projects_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        _collect_environment_references(payload, names)

    loaded: list[str] = []
    for name in sorted(names):
        if os.environ.get(name):
            continue
        value = _read_windows_user_environment(name)
        if value:
            os.environ[name] = value
            loaded.append(name)
    return loaded
