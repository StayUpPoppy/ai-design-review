from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["AI_REVIEW_IDENTITY_MODE"] = "mock"
os.environ["GENERATION_ADMIN_API_KEY"] = "documentation-test-admin-secret"
os.environ["GENERATION_WORKER_API_KEY"] = "documentation-test-worker-secret"
os.environ["ERP_IDENTITY_COOKIE_NAME"] = "erp_review_identity"

from ai_design_review import api  # noqa: E402
from ai_design_review.api_documentation import (  # noqa: E402
    OPENAPI_TAGS,
    SCALAR_ASSET_FILENAME,
    SCALAR_ASSET_SHA256,
)


EXPECTED_OPERATION_KEYS = {
    ("GET", "/"),
    ("GET", "/api/health"),
    ("GET", "/api/session"),
    ("GET", "/api/samples/mixed-review"),
    ("GET", "/api/samples/spring-preview"),
    ("GET", "/api/standard-knowledge/search"),
    ("POST", "/api/reviews"),
    ("GET", "/api/reviews"),
    ("POST", "/api/reviews/standardize"),
    ("POST", "/api/reviews/reasonableness"),
    ("POST", "/api/reviews/standardization-chat"),
    ("GET", "/api/reviews/{job_id}/recognition-status"),
    ("POST", "/api/reviews/{job_id}/retry"),
    ("GET", "/api/reviews/{job_id}/candidates"),
    ("GET", "/api/reviews/{job_id}"),
    ("PATCH", "/api/reviews/{job_id}"),
    ("DELETE", "/api/reviews/{job_id}"),
    ("GET", "/api/reviews/{job_id}/changes"),
    ("GET", "/api/reviews/{job_id}/download"),
    ("GET", "/api/reviews/{job_id}/artifacts/{relative_path}"),
    ("POST", "/api/reviews/{job_id}/standardize"),
    ("POST", "/api/reviews/{job_id}/standardization-chat"),
    ("POST", "/api/reviews/{job_id}/parameter-change-proposals/{proposal_id}/apply"),
    ("POST", "/api/reviews/{job_id}/parameter-change-proposals/{proposal_id}/discard"),
    ("GET", "/api/reviews/{job_id}/generation-readiness"),
    ("GET", "/api/reviews/{job_id}/generation-package"),
    ("POST", "/api/reviews/{job_id}/generation-template-match"),
    ("POST", "/api/reviews/{job_id}/generation-jobs"),
    ("GET", "/api/reviews/{job_id}/generation-jobs"),
    ("GET", "/api/generation-templates"),
    ("GET", "/api/generation-templates/{template_code}/versions"),
    ("POST", "/api/admin/generation-templates"),
    ("POST", "/api/admin/generation-templates/{template_code}/versions"),
    ("PATCH", "/api/admin/generation-templates/{template_code}/versions/{version}/status"),
    ("GET", "/api/generation-jobs/{generation_id}"),
    ("POST", "/api/generation-jobs/{generation_id}/cancel"),
    ("POST", "/api/generation-jobs/{generation_id}/retry"),
    ("POST", "/api/generation-jobs/{generation_id}/approve"),
    ("GET", "/api/generation-jobs/{generation_id}/artifacts"),
    ("GET", "/api/generation-jobs/{generation_id}/artifacts/{artifact_id}"),
    ("POST", "/api/generation-worker/jobs/claim"),
    ("POST", "/api/generation-worker/jobs/{generation_id}/heartbeat"),
    ("PATCH", "/api/generation-worker/jobs/{generation_id}/status"),
    ("POST", "/api/generation-worker/jobs/{generation_id}/artifacts"),
    ("POST", "/api/generation-worker/jobs/{generation_id}/complete"),
    ("POST", "/api/generation-worker/jobs/{generation_id}/failed"),
}

