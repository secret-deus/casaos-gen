"""Shared constants and small helpers for CasaOS compose generation."""

from __future__ import annotations

from typing import List

CDN_BASE = "https://cdn.jsdelivr.net/gh/IceWhaleTech/CasaOS-AppStore@main/Apps"
STORE_FOLDER_PLACEHOLDER = "<store_folder>"

APP_DATA_BASE_DIR = "/DATA/AppData"
DEFAULT_APP_ID_VAR = "$AppID"


def build_cdn_icon_url(store_folder: str) -> str:
    return f"{CDN_BASE}/{store_folder}/icon.png"


def build_cdn_thumbnail_url(store_folder: str) -> str:
    return f"{CDN_BASE}/{store_folder}/thumbnail.png"


def build_cdn_screenshot_urls(store_folder: str) -> List[str]:
    return [
        f"{CDN_BASE}/{store_folder}/screenshot-1.png",
        f"{CDN_BASE}/{store_folder}/screenshot-2.png",
        f"{CDN_BASE}/{store_folder}/screenshot-3.png",
    ]


def build_app_data_root(app_id_var: str | None = None) -> str:
    """Return the CasaOS AppData root path (template-aware).

    Example: '/DATA/AppData/$AppID'
    """
    token = (app_id_var or DEFAULT_APP_ID_VAR).strip() or DEFAULT_APP_ID_VAR
    return f"{APP_DATA_BASE_DIR}/{token}"

