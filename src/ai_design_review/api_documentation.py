from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


SCALAR_VERSION = "1.64.0"
SCALAR_ASSET_FILENAME = f"scalar-api-reference-{SCALAR_VERSION}.js"
SCALAR_ASSET_SHA256 = "25e0a1ef537dc7f1aa41dd8d22b94d8703dcfab34361f4d2ee84ac0600c8a457"

API_TITLE = "弹簧图纸 AI 审查与生图 API"
API_SUMMARY = "面向弹簧图纸识别、参数审查、标准化和 SolidWorks 生图协同的一体化接口。"
API_DESCRIPTION = """
## 使用说明

本 API 覆盖“上传图纸 → 异步识别 → 人工核对 → 可选参数标准化 → 生图准备 → SolidWorks 生图 → 版本确认”的完整流程。标准化用于辅助核对，不是创建生图任务的必备条件。

### 鉴权方式

- **ERP 身份 Cookie**：审图、标准化、模板查询和用户生图接口按 ERP 用户隔离数据。本地 `mock` 身份模式不要求浏览器携带 Cookie。
- **GenerationAdminBearer**：模板管理员专用 Bearer API Key。
- **GenerationWorkerBearer**：模拟或真实 SolidWorks Worker 专用 Bearer API Key。

管理员 Key 与 Worker Key 必须使用不同值，文档页面不会预填或保存服务端密钥。

### 推荐调用流程

1. 上传图纸并轮询识别状态。
2. 获取审图结果，人工修改、标准化并保存参数。
3. 查询生图就绪状态并匹配模板。
4. 创建生图任务，轮询任务状态并下载生成产物。
5. 修改参数后创建关联版本，最终确认当前修订对应的完成版本。
""".strip()


OPENAPI_TAGS = [
    {"name": "系统状态", "description": "服务入口、健康检查和运行环境诊断。"},
    {"name": "会话与示例", "description": "当前 ERP 身份和本地示例文件。"},
    {"name": "标准知识库", "description": "按标准号、弹簧类型和目标字段检索标准知识。"},
    {"name": "图纸识别", "description": "图纸上传、异步识别进度、失败重试和候选参数。"},
    {"name": "审图管理", "description": "审图记录、人工修改、审计历史和原始产物管理。"},
    {"name": "标准化与合理性", "description": "参数标准化、合理性诊断和标准化 AI 对话。"},
    {"name": "生图准备", "description": "生图就绪核对、参数包生成和模板匹配。"},
    {"name": "模板查询", "description": "普通用户查询当前启用的 SolidWorks 模板。"},
    {"name": "生图任务", "description": "创建、查询、取消、重试和确认生图版本。"},
    {"name": "生成产物", "description": "查询和下载生图任务生成的预览或模型文件。"},
    {"name": "模板管理", "description": "管理员注册模板版本以及启用或禁用模板。"},
    {"name": "SolidWorks Worker", "description": "SolidWorks Worker 领取任务、续租、上报进度和上传产物。"},
]

OPENAPI_TAG_GROUPS = [
    {"name": "基础服务", "tags": ["系统状态", "会话与示例", "标准知识库"]},
    {"name": "审图助手", "tags": ["图纸识别", "审图管理", "标准化与合理性"]},
    {"name": "生图中心", "tags": ["生图准备", "模板查询", "生图任务", "生成产物"]},
    {"name": "对接管理", "tags": ["模板管理", "SolidWorks Worker"]},
]


def _operation(tag: str, summary: str, description: str) -> dict[str, str]:
    return {"tag": tag, "summary": summary, "description": description}


