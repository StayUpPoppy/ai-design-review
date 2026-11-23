from __future__ import annotations
from hashlib import sha256
import json
import re
import shutil
from uuid import uuid4
from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from .identity import IdentityContext
from .review_persistence import PersistenceError
from .template_pdf import TemplatePdfError, readiness, resources, resource_status
from .template_pdf_store import TemplatePdfStore


class TemplatePdfCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_review_revision: int = Field(ge=1, description="当前已保存审图修订号")
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"\S", description="本次出图的唯一请求编号；重试时复用")


def public_record(record):
    url = f"/api/template-pdfs/{record['pdf_id']}/file"
    return {key: record[key] for key in ("pdf_id", "review_revision", "template_version", "created_at", "filename")} | {
        "review_id": record["review_job_id"], "url": url, "inline_url": url + "?inline=true",
    }


def register_template_pdf_routes(app, *, repository, load_review, job_dir, require_identity):
    app.state.template_pdf_resources = resource_status()
    def store():
        value = repository()
        if not value.configured:
            raise HTTPException(503, detail={"code": "template_pdf_database_missing", "message": "模板 PDF 历史需要配置数据库。"})
        result = TemplatePdfStore(value)
        if not result.available():
            raise HTTPException(503, detail={"code": "template_pdf_database_unavailable", "message": "模板 PDF 历史暂不可用，请检查数据库连接并执行数据库迁移。"})
        return result

    @app.get("/api/reviews/{job_id}/template-pdf-readiness", tags=["Template PDF"])
    def get_readiness(job_id: str, identity: IdentityContext = Depends(require_identity)):
        review, revision = load_review(job_id, identity)
        try:
            result, _ = readiness(review)
        except (ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, TemplatePdfError):
                raise HTTPException(422, detail=exc.detail()) from exc
            raise HTTPException(422, detail={"code": "template_pdf_invalid_parameters", "message": "参数格式无效，请核对当前输入。"}) from exc
        try:
            store()
        except HTTPException as exc:
            message = exc.detail["message"]
            result["readiness"].update(status="blocked", summary=message)
            result["readiness"].setdefault("blocking_reasonableness", []).append({"field": "history", "reason": message})
        return {"review_id": job_id, "review_revision": revision, **result}

    @app.get("/api/reviews/{job_id}/template-pdfs", tags=["Template PDF"])
    def list_pdfs(job_id: str, identity: IdentityContext = Depends(require_identity)):
        load_review(job_id, identity)
        return {"review_id": job_id, "template_pdfs": [public_record(row) for row in store().list(job_id, identity.user_id)]}

    @app.post("/api/reviews/{job_id}/template-pdfs", tags=["Template PDF"], status_code=201)
    def create_pdf(job_id: str, body: TemplatePdfCreate, identity: IdentityContext = Depends(require_identity)):
        review, revision = load_review(job_id, identity)
        records = store()
        fingerprint = sha256(json.dumps({"revision": body.expected_review_revision}, sort_keys=True).encode()).hexdigest()
        existing = records.find_request(job_id, identity.user_id, body.idempotency_key)
        if existing:
            if existing["request_fingerprint"] != fingerprint:
                raise HTTPException(409, detail={"code": "template_pdf_request_conflict", "message": "此请求编号已用于其他审图版本，请重新出图。"})
            return JSONResponse(status_code=200, content={"created": False, "template_pdf": public_record(existing)})
        if revision != body.expected_review_revision:
            raise HTTPException(409, detail={"code": "review_revision_conflict", "message": "审图参数已更新，请刷新后重新出图。", "current_revision": revision})
        try:
            result, snapshot = readiness(review)
            if not result["resources"]["available"]:
                raise HTTPException(503, detail={"code": result["resources"].get("code", "template_pdf_resources_missing"), "message": result["resources"]["message"]})
            if result["readiness"]["status"] not in ("ready", "ready_with_warnings"):
                raise HTTPException(409, detail={"code": "template_pdf_not_ready", "message": result["readiness"]["summary"], "readiness": result["readiness"]})
            resource = resources()
            svg, pdf = resource.render(snapshot["template_data"])
        except TemplatePdfError as exc:
            raise HTTPException(422, detail=exc.detail()) from exc
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(422, detail={"code": "template_pdf_invalid_parameters", "message": "参数格式无效，请核对当前输入。"}) from exc
        pdf_id = uuid4().hex
        directory = job_dir(job_id) / "template_pdf" / pdf_id
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", snapshot["template_data"]["product_name"] or "压簧模板图纸")[:100] + ".pdf"
        try:
            directory.mkdir(parents=True, exist_ok=False)
            (directory / "drawing.svg").write_bytes(svg)
            (directory / "drawing.pdf").write_bytes(pdf)
            record, created = records.create({
                "pdf_id": pdf_id, "review_job_id": job_id, "owner_erp_user_id": identity.user_id,
                "review_revision": revision, "idempotency_key": body.idempotency_key, "request_fingerprint": fingerprint,
                "template_version": resource.version, "parameter_snapshot": snapshot,
                "technical_requirements_text": snapshot["technical_requirements_projection"]["text"],
                "template_data": snapshot["template_data"], "relative_path": f"template_pdf/{pdf_id}/drawing.pdf", "filename": filename,
            })
            if not created:
                shutil.rmtree(directory)
        except (PersistenceError, OSError) as exc:
            if directory.is_dir():
                shutil.rmtree(directory)
            raise HTTPException(503, detail={"code": "template_pdf_save_failed", "message": "模板 PDF 保存失败，请重试。"}) from exc
        return JSONResponse(status_code=201 if created else 200, content={"created": created, "template_pdf": public_record(record)})

    @app.get("/api/template-pdfs/{pdf_id}/file", tags=["Template PDF"])
    def download(pdf_id: str, inline: bool = False, identity: IdentityContext = Depends(require_identity)):
        record = store().get(pdf_id, identity.user_id)
        if not record:
            raise HTTPException(404, detail="模板 PDF 不存在。")
        load_review(record["review_job_id"], identity)
        root = job_dir(record["review_job_id"]).resolve()
        path = (root / record["relative_path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404, detail="模板 PDF 文件不存在。")
        return FileResponse(path, media_type="application/pdf", filename=record["filename"], content_disposition_type="inline" if inline else "attachment")
