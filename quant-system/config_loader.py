"""
설정 파일 로더 / 저장기
"""
import os
from pathlib import Path

import yaml


def load_config(path: str = None) -> dict:
    if path is None:
        base_dir = Path(__file__).parent
        path = base_dir / "config.yaml"

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config


def save_config(config: dict, path: str = None) -> bool:
    """config dict를 config.yaml에 저장. True=성공."""
    if path is None:
        base_dir = Path(__file__).parent
        path = base_dir / "config.yaml"
    try:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True,
                      default_flow_style=False, sort_keys=False)
        return True
    except Exception as e:
        return False