OPERATION_DOCS: dict[tuple[str, str], dict[str, str]] = {
    ("GET", "/"): _operation("系统状态", "查看 API 服务入口", "返回服务名称、健康检查地址和增强接口文档地址，不执行任何业务操作。"),
    ("GET", "/api/health"): _operation("系统状态", "检查服务运行状态", "返回数据库、识别队列、OCR、标准化、生图队列和模拟模板等运行状态；用于部署验收和故障诊断。"),
    ("GET", "/api/session"): _operation("会话与示例", "获取当前 ERP 用户", "解析当前请求携带的 ERP 身份 Cookie，并返回脱敏后的用户与组织信息；本地 mock 模式返回配置的模拟身份。"),
    ("GET", "/api/samples/mixed-review"): _operation("会话与示例", "下载示例审图 JSON", "下载项目内置的压缩弹簧审图示例，便于前端演示和接口联调。"),
    ("GET", "/api/samples/spring-preview"): _operation("会话与示例", "查看示例弹簧预览图", "返回项目内置的压缩弹簧 PNG 预览图。"),
    ("GET", "/api/standard-knowledge/search"): _operation("标准知识库", "检索弹簧标准知识", "按标准号、弹簧类型、目标字段和自然语言问题检索标准条款；结果仅用于审图辅助，最终仍需人工确认。"),
    ("POST", "/api/reviews"): _operation("图纸识别", "上传图纸并创建识别任务", "以 multipart/form-data 上传图纸和可选识别结果，持久化输入后加入异步识别队列。成功返回 202 和 job_id，不代表识别已经完成。"),
    ("GET", "/api/reviews/{job_id}/recognition-status"): _operation("图纸识别", "查询图纸识别进度", "查询指定审图任务的排队位置、处理阶段、进度和错误信息；前端可定时轮询，完成后再获取审图结果。"),
    ("POST", "/api/reviews/{job_id}/retry"): _operation("图纸识别", "重试失败的识别任务", "仅允许重试 failed 状态的识别任务；成功后任务重新进入队列并返回 202。"),
    ("GET", "/api/reviews/{job_id}/candidates"): _operation("图纸识别", "获取识别候选参数", "返回 OCR、视觉模型和几何识别产生的候选数据，用于追溯参数来源和人工复核。"),
    ("GET", "/api/reviews"): _operation("审图管理", "查询审图记录列表", "按当前 ERP 用户隔离并返回最近的审图及识别任务；limit 范围为 1 至 100。"),
    ("GET", "/api/reviews/{job_id}"): _operation("审图管理", "获取完整审图结果", "返回指定任务当前修订的完整审图 JSON。识别尚未完成时返回 409，其他用户的数据按不存在处理。"),
    ("PATCH", "/api/reviews/{job_id}"): _operation("审图管理", "保存人工修改的审图结果", "保存完整 review 对象并增加审图修订号。expected_revision 用于乐观锁，版本不一致时返回 409，避免覆盖其他修改。"),
    ("DELETE", "/api/reviews/{job_id}"): _operation("审图管理", "删除审图任务", "删除当前用户的审图记录和相关文件；识别进行中时先标记取消，由 Worker 完成清理。该操作不可通过接口撤销。"),
    ("GET", "/api/reviews/{job_id}/changes"): _operation("审图管理", "查询审图修改历史", "按时间返回人工确认、标准化和 AI 对话产生的审计事件，最多返回 500 条。"),
    ("GET", "/api/reviews/{job_id}/download"): _operation("审图管理", "下载审图 JSON", "下载指定审图任务当前保存的完整 JSON 文件。"),
    ("GET", "/api/reviews/{job_id}/artifacts/{relative_path}"): _operation("审图管理", "下载审图过程产物", "下载原始图纸、预览图或识别中间文件；路径必须位于该任务安全目录内。"),
    ("POST", "/api/reviews/standardize"): _operation("标准化与合理性", "标准化临时审图数据", "标准化请求体中的 review，但不写入指定审图任务；适用于导入但尚未持久化的本地 JSON。"),
    ("POST", "/api/reviews/reasonableness"): _operation("标准化与合理性", "核对参数合理性", "对当前 review 执行确定性几何与参数关系检查，返回警告、阻断问题和派生参数预览，不直接保存数据。"),
    ("POST", "/api/reviews/{job_id}/standardize"): _operation("标准化与合理性", "标准化并保存审图参数", "对已保存审图单执行规则或 LLM 标准化，保存结果、增加修订号并记录审计事件；expected_revision 不一致时返回 409。"),
    ("POST", "/api/reviews/standardization-chat"): _operation("标准化与合理性", "对临时审图数据进行标准化对话", "根据 review 和用户消息生成标准化建议、参数修改结果或生图参数包导出动作。明确的“按一级、二级或三级精度标准化”指令会直接选择通用精度并重新计算建议；“导出参数包”只返回本地白名单下载动作，不创建生图任务。"),
    ("POST", "/api/reviews/{job_id}/standardization-chat"): _operation("标准化与合理性", "对已保存审图单进行标准化对话", "结合当前审图参数和标准知识处理用户指令。通用精度标准化会在同一事务中选择精度并重新计算建议；“导出参数包”会重新校验生图就绪状态，前端随后从正式 generation-package 接口下载并核对审图修订号，不创建生图任务。"),
    ("POST", "/api/reviews/{job_id}/parameter-change-proposals/{proposal_id}/apply"): _operation("标准化与合理性", "应用完整参数修改方案", "按方案版本和审图修订执行乐观锁校验，重新求解全部关联参数并原子写入。ready 或 warning 方案可以应用；过期、缺信息或存在冲突时返回409。"),
    ("POST", "/api/reviews/{job_id}/parameter-change-proposals/{proposal_id}/discard"): _operation("标准化与合理性", "放弃参数修改方案", "关闭尚未应用的方案草稿并保存审计事件，不修改正式参数；已应用或版本已变化时返回409。"),
    ("GET", "/api/reviews/{job_id}/generation-readiness"): _operation("生图准备", "检查审图是否可以生图", "由服务端根据当前审图修订重新计算缺失字段、待确认字段、警告和参数矛盾，是前端启用“生成图纸”的唯一可信依据。标准化为可选功能；未标准化、标准未确认或标准化结果过期只产生警告，不阻止按当前人工确认参数生图。"),
    ("GET", "/api/reviews/{job_id}/generation-package"): _operation("生图准备", "获取 SolidWorks 生图参数包", "仅 ready 或 ready_with_warnings 状态返回冻结的 spring_generation_parameters/v1 参数快照。spring_parameters 固定包含线径、中径、自由长度、总圈数、有效圈数、旋向、两端磨削和端圈压并八个字段；SolidWorks 根据中径和线径计算外径、内径。未执行标准化时 standard_context 保持空值，参数包仍可用于生图；其他未就绪状态返回 409 和具体原因。"),
    ("POST", "/api/reviews/{job_id}/generation-template-match"): _operation("生图准备", "匹配 SolidWorks 生图模板", "根据图纸类型、必填字段、匹配规则和优先级返回模板候选；可指定 template_code，也可由后端自动选择。"),
    ("GET", "/api/generation-templates"): _operation("模板查询", "查询启用的生图模板", "返回当前启用的模板及匹配规则、参数映射和 Worker 能力要求；不返回已禁用版本。"),
    ("GET", "/api/generation-templates/{template_code}/versions"): _operation("模板查询", "查询模板的启用版本", "返回指定 template_code 当前所有启用版本；模板代码可包含斜杠。"),
    ("POST", "/api/reviews/{job_id}/generation-jobs"): _operation("生图任务", "创建生图任务", "校验审图修订、八个建模参数、技术要求、参数合理性和模板后创建不可变参数快照。标准化为可选功能；未应用的标准化建议不会进入参数包。新任务返回 202；相同 idempotency_key 和相同请求返回原任务及 200。"),
    ("GET", "/api/reviews/{job_id}/generation-jobs"): _operation("生图任务", "查询审图单的全部生图版本", "返回指定审图单的全部生图任务，并标记最终版本和因审图修订变化而过期的版本。"),
    ("GET", "/api/generation-jobs/{generation_id}"): _operation("生图任务", "查询生图任务详情", "返回任务状态、阶段、进度、模板、参数哈希、租约、错误和产物摘要，供前端轮询。"),
    ("POST", "/api/generation-jobs/{generation_id}/cancel"): _operation("生图任务", "取消生图任务", "取消排队中或正在处理的任务；Worker 后续使用旧租约更新时将收到冲突响应。"),
    ("POST", "/api/generation-jobs/{generation_id}/retry"): _operation("生图任务", "重试失败的生图任务", "使用任务原有参数快照和模板重新排队，清除旧失败产物并增加尝试次数；参数修改后应创建新任务。"),
    ("POST", "/api/generation-jobs/{generation_id}/approve"): _operation("生图任务", "设为最终生图版本", "仅允许确认已完成且对应当前审图修订的任务；同一审图单只保留一个最终版本。模拟任务会保留 is_mock 标识。"),
    ("GET", "/api/generation-jobs/{generation_id}/artifacts"): _operation("生成产物", "查询生图任务产物", "列出任务上传的 PNG、PDF、模型、清单和日志文件，包含大小、MIME、SHA-256 和模拟标识。"),
    ("GET", "/api/generation-jobs/{generation_id}/artifacts/{artifact_id}"): _operation("生成产物", "下载生图任务产物", "按 artifact_id 下载指定任务的生成文件，并校验当前 ERP 用户的数据权限和安全路径。"),
    ("POST", "/api/admin/generation-templates"): _operation("模板管理", "注册生图模板", "使用管理员 Bearer Key 创建首个模板版本。template_code 与 version 组合必须唯一，模板内容创建后不可直接修改。"),
    ("POST", "/api/admin/generation-templates/{template_code}/versions"): _operation("模板管理", "创建模板新版本", "为已有 template_code 创建不可变新版本；参数映射、匹配规则或能力要求变化时使用此接口。"),
    ("PATCH", "/api/admin/generation-templates/{template_code}/versions/{version}/status"): _operation("模板管理", "启用或禁用模板版本", "只修改指定模板版本的 enabled 状态，不修改模板内容。被禁用版本不参与用户查询和自动匹配。"),
    ("POST", "/api/generation-worker/jobs/claim"): _operation("SolidWorks Worker", "领取兼容的生图任务", "Worker 使用独立 Bearer Key 和 capabilities 原子领取最早兼容任务并获得租约；成功响应的 generation_job.parameter_package 直接展开冻结的八字段参数包，当前无任务时返回 204。"),
    ("POST", "/api/generation-worker/jobs/{generation_id}/heartbeat"): _operation("SolidWorks Worker", "续期生图任务租约", "当前持有租约的 Worker 上报心跳、阶段和进度并延长租约；旧 Worker 或租约失效时返回 409。"),
    ("PATCH", "/api/generation-worker/jobs/{generation_id}/status"): _operation("SolidWorks Worker", "更新生图任务阶段", "按 generating_3d → generating_2d → uploading 的固定流程更新状态，progress 取值 0 至 99。"),
    ("POST", "/api/generation-worker/jobs/{generation_id}/artifacts"): _operation("SolidWorks Worker", "上传 SolidWorks 生成产物", "以 multipart/form-data 上传文件并记录 MIME、大小、SHA-256 和 is_mock；校验任务租约、文件类型和大小限制。上传 PDF 后服务器自动把第一页转换为 PNG 对比预览，转换失败不丢失原 PDF。"),
    ("POST", "/api/generation-worker/jobs/{generation_id}/complete"): _operation("SolidWorks Worker", "完成生图任务", "当前 Worker 确认任务完成；SolidWorks V1 只需上传 PDF，服务器生成 PNG 对比预览。至少已有一个 PDF 或 PNG 才能完成。"),
    ("POST", "/api/generation-worker/jobs/{generation_id}/failed"): _operation("SolidWorks Worker", "上报生图任务失败", "当前 Worker 保存稳定错误代码和可读错误说明，并将任务置为 failed，供用户查看和重试。"),
}


