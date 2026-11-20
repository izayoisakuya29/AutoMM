"""Profile 路径展开。"""

from __future__ import annotations

import os
from pathlib import Path

from ..common import ROOT


def expand_path(value: str | Path) -> Path:
    """展开 ~ 和环境变量，返回绝对路径。"""
    return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()


def project_path(value: str | Path) -> Path:
    """把相对路径解析到项目根目录；绝对路径原样返回。"""
    path = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()
