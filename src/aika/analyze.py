from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from . import db as dbm
from .llm import LLMConfig, LLMError, get_provider


JOB_EXTRACT_ANNOTATIONS = "extract_annotations"
ALLOWED_TYPES = {"requirement", "risk", "decision", "dependency", "knowledge"}
ALLOWED_CONFIDENCE = {"high", "medium", "needs_review"}


@dataclass(frozen=True)
class AnalyzeScope:
    stage: str | None = None
    limit_chunks: int | None = None


SYSTEM_PROMPT = (
    "你是一位资深 IT 实施顾问。你必须基于证据输出，并且只返回 JSON。"
)


def build_user_prompt(*, chunk_text: str) -> str:
    return (
        "请从下面的文档片段中提取标注条目，输出 JSON："
        "{\"annotations\":[{\"type\":\"requirement|risk|decision|dependency|knowledge\","
        "\"content\":\"...\",\"confidence\":\"high|medium|needs_review\"}]}"
        "\n\n文档片段：\n"
        f"{chunk_text}"
    )


def _iter_project_chunks(conn, *, project_id: int, stage: str | None, limit_chunks: int | None):
    params: list[object] = [project_id]
    stage_sql = ""
    if stage is not None:
        stage_sql = "AND d.stage=?"
        params.append(stage)
    limit_sql = ""
    if limit_chunks is not None:
        limit_sql = "LIMIT ?"
        params.append(int(limit_chunks))

    sql = f"""
    SELECT c.id AS chunk_id, c.text AS text
    FROM document_chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.project_id = ?
      {stage_sql}
    ORDER BY d.path, c.chunk_index
    {limit_sql}
    """
    for r in conn.execute(sql, params):
        yield int(r["chunk_id"]), str(r["text"])


def run_extract_annotations(
    conn,
    *,
    project: dbm.ProjectRow,
    scope: AnalyzeScope,
    llm_cfg: LLMConfig,
) -> int:
    scope_json = json.dumps(
        {"stage": scope.stage, "limit_chunks": scope.limit_chunks},
        ensure_ascii=False,
    )
    llm_config_json = json.dumps(llm_cfg.__dict__, ensure_ascii=False)
    job_id = dbm.create_analysis_job(
        conn,
        project_id=project.id,
        job_type=JOB_EXTRACT_ANNOTATIONS,
        scope_json=scope_json,
        llm_config_json=llm_config_json,
    )
    dbm.update_analysis_job_status(conn, job_id=job_id, status="running", progress=0, started=True)
    dbm.commit(conn)

    provider = get_provider(llm_cfg.provider)
    inserted = 0
    processed = 0
    invalid_chunks = 0
    chunk_ids: list[int] = []

    for chunk_id, chunk_text in _iter_project_chunks(
        conn,
        project_id=project.id,
        stage=scope.stage,
        limit_chunks=scope.limit_chunks,
    ):
        chunk_ids.append(chunk_id)

    total = len(chunk_ids)
    try:
        for chunk_id in chunk_ids:
            row = conn.execute(
                "SELECT text FROM document_chunks WHERE id=?",
                (chunk_id,),
            ).fetchone()
            if row is None:
                continue
            chunk_text = str(row["text"])
            user_prompt = build_user_prompt(chunk_text=chunk_text)

            res = provider.chat(system=SYSTEM_PROMPT, user=user_prompt, config=llm_cfg)
            try:
                payload = json.loads(res.text)
            except json.JSONDecodeError:
                payload = None

            annotations: list[dict[str, Any]] = []
            if isinstance(payload, dict) and isinstance(payload.get("annotations"), list):
                annotations = payload["annotations"]
            else:
                invalid_chunks += 1
                dbm.insert_annotation(
                    conn,
                    project_id=project.id,
                    chunk_id=chunk_id,
                    type_="knowledge",
                    content="LLM 输出无法解析为期望的 JSON 结构，需要人工核实。",
                    source="ai_generated",
                    confidence="needs_review",
                )
                inserted += 1

            for a in annotations:
                if not isinstance(a, dict):
                    continue
                type_ = str(a.get("type") or "").strip()
                content = str(a.get("content") or "").strip()
                confidence = (str(a.get("confidence") or "").strip() or "needs_review").strip()

                if type_ not in ALLOWED_TYPES or not content:
                    invalid_chunks += 1
                    dbm.insert_annotation(
                        conn,
                        project_id=project.id,
                        chunk_id=chunk_id,
                        type_="knowledge",
                        content="LLM 输出字段不合法（type/content），需要人工核实。",
                        source="ai_generated",
                        confidence="needs_review",
                    )
                    inserted += 1
                    break

                if confidence not in ALLOWED_CONFIDENCE:
                    confidence = "needs_review"

                dbm.insert_annotation(
                    conn,
                    project_id=project.id,
                    chunk_id=chunk_id,
                    type_=type_,
                    content=content,
                    source="ai_generated",
                    confidence=confidence,
                )
                inserted += 1

            processed += 1
            prog = int(processed * 100 / total) if total else 100
            dbm.update_analysis_job_status(conn, job_id=job_id, status="running", progress=prog)
            dbm.commit(conn)

    except (LLMError, json.JSONDecodeError) as e:
        dbm.update_analysis_job_status(
            conn,
            job_id=job_id,
            status="failed",
            progress=int(processed * 100 / total) if total else 0,
            error_code="LLM_ERROR",
            error_message=str(e)[:500],
            finished=True,
        )
        dbm.commit(conn)
        raise

    final_status = "partial_success" if invalid_chunks > 0 else "succeeded"
    dbm.update_analysis_job_status(
        conn,
        job_id=job_id,
        status=final_status,
        progress=100,
        error_code=("LLM_OUTPUT_INVALID" if invalid_chunks > 0 else None),
        error_message=(f"invalid_chunks={invalid_chunks}" if invalid_chunks > 0 else None),
        finished=True,
    )
    dbm.commit(conn)
    return inserted