class ReviewParameterValue(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: Any | None = Field(default=None, description="识别、计算或人工确认后的参数值。")
    unit: str | None = Field(default=None, description="参数单位，例如 mm、N 或 N/mm。")
    tolerance_upper: float | None = Field(default=None, description="上偏差；没有标注时为 null。")
    tolerance_lower: float | None = Field(default=None, description="下偏差；没有标注时为 null。")
    source: list[str] = Field(default_factory=list, description="参数来源，例如 OCR、视觉模型、公式计算或人工确认。")
    evidence: str | None = Field(default=None, description="支持该参数值的图纸文字或计算依据。")
    confidence: float | None = Field(default=None, ge=0, le=1, description="识别置信度，范围为 0 至 1。")
    need_human_review: bool | None = Field(default=None, description="是否仍需人工核对。")


class DrawingSummaryDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    drawing_name: str | None = Field(default=None, description="图纸名称。")
    drawing_no: str | None = Field(default=None, description="图号。")
    version: str | None = Field(default=None, description="图纸版本号。")
    spring_type: str | None = Field(default=None, description="标准化弹簧类型代码，当前生图支持 compression_spring。")
    spring_type_label: str | None = Field(default=None, description="弹簧类型中文名称。")
    material: str | None = Field(default=None, description="图纸标注或确认的材料。")
    unit: str | None = Field(default=None, description="图纸默认尺寸单位。")
    overall_status: str | None = Field(default=None, description="审图总体状态。")
    summary: str | None = Field(default=None, description="审图结果摘要。")


class SpringParametersDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    material: ReviewParameterValue | None = Field(default=None, description="材料。")
    standard_no: ReviewParameterValue | None = Field(default=None, description="执行标准号。")
    accuracy_grade: ReviewParameterValue | None = Field(default=None, description="通用精度等级。")
    diameter_accuracy_grade: ReviewParameterValue | None = Field(default=None, description="直径专项精度等级；存在时优先于通用精度。")
    free_length_accuracy_grade: ReviewParameterValue | None = Field(default=None, description="自由高度专项精度等级；存在时优先于通用精度。")
    load_accuracy_grade: ReviewParameterValue | None = Field(default=None, description="载荷专项精度等级；存在时优先于通用精度。")
    stiffness_accuracy_grade: ReviewParameterValue | None = Field(default=None, description="刚度专项精度等级；存在时优先于通用精度。")
    wire_diameter: ReviewParameterValue | None = Field(default=None, description="线径。")
    outer_diameter: ReviewParameterValue | None = Field(default=None, description="外径。")
    inner_diameter: ReviewParameterValue | None = Field(default=None, description="内径。")
    mean_diameter: ReviewParameterValue | None = Field(default=None, description="中径。")
    free_length: ReviewParameterValue | None = Field(default=None, description="自由长度。")
    body_length: ReviewParameterValue | None = Field(default=None, description="弹簧体长度。")
    solid_height: ReviewParameterValue | None = Field(default=None, description="压并高度。")
    total_coils: ReviewParameterValue | None = Field(default=None, description="总圈数。")
    active_coils: ReviewParameterValue | None = Field(default=None, description="有效圈数。")
    end_coils: ReviewParameterValue | None = Field(default=None, description="端圈数。")
    handedness: ReviewParameterValue | None = Field(default=None, description="旋向。")
    pitch: ReviewParameterValue | None = Field(default=None, description="节距。")
    end_type: ReviewParameterValue | None = Field(default=None, description="端部结构形式。")
    end_grinding: ReviewParameterValue | None = Field(default=None, description="端面磨削方式。")
    spring_rate: ReviewParameterValue | None = Field(default=None, description="弹簧刚度。")
    load_points: list[dict[str, Any]] = Field(default_factory=list, description="载荷测试点，通常包含高度和力值。")


class ReviewDocument(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={"examples": [{
            "drawing_summary": {"drawing_no": "SPRING-001", "spring_type": "compression_spring", "unit": "mm"},
            "spring_parameters": {
                "wire_diameter": {"value": 2.0, "unit": "mm", "source": ["human_confirmed"], "need_human_review": False},
                "outer_diameter": {"value": 20.0, "unit": "mm", "source": ["human_confirmed"], "need_human_review": False},
                "free_length": {"value": 50.0, "unit": "mm", "source": ["human_confirmed"], "need_human_review": False},
            },
            "review_revision": 3,
        }]},
    )

    drawing_summary: DrawingSummaryDocument = Field(default_factory=DrawingSummaryDocument, description="图纸基本信息与总体审查结论。")
    spring_parameters: SpringParametersDocument = Field(default_factory=SpringParametersDocument, description="识别、推导和人工确认的弹簧参数。")
    derived_parameters: dict[str, Any] = Field(default_factory=dict, description="根据已知参数计算出的派生参数。")
    standard_selection: dict[str, Any] = Field(default_factory=dict, description="标准选择、适用性和人工确认信息。")
    parameter_reasonableness: dict[str, Any] | None = Field(default=None, description="最近一次参数合理性诊断结果。")
    parameter_reasonableness_stale: bool = Field(default=False, description="参数变化后合理性结果是否已经过期。")
    conflicts: list[dict[str, Any]] = Field(default_factory=list, description="不同识别来源之间的参数冲突。")
    missing_fields: list[str] = Field(default_factory=list, description="当前缺失的必要字段。")
    change_history: list[dict[str, Any]] = Field(default_factory=list, description="参数修改与确认历史。")
    review_revision: int | None = Field(default=None, description="审图修订号，每次持久化修改后递增。")


class StandardizePayloadRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    review: ReviewDocument = Field(description="需要标准化的完整审图数据。")
    use_llm_standardization: bool = Field(default=False, description="是否调用大模型补充标准化建议。")


class ExistingStandardizeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    review: ReviewDocument | None = Field(default=None, description="可选；省略时读取数据库中的当前审图数据。")
    expected_revision: int | None = Field(default=None, ge=1, description="客户端当前审图修订号，用于防止并发覆盖。")
    use_llm_standardization: bool = Field(default=False, description="是否调用大模型补充标准化建议。")


class ReasonablenessRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    review: ReviewDocument = Field(description="需要执行参数合理性核对的审图数据。")


class StandardizationChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    review: ReviewDocument = Field(description="当前完整审图数据。")
    message: str = Field(
        min_length=1,
        description="用户的标准化、参数调整或生图参数包导出指令。",
        examples=["请按当前标准核对线径和自由长度。", "导出参数包"],
    )
    use_llm: bool = Field(default=False, description="是否调用大模型处理本轮对话。")
    supplements: dict[str, Any] | None = Field(default=None, description="上一轮要求补充的工况或参数信息。")
    active_proposal_id: str | None = Field(default=None, description="需要继续调整的参数修改方案 ID；省略时使用当前活动方案。")


class ExistingStandardizationChatRequest(StandardizationChatRequest):
    review: ReviewDocument | None = Field(default=None, description="可选；省略时读取数据库中的当前审图数据。")
    expected_revision: int | None = Field(default=None, ge=1, description="客户端当前审图修订号，用于防止并发覆盖。")


class ReviewAuditEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    client_event_id: str | None = Field(default=None, description="前端生成的幂等事件 ID。")
    event_type: str = Field(default="manual_review_updated", description="事件类型。")
    target_field: str | None = Field(default=None, description="发生变化的参数字段。")
    source: str = Field(default="manual", description="修改来源。")
    reason: str | None = Field(default=None, description="修改原因。")
    before_state: dict[str, Any] | None = Field(default=None, description="修改前状态。")
    after_state: dict[str, Any] | None = Field(default=None, description="修改后状态。")
    metadata: dict[str, Any] = Field(default_factory=dict, description="事件扩展信息。")


class SaveReviewRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    review: ReviewDocument = Field(description="需要保存的完整审图数据。")
    expected_revision: int | None = Field(default=None, ge=1, description="客户端当前审图修订号，用于乐观锁。")
    events: list[ReviewAuditEvent] = Field(default_factory=list, description="本次保存附带的参数修改事件，最多处理 100 条。")


class ReviewCreateResponse(BaseModel):
    job_id: str = Field(description="新建的审图任务 ID。")
    drawing_name: str | None = Field(default=None, description="上传图纸文件名。")
    recognition_status: str = Field(description="识别任务状态，创建时通常为 queued。")
    recognition_stage: str | None = Field(default=None, description="当前识别阶段。")
    recognition_progress: int | None = Field(default=None, description="识别进度百分比。")
    queue_position: int | None = Field(default=None, description="当前排队位置。")
    message: str = Field(description="任务创建结果说明。")


class RecognitionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str = Field(description="审图任务 ID。")
    recognition: dict[str, Any] = Field(description="识别状态、阶段、进度、错误和预览地址。")


class ReviewListResponse(BaseModel):
    reviews: list[dict[str, Any]] = Field(default_factory=list, description="当前 ERP 用户可访问的审图记录。")
    persistence: dict[str, Any] | None = Field(default=None, description="持久化运行模式和状态。")


class StandardizationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str | None = Field(default=None, description="持久化版本对应的审图任务 ID。")
    review_revision: int | None = Field(default=None, description="保存后的审图修订号。")
    warnings: list[str] = Field(default_factory=list, description="标准化过程产生的警告。")
    llm_standardization: dict[str, Any] | None = Field(default=None, description="大模型标准化摘要。")
    review: ReviewDocument = Field(description="标准化后的完整审图数据。")


class ReasonablenessResponse(BaseModel):
    parameter_reasonableness: dict[str, Any] = Field(description="参数合理性状态、问题列表和派生参数预览。")


class ParameterImpactRiskDelta(BaseModel):
    introduced: list[dict[str, Any]] = Field(default_factory=list, description="本次修改新引入的合理性或协议风险。")
    resolved: list[dict[str, Any]] = Field(default_factory=list, description="本次修改消除的原有风险。")
    unchanged_count: int = Field(default=0, ge=0, description="修改前后均存在的风险数量。")


class ParameterImpactGenerationReadiness(BaseModel):
    model_config = ConfigDict(extra="allow")

    before_status: str | None = Field(default=None, description="修改前生图就绪状态。")
    after_status: str | None = Field(default=None, description="按建议确认修改后的生图就绪状态。")
    parameter_package_changed: bool = Field(default=False, description="冻结的 SolidWorks 参数包是否发生变化。")
    changed_frozen_fields: list[str] = Field(default_factory=list, description="发生变化的冻结建模字段。")


class ParameterImpactWorkflowEffects(BaseModel):
    standardization_recalculation_required: bool = Field(description="应用后是否需要自动重新标准化。")
    new_generation_required: bool = Field(description="如需反映本次修改，是否应创建新的生图版本。")


class ParameterImpactPreview(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={"examples": [{
            "status": "ready",
            "summary": "修改后未发现新增阻断问题，SolidWorks 参数包将随之更新。",
            "impact_count": 4,
            "direct_changes": [{
                "field": "mean_diameter",
                "label": "中径",
                "change_type": "value",
                "before": 23,
                "after": 25,
                "unit": "mm",
            }],
            "derived_changes": [
                {"field": "outer_diameter", "label": "外径", "before": 26, "after": 28, "unit": "mm"},
                {"field": "inner_diameter", "label": "内径", "before": 20, "after": 22, "unit": "mm"},
            ],
            "risk_delta": {"introduced": [], "resolved": [], "unchanged_count": 0},
            "generation_readiness": {
                "before_status": "ready",
                "after_status": "ready_with_warnings",
                "parameter_package_changed": True,
                "changed_frozen_fields": ["mean_diameter"],
            },
            "workflow_effects": {
                "standardization_recalculation_required": True,
                "new_generation_required": True,
            },
            "baseline_state": {},
        }]},
    )

    status: str = Field(description="影响结论：ready、warning、blocked 或 not_applicable。")
    summary: str = Field(description="面向用户的中文影响摘要。")
    impact_count: int = Field(default=0, ge=0, description="直接变化、派生变化及风险变化的合计数量。")
    direct_changes: list[dict[str, Any]] = Field(default_factory=list, description="参数或公差的当前值与建议值。")
    derived_changes: list[dict[str, Any]] = Field(default_factory=list, description="外径、中径、内径、旋绕比等派生结果变化。")
    risk_delta: ParameterImpactRiskDelta = Field(description="新增、消除和保留的风险。")
    generation_readiness: ParameterImpactGenerationReadiness = Field(description="生图状态和冻结参数包变化。")
    workflow_effects: ParameterImpactWorkflowEffects = Field(description="标准化和生图版本的后续影响。")
    baseline_state: dict[str, Any] = Field(description="生成预览时的审图状态快照，用于阻止应用过期建议。")


class ParameterChangeProposalItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    field: str = Field(description="稳定的英文参数字段代码。")
    label: str = Field(description="与参数页一致的中文名称。")
    before: Any | None = Field(default=None, description="正式参数当前值。")
    after: Any | None = Field(default=None, description="方案应用后的值。")
    unit: str | None = Field(default=None, description="参数单位。")
    confirmation_after: str | None = Field(default=None, description="应用后的确认或计算来源。")
    source_fields: list[str] = Field(default_factory=list, description="自动同步值所依赖的字段代码。")


class ParameterChangeProposal(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={"examples": [{
            "proposal_id": "proposal_123",
            "version": 1,
            "status": "ready",
            "summary": "方案已完成整体校验，将同步更新3项参数。",
            "user_goal": "中径改成26mm，线径不变",
            "direct_changes": [{"field": "mean_diameter", "label": "中径", "before": 42, "after": 26, "unit": "mm"}],
            "synchronized_changes": [
                {"field": "outer_diameter", "label": "外径", "before": 48, "after": 32, "unit": "mm"},
                {"field": "inner_diameter", "label": "内径", "before": 36, "after": 20, "unit": "mm"},
            ],
            "derived_changes": [{"field": "spring_index", "label": "旋绕比", "before": 7, "after": 4.3333}],
            "clarifying_questions": [],
            "blocking_issues": [],
        }]},
    )

    proposal_id: str = Field(description="参数修改方案唯一ID。")
    version: int = Field(ge=1, description="方案版本，每轮继续调整后递增。")
    status: str = Field(description="方案状态：needs_input、ready、warning、blocked、stale、applied或discarded。")
    summary: str = Field(description="中文方案结论。")
    user_goal: str = Field(description="当前方案对应的用户修改目标。")
    direct_changes: list[ParameterChangeProposalItem] = Field(default_factory=list, description="用户明确要求修改的参数。")
    synchronized_changes: list[ParameterChangeProposalItem] = Field(default_factory=list, description="为保持整体一致而必须同步的参数。")
    derived_changes: list[dict[str, Any]] = Field(default_factory=list, description="旋绕比、细长比、刚度等计算影响。")
    recommendations: list[dict[str, Any]] = Field(default_factory=list, description="尚未加入应用范围的可选调整建议。")
    constraints: list[dict[str, Any]] = Field(default_factory=list, description="用户在多轮对话中累计的最大值、最小值或保持不变约束。")
    clarifying_questions: list[str] = Field(default_factory=list, description="形成唯一方案前需要用户补充的问题。")
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list, description="禁止应用的冲突或几何问题。")
    risk_delta: ParameterImpactRiskDelta = Field(description="方案新增、消除和保留的风险。")
    generation_readiness: ParameterImpactGenerationReadiness = Field(description="方案前后的生图状态与冻结参数变化。")
    workflow_effects: ParameterImpactWorkflowEffects = Field(description="标准化和生图版本影响。")


