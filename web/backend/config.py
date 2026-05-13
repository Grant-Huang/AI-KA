from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    projects_allow_prefix: str | None
    enable_native_folder_picker: bool
    fs_picker_localhost_only: bool
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str | None
    llm_provider: str
    cors_origins: list[str]


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@lru_cache
def get_settings() -> Settings:
    origins_raw = os.environ.get("AIKA_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
    origins = [o.strip() for o in origins_raw.split(",") if o.strip()]
    return Settings(
        projects_allow_prefix=os.environ.get("AIKA_PROJECTS_ALLOW_PREFIX"),
        enable_native_folder_picker=_env_bool("AIKA_ENABLE_NATIVE_FOLDER_PICKER", True),
        fs_picker_localhost_only=_env_bool("AIKA_FS_PICKER_LOCALHOST_ONLY", True),
        llm_base_url=os.environ.get("AIKA_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL"),
        llm_api_key=os.environ.get("AIKA_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
        llm_model=os.environ.get("AIKA_LLM_MODEL"),
        llm_provider=os.environ.get("AIKA_LLM_PROVIDER", "openai_compatible"),
        cors_origins=origins,
    )