EXPECTED_OPERATION_IDS = {
    "approve_generation_job_api_generation_jobs__generation_id__approve_post",
    "apply_review_parameter_change_proposal_api_reviews__job_id__parameter_change_proposals__proposal_id__apply_post",
    "assess_review_reasonableness_api_reviews_reasonableness_post",
    "cancel_generation_job_api_generation_jobs__generation_id__cancel_post",
    "claim_generation_worker_job_api_generation_worker_jobs_claim_post",
    "complete_generation_worker_job_api_generation_worker_jobs__generation_id__complete_post",
    "create_generation_job_api_reviews__job_id__generation_jobs_post",
    "create_generation_template_api_admin_generation_templates_post",
    "create_generation_template_version_api_admin_generation_templates__template_code__versions_post",
    "create_review_api_reviews_post",
    "delete_existing_review_api_reviews__job_id__delete",
    "discard_review_parameter_change_proposal_api_reviews__job_id__parameter_change_proposals__proposal_id__discard_post",
    "download_generation_artifact_api_generation_jobs__generation_id__artifacts__artifact_id__get",
    "download_review_api_reviews__job_id__download_get",
    "fail_generation_worker_job_api_generation_worker_jobs__generation_id__failed_post",
    "get_candidates_api_reviews__job_id__candidates_get",
    "get_generation_job_api_generation_jobs__generation_id__get",
    "get_generation_package_api_reviews__job_id__generation_package_get",
    "get_generation_readiness_api_reviews__job_id__generation_readiness_get",
    "get_mixed_review_sample_api_samples_mixed_review_get",
    "get_recognition_status_api_reviews__job_id__recognition_status_get",
    "get_review_api_reviews__job_id__get",
    "get_review_artifact_api_reviews__job_id__artifacts__relative_path__get",
    "get_review_changes_api_reviews__job_id__changes_get",
    "get_session_api_session_get",
    "get_spring_preview_sample_api_samples_spring_preview_get",
    "health_api_health_get",
    "heartbeat_generation_worker_job_api_generation_worker_jobs__generation_id__heartbeat_post",
    "list_generation_artifacts_api_generation_jobs__generation_id__artifacts_get",
    "list_generation_template_versions_api_generation_templates__template_code__versions_get",
    "list_generation_templates_api_generation_templates_get",
    "list_review_generation_jobs_api_reviews__job_id__generation_jobs_get",
    "list_reviews_api_reviews_get",
    "match_review_generation_template_api_reviews__job_id__generation_template_match_post",
    "retry_generation_job_api_generation_jobs__generation_id__retry_post",
    "retry_recognition_job_api_reviews__job_id__retry_post",
    "root__get",
    "save_existing_review_api_reviews__job_id__patch",
    "search_standard_knowledge_api_standard_knowledge_search_get",
    "standardization_chat_existing_review_api_reviews__job_id__standardization_chat_post",
    "standardization_chat_payload_api_reviews_standardization_chat_post",
    "standardize_existing_review_api_reviews__job_id__standardize_post",
    "standardize_review_payload_api_reviews_standardize_post",
    "update_generation_template_status_api_admin_generation_templates__template_code__versions__version__status_patch",
    "update_generation_worker_status_api_generation_worker_jobs__generation_id__status_patch",
    "upload_generation_worker_artifact_api_generation_worker_jobs__generation_id__artifacts_post",
}

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE"}
CHINESE = re.compile(r"[\u4e00-\u9fff]")