class ParameterChangeProposalCommand(BaseModel):
    version: int = Field(ge=1, description="需要应用或放弃的方案版本。")
    expected_review_revision: int = Field(ge=1, description="客户端当前审图修订号，用于乐观锁。")


class ParameterChangeProposalResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str = Field(description="审图任务ID。")
    review_revision: int | None = Field(default=None, description="操作完成后的审图修订号。")
    persistence: dict[str, Any] = Field(description="持久化模式和修订信息。")
    change_proposal: ParameterChangeProposal = Field(description="操作后的完整方案状态。")
    log_id: str | None = Field(default=None, description="应用方案生成的审计操作ID。")
    review: ReviewDocument = Field(description="操作后的完整审图数据。")


class AccuracyStandardizationResult(BaseModel):
    status: str = Field(description="执行状态；完成时为 completed。", examples=["completed"])
    requested_grade: str | None = Field(default=None, description="用户要求的通用精度等级，仅允许1级、2级或3级。", examples=["1级"])
    previous_grade: str | None = Field(default=None, description="执行前的通用精度等级。", examples=["2级"])
    scope: str = Field(default="general", description="精度作用范围；第一版仅执行 general。")
    selection_changed: bool | None = Field(default=None, description="精度值、来源或确认状态是否实际发生变化。")
    specialized_grades_retained: dict[str, str] = Field(
        default_factory=dict,
        description="保持不变并继续优先的专项精度等级。",
        examples=[{"diameter_accuracy_grade": "2级"}],
    )
    standardization_result_count: int = Field(default=0, ge=0, description="重新计算得到的标准化建议数量。")
    warnings: list[str] = Field(default_factory=list, description="本轮标准化产生的非阻断警告。")


