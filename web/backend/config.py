from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    docs2md_root: str | None
    docs2md_python: str
    projects_allow_prefix: str | None
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str | None
    llm_provider: str
    cors_origins: list[str]


@lru_cache
def get_settings() -> Settings:
    origins_raw = os.environ.get("AIKA_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
    origins = [o.strip() for o in origins_raw.split(",") if o.strip()]
    return Settings(
        docs2md_root=os.environ.get("DOCS2MD_ROOT"),
        docs2md_python=os.environ.get("DOCS2MD_PYTHON", "python"),
        projects_allow_prefix=os.environ.get("AIKA_PROJECTS_ALLOW_PREFIX"),
        llm_base_url=os.environ.get("AIKA_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL"),
        llm_api_key=os.environ.get("AIKA_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
        llm_model=os.environ.get("AIKA_LLM_MODEL"),
        llm_provider=os.environ.get("AIKA_LLM_PROVIDER", "openai_compatible"),
        cors_origins=origins,
    )