def main() -> None:
    client = TestClient(api.app)

    scalar_response = client.get("/api/docs")
    assert scalar_response.status_code == 200
    scalar_html = scalar_response.text
    assert f"/api/docs-assets/{SCALAR_ASSET_FILENAME}" in scalar_html
    assert "url: '/api/openapi.json'" in scalar_html
    assert "credentials: 'include'" in scalar_html
    assert "telemetry: false" in scalar_html
    assert "cdn.jsdelivr.net" not in scalar_html
    assert "proxy.scalar.com" not in scalar_html

    swagger_response = client.get("/api/swagger")
    assert swagger_response.status_code == 200
    assert "/api/openapi.json" in swagger_response.text

    redirect_response = client.get("/docs", follow_redirects=False)
    assert redirect_response.status_code == 307
    assert redirect_response.headers["location"] == "/api/docs"

    asset_response = client.get(f"/api/docs-assets/{SCALAR_ASSET_FILENAME}")
    assert asset_response.status_code == 200
    assert len(asset_response.content) > 1_000_000
    assert hashlib.sha256(asset_response.content).hexdigest() == SCALAR_ASSET_SHA256

    openapi_response = client.get("/api/openapi.json")
    assert openapi_response.status_code == 200
    schema = openapi_response.json()
    serialized = json.dumps(schema, ensure_ascii=False)
    assert "documentation-test-admin-secret" not in serialized
    assert "documentation-test-worker-secret" not in serialized
    assert schema["info"]["title"] == "弹簧图纸 AI 审查与生图 API"
    assert CHINESE.search(schema["info"]["description"])
    assert len(schema["x-tagGroups"]) == 4

    configured_tags = {tag["name"] for tag in OPENAPI_TAGS}
    operations: dict[tuple[str, str], dict] = {}
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            key = (method.upper(), path)
            if key[0] in HTTP_METHODS:
                operations[key] = operation

    assert set(operations) == EXPECTED_OPERATION_KEYS
    assert len(operations) == 46
    assert {operation["operationId"] for operation in operations.values()} == EXPECTED_OPERATION_IDS

    for key, operation in operations.items():
        assert CHINESE.search(operation.get("summary", "")), key
        assert CHINESE.search(operation.get("description", "")), key
        assert len(operation.get("tags", [])) == 1, key
        assert operation["tags"][0] in configured_tags, key
        for parameter in operation.get("parameters", []):
            assert CHINESE.search(parameter.get("description", "")), (key, parameter.get("name"))

    for model_name, model_schema in schema["components"]["schemas"].items():
        assert model_schema.get("description"), model_name
        for field_name, field_schema in (model_schema.get("properties") or {}).items():
            assert field_schema.get("description"), (model_name, field_name)

    schemes = schema["components"]["securitySchemes"]
    assert schemes["ErpIdentityCookie"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "erp_review_identity",
        "description": "ERP 注入的用户身份 Cookie；本地 mock 身份模式无需填写。",
    }
    assert schemes["GenerationAdminBearer"]["scheme"] == "bearer"
    assert schemes["GenerationWorkerBearer"]["scheme"] == "bearer"
    assert operations[("GET", "/api/health")]["security"] == []
    assert operations[("GET", "/api/session")]["security"] == [{"ErpIdentityCookie": []}]
    assert operations[("POST", "/api/admin/generation-templates")]["security"] == [{"GenerationAdminBearer": []}]
    assert operations[("POST", "/api/generation-worker/jobs/claim")]["security"] == [{"GenerationWorkerBearer": []}]

    assert operations[("PATCH", "/api/reviews/{job_id}")]["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SaveReviewRequest"
    }
    assert operations[("GET", "/api/reviews/{job_id}")]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ReviewDocument"
    }
    assert schema["components"]["schemas"]["ReviewDocument"].get("examples")
    assert schema["components"]["schemas"]["GenerationJobCreate"].get("examples")
    frozen_inputs = schema["components"]["schemas"]["CompressionSpringGenerationInputsV1"]
    frozen_fields = {
        "wire_diameter", "mean_diameter", "free_length", "total_coils",
        "active_coils", "handedness", "end_grinding", "end_coils_closed",
    }
    assert set(frozen_inputs["properties"]) == frozen_fields
    assert set(frozen_inputs["required"]) == frozen_fields
    assert frozen_inputs.get("additionalProperties") is False
    assert frozen_inputs["properties"]["handedness"]["$ref"].endswith("GenerationHandednessParameter")
    claim_response = operations[("POST", "/api/generation-worker/jobs/claim")]["responses"]["200"]
    assert claim_response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/GenerationWorkerClaimResponse"
    }
    claim_job = schema["components"]["schemas"]["GenerationWorkerClaimJobView"]
    assert claim_job["properties"]["parameter_package"]["$ref"].endswith("GenerationParameterPackageV1")
    generation_parameters = schema["components"]["schemas"]["GenerationParametersV1"]
    technical_text = generation_parameters["properties"]["technical_requirements_text"]
    assert technical_text["default"] == ""
    assert technical_text["description"]
    assert technical_text["examples"] == ["1.表面处理：表面镀锌。\n2.盐雾试验：96小时。"]
    chat_response = schema["components"]["schemas"]["StandardizationChatResponse"]
    assert chat_response["properties"]["generation_package_export"]["anyOf"][0]["$ref"].endswith(
        "GenerationPackageExportAction"
    )
    package_export_action = schema["components"]["schemas"]["GenerationPackageExportAction"]
    assert package_export_action["properties"]["schema_version"]["examples"] == ["spring_generation_parameters/v1"]
    assert package_export_action["properties"]["parameter_fields"]["description"]
    job_create = schema["components"]["schemas"]["GenerationJobCreate"]
    requested_artifacts = job_create["properties"]["requested_artifact_types"]
    assert requested_artifacts.get("default") == ["pdf"]
    assert operations[("POST", "/api/reviews")]["responses"]["413"]["content"]["application/json"]["example"]
    assert operations[("POST", "/api/generation-worker/jobs/{generation_id}/artifacts")]["responses"]["415"]["content"]["application/json"]["example"]

    print(f"API documentation contract tests passed: {len(operations)} operations, Chinese metadata, self-hosted Scalar, and security schemes.")


if __name__ == "__main__":
    main()