class StandardizationBatchValue(BaseModel):
    exists: bool = Field(description="应用前该参数栏位是否已经存在。")
    value: Any = Field(default=None, description="参数值；没有值时为 null。")
    tolerance_upper: Any = Field(default=None, description="上偏差；没有公差时为 null。")
    tolerance_lower: Any = Field(default=None, description="下偏差；没有公差时为 null。")
    unit: str = Field(default="", description="参数或载荷值单位。")
    confirmed: bool = Field(default=False, description="该状态是否已经人工确认。")


class StandardizationBatchItem(BaseModel):
    result_index: int = Field(ge=0, description="该项目在本次 standardization_results 中的位置。")
    target_field: str = Field(description="稳定的内部字段代码；前端只展示中文 label。", examples=["free_length"])
    label: str = Field(description="与参数页面一致的中文名称。", examples=["自由长度"])
    rule_id: str = Field(default="", description="产生该建议的标准化规则编号。")
    standard_no: str = Field(default="", description="建议采用的技术标准编号。")
    unit: str = Field(default="", description="建议值单位。")
    before: StandardizationBatchValue = Field(description="应用前的参数值、公差和确认状态。")
    after: StandardizationBatchValue = Field(description="应用后的参数值、公差和确认状态。")
    change_types: list[str] = Field(
        default_factory=list,
        description="实际变化类型：created、value、tolerance 或 confirmation。",
    )
    can_apply: bool = Field(description="该项是否允许由本次‘应用全部’安全写入。")
    reason: str = Field(default="", description="不能应用时的中文原因。")
    basis: str = Field(default="", description="可折叠展示的标准依据，不包含前端计算公式。")


class StandardizationBatch(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "batch_id": "standardization_batch_58c1b20a43b572d1bc17",
                "status": "ready",
                "review_revision": 8,
                "baseline_fingerprint": "58c1b20a43b572d1bc17...",
                "result_fingerprint": "28eed4e1b985...",
                "applicable_count": 2,
                "skipped_count": 1,
                "items": [
                    {
                        "result_index": 1,
                        "target_field": "free_length",
                        "label": "自由长度",
                        "rule_id": "GBT1239.2-FREE",
                        "standard_no": "GB/T 1239.2-2009",
                        "unit": "mm",
                        "before": {"exists": True, "value": 45, "tolerance_upper": 1, "tolerance_lower": -1, "unit": "mm", "confirmed": True},
                        "after": {"exists": True, "value": 45, "tolerance_upper": 0.6, "tolerance_lower": -0.6, "unit": "mm", "confirmed": True},
                        "change_types": ["tolerance"],
                        "can_apply": True,
                        "reason": "",
                        "basis": "按所选精度等级计算自由高度公差。",
                    }
                ],
                "skipped_items": [],
                "baseline_state": {},
                "applied_count": 0,
                "applied_at": None,
            }
        }
    )

    batch_id: str = Field(description="本次标准化结果快照的稳定标识。")
    status: str = Field(description="批次状态：ready、no_changes、applied 或 stale。")
    review_revision: int | None = Field(default=None, description="生成该快照后的审图修订号；本地JSON模式为空。")
    baseline_fingerprint: str = Field(description="生成标准化结果时参数基线的SHA-256。")
    result_fingerprint: str = Field(description="本次标准化建议集合的SHA-256。")
    applicable_count: int = Field(default=0, ge=0, description="可以由‘应用全部’写入的实际变化项数量。")
    skipped_count: int = Field(default=0, ge=0, description="因缺条件、冲突、不适用或过期而跳过的数量。")
    items: list[StandardizationBatchItem] = Field(default_factory=list, description="会实际修改参数栏位的安全建议。")
    skipped_items: list[StandardizationBatchItem] = Field(default_factory=list, description="不会写入的建议及中文原因。")
    baseline_state: dict[str, Any] = Field(default_factory=dict, description="用于应用前检查结果是否过期的基线快照。")
    applied_count: int = Field(default=0, ge=0, description="已成功写入的项目数量。")
    applied_at: str | None = Field(default=None, description="成功应用时间；未应用时为空。")


class GenerationPackageExportField(BaseModel):
    field: str = Field(description="稳定的协议字段代码；界面只展示对应中文名称。", examples=["mean_diameter"])
    label: str = Field(description="与参数页一致的中文名称。", examples=["中径"])
    value: Any = Field(default=None, description="执行导出校验时的参数值。")
    unit: str | None = Field(default=None, description="参数单位。", examples=["mm"])


class GenerationPackageExportAction(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ready_with_warnings",
                "source_mode": "server",
                "filename": "compression_spring_generation_parameters.json",
                "schema_version": "spring_generation_parameters/v1",
                "review_revision": 12,
                "can_download": True,
                "automatic_download": True,
                "action_type": "download_generation_package",
                "parameter_fields": [
                    {"field": "wire_diameter", "label": "线径", "value": 3, "unit": "mm"},
                    {"field": "mean_diameter", "label": "中径", "value": 23, "unit": "mm"},
                ],
                "missing_fields": [],
                "pending_fields": [],
                "blocking_reasonableness": [],
                "warnings": [
                    {"field": "standard_no", "label": "适用标准", "reason": "未执行标准化检查；可按当前人工确认参数直接导出。"}
                ],
                "download_status": "pending",
                "downloaded_at": None,
                "failure_reason": "",
                "baseline_state": {},
            }
        }
    )

    status: str = Field(description="服务端重新计算的生图就绪状态。", examples=["ready_with_warnings"])
    source_mode: str = Field(description="参数包来源：server 为正式审图，local 为本地导入JSON。", examples=["server"])
    filename: str = Field(description="建议下载文件名。", examples=["compression_spring_generation_parameters.json"])
    schema_version: str = Field(description="冻结参数包协议版本。", examples=["spring_generation_parameters/v1"])
    review_revision: int | None = Field(default=None, description="生成该导出动作时的审图修订号；本地模式为空。")
    can_download: bool = Field(description="当前是否允许下载。")
    automatic_download: bool = Field(description="前端收到本轮响应后是否应立即触发下载。")
    action_type: str = Field(description="前端动作；可下载时为 download_generation_package，否则为 resolve_generation_readiness。")
    parameter_fields: list[GenerationPackageExportField] = Field(default_factory=list, description="冻结8个SolidWorks建模字段摘要。")
    missing_fields: list[dict[str, Any]] = Field(default_factory=list, description="缺失字段及中文原因。")
    pending_fields: list[dict[str, Any]] = Field(default_factory=list, description="待人工确认字段及中文原因。")
    blocking_reasonableness: list[dict[str, Any]] = Field(default_factory=list, description="阻止导出的合理性问题。")
    warnings: list[dict[str, Any]] = Field(default_factory=list, description="不阻止下载但需要用户知悉的警告。")
    download_status: str = Field(description="初始下载状态；浏览器可在本地更新为 downloading、downloaded、failed 或 stale。")
    downloaded_at: str | None = Field(default=None, description="浏览器成功触发下载的时间；初始为空。")
    failure_reason: str = Field(default="", description="自动下载失败时的中文原因。")
    baseline_state: dict[str, Any] = Field(default_factory=dict, description="本地JSON模式用来判断旧导出卡是否过期的参数基线。")


class StandardizationChatResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str | None = Field(default=None, description="持久化版本对应的审图任务 ID。")
    review_revision: int | None = Field(default=None, description="保存后的审图修订号。")
    answer: str | None = Field(default=None, description="本轮 AI 对话答复。")
    reply: str | None = Field(default=None, description="本轮AI返回的中文回复。")
    intent: dict[str, Any] | None = Field(default=None, description="识别出的用户意图、目标字段和处理状态。")
    suggested_actions: list[dict[str, Any]] = Field(default_factory=list, description="需要用户确认后才能写回的结构化修改建议；每项可包含 impact_preview。")
    impact_preview: ParameterImpactPreview | None = Field(default=None, description="本轮全部参数建议同时应用时的确定性影响预览。")
    change_proposal: ParameterChangeProposal | None = Field(default=None, description="本轮生成或更新的完整参数修改方案。")
    accuracy_standardization: AccuracyStandardizationResult | None = Field(
        default=None,
        description="按通用精度等级直接标准化的执行结果；普通对话时为空。",
    )
    standardization_batch: StandardizationBatch | None = Field(
        default=None,
        description="执行型标准化生成的实际变化快照和一键应用范围；普通问答及参数修改方案为空。",
    )
    generation_package_export: GenerationPackageExportAction | None = Field(
        default=None,
        description="AI对话导出生图参数包的校验结果和前端下载动作；普通对话时为空。",
    )
    turn: dict[str, Any] | None = Field(default=None, description="已经写入审图记录的本轮对话，其中单项建议包含各自的影响预览。")
    review: ReviewDocument = Field(description="应用本轮对话结果后的审图数据。")


class SaveReviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str = Field(description="审图任务 ID。")
    review_revision: int | None = Field(default=None, description="保存后的审图修订号。")
    persistence: dict[str, Any] = Field(description="持久化模式和修订信息。")
    events: list[dict[str, Any]] = Field(default_factory=list, description="已经保存的审计事件。")


class DeleteReviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str = Field(description="审图任务 ID。")
    deleted: bool = Field(description="是否已接受删除操作。")
    status: str | None = Field(default=None, description="删除或取消清理状态。")
    artifact_cleanup: str | None = Field(default=None, description="文件清理结果。")


class ReviewChangesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str = Field(description="审图任务 ID。")
    events: list[dict[str, Any]] = Field(default_factory=list, description="按时间返回的审图修改事件。")


class ApiErrorResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    detail: str | dict[str, Any] | list[dict[str, Any]] = Field(description="错误说明或结构化业务错误详情。")


DOCUMENTATION_MODELS: tuple[type[BaseModel], ...] = (
    ReviewParameterValue,
    DrawingSummaryDocument,
    SpringParametersDocument,
    ReviewDocument,
    StandardizePayloadRequest,
    ExistingStandardizeRequest,
    ReasonablenessRequest,
    StandardizationChatRequest,
    ExistingStandardizationChatRequest,
    ReviewAuditEvent,
    SaveReviewRequest,
    ReviewCreateResponse,
    RecognitionStatusResponse,
    ReviewListResponse,
    StandardizationResponse,
    ReasonablenessResponse,
    ParameterImpactRiskDelta,
    ParameterImpactGenerationReadiness,
    ParameterImpactWorkflowEffects,
    ParameterImpactPreview,
    ParameterChangeProposalItem,
    ParameterChangeProposal,
    ParameterChangeProposalCommand,
    ParameterChangeProposalResponse,
    StandardizationChatResponse,
    SaveReviewResponse,
    DeleteReviewResponse,
    ReviewChangesResponse,
    ApiErrorResponse,
)


REQUEST_MODELS: dict[tuple[str, str], type[BaseModel]] = {
    ("POST", "/api/reviews/standardize"): StandardizePayloadRequest,
    ("POST", "/api/reviews/reasonableness"): ReasonablenessRequest,
    ("POST", "/api/reviews/{job_id}/standardize"): ExistingStandardizeRequest,
    ("POST", "/api/reviews/standardization-chat"): StandardizationChatRequest,
    ("POST", "/api/reviews/{job_id}/standardization-chat"): ExistingStandardizationChatRequest,
    ("POST", "/api/reviews/{job_id}/parameter-change-proposals/{proposal_id}/apply"): ParameterChangeProposalCommand,
    ("POST", "/api/reviews/{job_id}/parameter-change-proposals/{proposal_id}/discard"): ParameterChangeProposalCommand,
    ("PATCH", "/api/reviews/{job_id}"): SaveReviewRequest,
}

RESPONSE_MODELS: dict[tuple[str, str], tuple[str, type[BaseModel]]] = {
    ("POST", "/api/reviews"): ("202", ReviewCreateResponse),
    ("GET", "/api/reviews"): ("200", ReviewListResponse),
    ("GET", "/api/reviews/{job_id}"): ("200", ReviewDocument),
    ("PATCH", "/api/reviews/{job_id}"): ("200", SaveReviewResponse),
    ("DELETE", "/api/reviews/{job_id}"): ("200", DeleteReviewResponse),
    ("GET", "/api/reviews/{job_id}/recognition-status"): ("200", RecognitionStatusResponse),
    ("POST", "/api/reviews/{job_id}/retry"): ("202", RecognitionStatusResponse),
    ("GET", "/api/reviews/{job_id}/changes"): ("200", ReviewChangesResponse),
    ("POST", "/api/reviews/standardize"): ("200", StandardizationResponse),
    ("POST", "/api/reviews/{job_id}/standardize"): ("200", StandardizationResponse),
    ("POST", "/api/reviews/reasonableness"): ("200", ReasonablenessResponse),
    ("POST", "/api/reviews/standardization-chat"): ("200", StandardizationChatResponse),
    ("POST", "/api/reviews/{job_id}/standardization-chat"): ("200", StandardizationChatResponse),
    ("POST", "/api/reviews/{job_id}/parameter-change-proposals/{proposal_id}/apply"): ("200", ParameterChangeProposalResponse),
    ("POST", "/api/reviews/{job_id}/parameter-change-proposals/{proposal_id}/discard"): ("200", ParameterChangeProposalResponse),
}


PARAMETER_DOCUMENTATION = {
    "job_id": ("审图任务 ID。", "review-123"),
    "generation_id": ("生图任务 ID。", "generation-123"),
    "artifact_id": ("生成产物 ID。", "artifact-123"),
    "relative_path": ("审图任务目录内的相对文件路径。", "previews/page-1.png"),
    "template_code": ("模板代码，可包含斜杠。", "mock/compression-spring"),
    "version": ("模板版本号。", "v1"),
    "proposal_id": ("参数修改方案 ID。", "proposal_123"),
    "standard_no": ("标准号。", "GB/T 1239.2-2009"),
    "spring_type": ("弹簧类型代码。", "compression_spring"),
    "target_fields": ("目标字段，多个字段使用英文逗号分隔。", "wire_diameter,free_length"),
    "query": ("自然语言检索问题。", "自由长度允许偏差是多少"),
    "limit": ("最大返回数量。", 20),
}

FIELD_DESCRIPTIONS = {
    "drawing": "必填；需要识别的 PDF 或图片图纸。",
    "candidate_json": "可选；外部系统提供的候选参数 JSON。",
    "ocr_json": "可选；外部系统提供的 OCR JSON。",
    "use_werk24": "是否调用可选的 Werk24 外部识别服务。",
    "confirm_upload_to_werk24": "是否明确确认将图纸发送至外部 Werk24 服务。",
    "use_cached_werk24": "是否优先使用已有 Werk24 缓存结果。",
    "use_ocr": "是否执行 OCR 识别。",
    "ocr_provider": "OCR 提供方代码；省略时由服务端自动选择。",
    "use_qwen": "是否使用通义千问视觉识别。",
    "use_geometry": "是否执行几何识别。",
    "use_vlm": "是否执行可选视觉模型复核。",
    "use_llm_standardization": "是否调用大模型生成标准化建议。",
    "vision_provider": "视觉识别提供方代码。",
    "use_paddleocr": "兼容字段；是否使用旧 PaddleOCR 路径。",
    "use_sample_ocr": "是否使用内置示例 OCR 数据。",
    "field": "参数字段代码。",
    "label": "供用户查看的名称。",
    "reason": "状态、匹配或问题原因。",
    "status": "当前状态代码。",
    "summary": "当前结果的可读摘要。",
    "missing_fields": "缺失的生图必要字段。",
    "pending_fields": "已有值但仍待人工确认的字段。",
    "warnings": "不阻止当前操作的警告。",
    "confirmed_core_count": "已确认的核心参数数量。",
    "core_field_count": "核心参数总数量。",
    "parameter_reasonableness": "参数合理性检查结果。",
    "blocking_reasonableness": "阻止生图的参数矛盾。",
    "template_code": "稳定的模板代码。",
    "version": "模板版本号。",
    "drawing_type": "模板适用的图纸类型。",
    "priority": "模板匹配优先级，数值越大越优先。",
    "enabled": "模板版本是否启用。",
    "is_mock": "是否为模拟产物或模拟模板。",
    "required_fields": "模板要求必须存在的参数字段。",
    "match_rules": "模板自动匹配规则。",
    "parameter_mapping": "审图参数到 SolidWorks 模板尺寸或属性的映射。",
    "worker_capability": "能够处理该模板的 Worker 能力代码。",
    "created_at": "创建时间，ISO 8601 格式。",
    "updated_at": "最后更新时间，ISO 8601 格式。",
    "match_score": "模板匹配得分。",
    "selected_template": "自动或人工指定后选中的模板。",
    "candidates": "满足基本条件的模板候选。",
    "artifact_id": "生成产物 ID。",
    "generation_id": "生图任务 ID。",
    "artifact_type": "产物类型，例如 png、pdf、sldprt 或 model_manifest。",
    "filename": "原始或安全化后的文件名。",
    "mime_type": "文件 MIME 类型。",
    "size_bytes": "文件大小，单位为字节。",
    "sha256": "文件内容 SHA-256。",
    "url": "当前用户可访问的产物下载地址。",
    "review_id": "关联的审图任务 ID。",
    "review_revision": "任务创建时固化的审图修订号。",
    "parent_generation_id": "参数修改后再次生图所关联的上一版本任务 ID。",
    "template_version": "任务固化的模板版本。",
    "parameter_schema_version": "生图参数包的 Schema 版本。",
    "parameter_hash": "规范化参数包的 SHA-256。",
    "parameter_package": "任务创建时固化的生图参数快照。",
    "readiness": "任务创建时固化的生图就绪状态。",
    "requested_artifact_types": "调用方希望 Worker 生成的产物类型；SolidWorks V1 默认仅为 pdf。",
    "execution_options": "任务执行选项；模拟模式包含 mock_scenario。",
    "stage": "当前处理阶段。",
    "progress": "当前进度百分比。",
    "error_code": "稳定的机器可读错误代码。",
    "error_message": "供用户或开发人员查看的错误说明。",
    "attempt_count": "任务领取或重试次数。",
    "worker_id": "当前 Worker 的唯一标识。",
    "lease_expires_at": "当前 Worker 租约过期时间。",
    "is_final": "是否为审图单选定的最终版本。",
    "is_stale": "任务参数是否已落后于当前审图修订。",
    "approved_by": "确认最终版本的 ERP 用户信息。",
    "approved_at": "确认最终版本的时间。",
    "started_at": "首次开始处理的时间。",
    "completed_at": "完成时间。",
    "artifacts": "任务已上传的产物摘要。",
    "expected_review_revision": "客户端当前审图修订号，用于乐观锁。",
    "idempotency_key": "调用方生成的幂等键，防止重复创建任务。",
    "mock_scenario": "模拟 Worker 测试场景：success、fail_3d、fail_2d 或 timeout。",
    "capabilities": "Worker 支持的能力代码列表。",
    "file": "需要上传的生成产物文件。",
}

RESPONSE_DESCRIPTIONS = {
    "200": "请求成功。",
    "201": "资源创建成功。",
    "202": "请求已接受并进入异步处理。",
    "204": "当前没有可返回的内容。",
    "400": "请求参数或业务输入不合法。",
    "401": "缺少有效的 ERP 身份或 API Key。",
    "404": "资源不存在，或不属于当前 ERP 用户。",
    "409": "修订、幂等键、任务状态、模板选择或 Worker 租约发生冲突。",
    "413": "上传文件超过配置的大小限制。",
    "415": "上传文件类型与 artifact_type 不匹配。",
    "422": "请求字段格式未通过 Pydantic 校验。",
    "503": "数据库、识别队列或生图队列当前不可用。",
}

ERROR_EXAMPLES: dict[str, dict[str, Any]] = {
    "400": {"detail": "请求参数或业务输入不合法。"},
    "401": {"detail": "缺少或未提供有效身份凭据。"},
    "404": {"detail": "资源不存在或无权访问。"},
    "409": {"detail": {"error": "revision_conflict", "message": "当前数据修订已变化，请刷新后重试。"}},
    "413": {"detail": "上传文件超过允许的大小限制。"},
    "415": {"detail": "上传文件类型不受支持。"},
    "422": {"detail": [{"loc": ["body", "field"], "msg": "字段校验失败", "type": "value_error"}]},
    "503": {"detail": "当前依赖服务不可用，请稍后重试。"},
}


def apply_chinese_openapi_documentation(schema: dict[str, Any]) -> dict[str, Any]:
    """Apply documentation-only metadata without changing runtime API behavior."""
    info = schema.setdefault("info", {})
    info.update({
        "title": API_TITLE,
        "summary": API_SUMMARY,
        "description": API_DESCRIPTION,
    })
    schema["tags"] = OPENAPI_TAGS
    schema["x-tagGroups"] = OPENAPI_TAG_GROUPS

    components = schema.setdefault("components", {})
    component_schemas = components.setdefault("schemas", {})
    _inject_documentation_models(component_schemas)
    _describe_component_schemas(component_schemas)

    security_schemes = components.setdefault("securitySchemes", {})
    cookie_name = str(os.getenv("ERP_IDENTITY_COOKIE_NAME", "erp_review_identity") or "erp_review_identity").strip()
    security_schemes["ErpIdentityCookie"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": cookie_name,
        "description": "ERP 注入的用户身份 Cookie；本地 mock 身份模式无需填写。",
    }
    security_schemes.setdefault("GenerationAdminBearer", {"type": "http", "scheme": "bearer"})["description"] = (
        "模板管理员 API Key，对应 GENERATION_ADMIN_API_KEY。"
    )
    security_schemes.setdefault("GenerationWorkerBearer", {"type": "http", "scheme": "bearer"})["description"] = (
        "SolidWorks Worker API Key，对应 GENERATION_WORKER_API_KEY。"
    )

    actual: set[tuple[str, str]] = set()
    documented: set[tuple[str, str]] = set()
    http_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE"}
    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            key = (str(method).upper(), str(path))
            if key[0] not in http_methods:
                continue
            actual.add(key)
            if key not in OPERATION_DOCS:
                continue
            documented.add(key)
            documentation = OPERATION_DOCS[key]
            tag = documentation["tag"]
            operation["tags"] = [tag]
            operation["summary"] = documentation["summary"]
            operation["description"] = documentation["description"]
            operation["x-display-name"] = documentation["summary"]
            _document_parameters(operation)
            _apply_documented_request_schema(key, operation)
            _apply_documented_response_schema(key, operation)
            _apply_operation_security_and_responses(key, tag, operation)

    stale_mappings = set(OPERATION_DOCS) - actual
    undocumented = actual - set(OPERATION_DOCS)
    if stale_mappings or undocumented or documented != actual:
        raise RuntimeError(
            "OpenAPI documentation mapping is inconsistent: "
            f"stale_mappings={sorted(stale_mappings)}, undocumented={sorted(undocumented)}"
        )
    return schema


def _inject_documentation_models(component_schemas: dict[str, Any]) -> None:
    for model in DOCUMENTATION_MODELS:
        generated = model.model_json_schema(ref_template="#/components/schemas/{model}")
        definitions = generated.pop("$defs", {})
        component_schemas.update(definitions)
        component_schemas[model.__name__] = generated


def _describe_component_schemas(component_schemas: dict[str, Any]) -> None:
    for name, model_schema in component_schemas.items():
        model_schema.setdefault("description", f"{name} 数据模型。")
        for field_name, field_schema in (model_schema.get("properties") or {}).items():
            if isinstance(field_schema, dict):
                field_schema.setdefault(
                    "description",
                    FIELD_DESCRIPTIONS.get(field_name, f"接口字段 `{field_name}`；具体含义见所属接口说明。"),
                )


def _document_parameters(operation: dict[str, Any]) -> None:
    for parameter in operation.get("parameters") or []:
        name = str(parameter.get("name") or "")
        description, example = PARAMETER_DOCUMENTATION.get(
            name,
            (f"接口参数 `{name}`。", None),
        )
        parameter["description"] = description
        if example is not None:
            parameter.setdefault("example", example)


def _apply_documented_request_schema(key: tuple[str, str], operation: dict[str, Any]) -> None:
    model = REQUEST_MODELS.get(key)
    if model is None:
        return
    request_body = operation.setdefault("requestBody", {})
    content = request_body.setdefault("content", {})
    json_content = content.setdefault("application/json", {})
    json_content["schema"] = {"$ref": f"#/components/schemas/{model.__name__}"}


def _apply_documented_response_schema(key: tuple[str, str], operation: dict[str, Any]) -> None:
    configured = RESPONSE_MODELS.get(key)
    if configured is None:
        return
    status_code, model = configured
    response = operation.setdefault("responses", {}).setdefault(status_code, {})
    response.setdefault("description", RESPONSE_DESCRIPTIONS[status_code])
    response.setdefault("content", {}).setdefault("application/json", {})["schema"] = {
        "$ref": f"#/components/schemas/{model.__name__}"
    }


def _apply_operation_security_and_responses(key: tuple[str, str], tag: str, operation: dict[str, Any]) -> None:
    method, path = key
    public_tags = {"系统状态"}
    if tag == "模板管理":
        operation["security"] = [{"GenerationAdminBearer": []}]
    elif tag == "SolidWorks Worker":
        operation["security"] = [{"GenerationWorkerBearer": []}]
    elif tag not in public_tags:
        operation["security"] = [{"ErpIdentityCookie": []}]
    else:
        operation["security"] = []

    responses = operation.setdefault("responses", {})
    for code, response in responses.items():
        if isinstance(response, dict) and code in RESPONSE_DESCRIPTIONS:
            response["description"] = RESPONSE_DESCRIPTIONS[code]
    if operation.get("security"):
        responses.setdefault("401", {"description": RESPONSE_DESCRIPTIONS["401"]})
    if "{" in path:
        responses.setdefault("404", {"description": RESPONSE_DESCRIPTIONS["404"]})
    if path.startswith("/api/generation") or "/generation-" in path:
        responses.setdefault("503", {"description": RESPONSE_DESCRIPTIONS["503"]})
    if method in {"POST", "PATCH"}:
        responses.setdefault("400", {"description": RESPONSE_DESCRIPTIONS["400"]})
    if (
        path.startswith("/api/generation")
        or "/generation-" in path
        or (path.startswith("/api/reviews/") and method in {"POST", "PATCH", "DELETE"})
    ):
        responses.setdefault("409", {"description": RESPONSE_DESCRIPTIONS["409"]})
    if method == "POST" and (path == "/api/reviews" or path.endswith("/artifacts")):
        responses.setdefault("413", {"description": RESPONSE_DESCRIPTIONS["413"]})
        responses.setdefault("415", {"description": RESPONSE_DESCRIPTIONS["415"]})

    for code, example in ERROR_EXAMPLES.items():
        response = responses.get(code)
        if not isinstance(response, dict):
            continue
        json_content = response.setdefault("content", {}).setdefault("application/json", {})
        json_content.setdefault("schema", {"$ref": "#/components/schemas/ApiErrorResponse"})
        json_content.setdefault("example", example)
