from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GenerationReadinessIssue(BaseModel):
    model_config = ConfigDict(extra="allow")

    field: str = Field(description="存在问题的参数字段代码。", examples=["wire_diameter"])
    label: str = Field(description="供用户查看的参数名称。", examples=["线径"])
    reason: str = Field(description="缺失、待确认、警告或阻断的具体原因。")


class GenerationReadinessView(BaseModel):
    status: Literal["ready", "ready_with_warnings", "needs_input", "needs_confirmation", "blocked", "not_applicable"] = Field(description="服务端计算的生图就绪状态。")
    summary: str = Field(description="就绪状态的中文摘要。")
    missing_fields: list[GenerationReadinessIssue] = Field(default_factory=list, description="尚未提供值的生图必要字段。")
    pending_fields: list[GenerationReadinessIssue] = Field(default_factory=list, description="已有值但仍待人工确认的字段。")
    warnings: list[GenerationReadinessIssue] = Field(default_factory=list, description="不会阻止本次生图的警告。")
    confirmed_core_count: int = Field(description="已完成人工确认的核心参数数量。")
    core_field_count: int = Field(description="核心参数总数量。")
    defaulted_fields: list[str] = Field(default_factory=list, description="因识别缺失而补入协议默认值、仍待人工确认的字段。")
    parameter_reasonableness: dict[str, Any] | None = Field(default=None, description="参数合理性检查的完整结果。")
    blocking_reasonableness: list[dict[str, Any]] = Field(default_factory=list, description="阻止生图的参数矛盾或合理性问题。")


class GenerationParameterBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="参数中文名称。")
    tolerance_upper: float | None = Field(default=None, description="可选上偏差；SolidWorks V1 建模不依赖该值。")
    tolerance_lower: float | None = Field(default=None, description="可选下偏差；SolidWorks V1 建模不依赖该值。")
    confirmation_source: Literal["human_confirmed"] = Field(description="参数已经人工确认的固定标记。")


class GenerationMillimeterParameter(GenerationParameterBase):
    value: float = Field(gt=0, description="毫米数值，导出时最多保留三位小数。", examples=[3.0])
    unit: Literal["mm"] = Field(description="固定单位 mm。")


class GenerationPositiveIntegerParameter(GenerationParameterBase):
    value: int = Field(gt=0, description="正整数圈数。", examples=[10])
    unit: None = Field(default=None, description="无单位。")


class GenerationHandednessParameter(GenerationParameterBase):
    value: Literal["right", "left"] = Field(description="旋向：right 为右旋，left 为左旋。", examples=["right"])
    unit: None = Field(default=None, description="无单位。")


class GenerationBinaryParameter(GenerationParameterBase):
    value: Literal[0, 1] = Field(description="二值开关，只允许 0 或 1。", examples=[1])
    unit: None = Field(default=None, description="无单位。")


class CompressionSpringGenerationInputsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wire_diameter: GenerationMillimeterParameter = Field(description="线径，默认候选值 3 mm。")
    mean_diameter: GenerationMillimeterParameter = Field(description="中径，默认候选值 23 mm；SolidWorks据此计算外径和内径。")
    free_length: GenerationMillimeterParameter = Field(description="自由长度，默认候选值 45 mm。")
    total_coils: GenerationPositiveIntegerParameter = Field(description="总圈数，默认候选值 10。")
    active_coils: GenerationPositiveIntegerParameter = Field(description="有效圈数，默认候选值 8，且不得大于总圈数。")
    handedness: GenerationHandednessParameter = Field(description="旋向，无默认值，必须人工确认。")
    end_grinding: GenerationBinaryParameter = Field(description="两端磨削：1 表示磨削，0 表示不磨削；默认候选值 1。")
    end_coils_closed: GenerationBinaryParameter = Field(description="端圈压并：1 表示压并，0 表示不压并；默认候选值 1。")


class GenerationTechnicalRequirementV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str | None = Field(default=None, description="技术要求分类代码。")
    content: str = Field(min_length=1, description="已人工确认、写入二维图固定区域的中文技术要求。", examples=["两端磨平，表面镀锌。"])
    confirmation_source: Literal["human_confirmed"] = Field(description="技术要求已经人工确认的固定标记。")


class GenerationParametersV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spring_parameters: CompressionSpringGenerationInputsV1 = Field(description="SolidWorks 必须解析的八个冻结建模字段。")
    technical_requirements: list[GenerationTechnicalRequirementV1] = Field(default_factory=list, description="写入二维图固定区域的中文技术要求。")


class GenerationExportPolicyV1(BaseModel):
    parameter_filter: Literal["frozen_compression_inputs_v1_human_confirmed_only"] = Field(description="固定的参数白名单策略。")
    readiness_is_advisory: bool = Field(description="参数包可导出但创建任务仍必须通过服务端就绪检查。")


class GenerationSourceV1(BaseModel):
    drawing_no: str | None = Field(default=None, description="原图纸编号。")
    drawing_name: str | None = Field(default=None, description="原图纸名称。")
    spring_type: str | None = Field(default=None, description="审图识别的弹簧类型代码。")
    spring_type_label: str | None = Field(default=None, description="弹簧类型中文名称。")


class GenerationStandardContextV1(BaseModel):
    selected_standard: str | None = Field(default=None, description="审图端选定的技术标准，仅用于追溯；直接生图时允许为空。")
    selection_status: str | None = Field(default=None, description="标准选择状态；未执行标准化时允许为空或 not_started。")
    human_confirmed: bool = Field(description="标准选择是否已经人工确认；该值不影响 SolidWorks 对八个建模字段的解析。")


class GenerationParameterPackageV1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{
            "schema_version": "spring_generation_parameters/v1",
            "package_type": "confirmed_compression_spring_generation_input",
            "generated_at": "2026-08-05T08:00:00+00:00",
            "export_policy": {
                "parameter_filter": "frozen_compression_inputs_v1_human_confirmed_only",
                "readiness_is_advisory": True,
            },
            "source": {"drawing_no": "SPRING-001", "drawing_name": "压缩弹簧", "spring_type": "compression_spring", "spring_type_label": "圆柱螺旋压缩弹簧"},
            "standard_context": {"selected_standard": "GB/T 1239.2-2009", "selection_status": "confirmed", "human_confirmed": True},
            "generation_parameters": {
                "spring_parameters": {
                    "wire_diameter": {"label": "线径", "value": 3.0, "unit": "mm", "tolerance_upper": None, "tolerance_lower": None, "confirmation_source": "human_confirmed"},
                    "mean_diameter": {"label": "中径", "value": 23.0, "unit": "mm", "tolerance_upper": None, "tolerance_lower": None, "confirmation_source": "human_confirmed"},
                    "free_length": {"label": "自由长度", "value": 45.0, "unit": "mm", "tolerance_upper": None, "tolerance_lower": None, "confirmation_source": "human_confirmed"},
                    "total_coils": {"label": "总圈数", "value": 10, "unit": None, "tolerance_upper": None, "tolerance_lower": None, "confirmation_source": "human_confirmed"},
                    "active_coils": {"label": "有效圈数", "value": 8, "unit": None, "tolerance_upper": None, "tolerance_lower": None, "confirmation_source": "human_confirmed"},
                    "handedness": {"label": "旋向", "value": "right", "unit": None, "tolerance_upper": None, "tolerance_lower": None, "confirmation_source": "human_confirmed"},
                    "end_grinding": {"label": "两端磨削", "value": 1, "unit": None, "tolerance_upper": None, "tolerance_lower": None, "confirmation_source": "human_confirmed"},
                    "end_coils_closed": {"label": "端圈压并", "value": 1, "unit": None, "tolerance_upper": None, "tolerance_lower": None, "confirmation_source": "human_confirmed"},
                },
                "technical_requirements": [{"type": "other", "content": "两端磨平，表面镀锌。", "confirmation_source": "human_confirmed"}],
            },
            "derived_parameters": {},
        }]},
    )

    schema_version: Literal["spring_generation_parameters/v1"] = Field(description="冻结协议版本。")
    package_type: Literal["confirmed_compression_spring_generation_input"] = Field(description="固定参数包类型。")
    generated_at: str = Field(description="参数包生成时间，ISO 8601 格式。")
    export_policy: GenerationExportPolicyV1
    source: GenerationSourceV1
    standard_context: GenerationStandardContextV1 = Field(description="可选标准化上下文；SolidWorks V1 不需要解析，空标准上下文不阻止生图。")
    generation_parameters: GenerationParametersV1
    derived_parameters: dict[str, Any] = Field(default_factory=dict, description="审图端保存的派生计算结果，SolidWorks V1 不解析。")


class GenerationTemplateView(BaseModel):
    template_code: str = Field(description="稳定的模板代码。", examples=["mock/compression-spring"])
    version: str = Field(description="不可变模板版本号。", examples=["v1"])
    drawing_type: str = Field(description="模板适用的图纸类型。", examples=["compression_spring"])
    label: str = Field(description="模板中文显示名称。")
    priority: int = Field(description="自动匹配优先级，数值越大越优先。")
    enabled: bool = Field(description="模板版本是否参与普通查询和自动匹配。")
    is_mock: bool = Field(description="是否为本地模拟模板。")
    required_fields: list[str] = Field(default_factory=list, description="模板要求必须存在的审图参数字段。")
    match_rules: dict[str, Any] = Field(default_factory=dict, description="图纸类型、范围和结构特征等匹配规则。")
    parameter_mapping: dict[str, Any] = Field(default_factory=dict, description="审图参数到 SolidWorks 尺寸或属性的映射。")
    worker_capability: str = Field(description="能够执行该模板的 Worker 能力代码。")
    created_at: str | None = Field(default=None, description="模板版本创建时间，ISO 8601 格式。")
    updated_at: str | None = Field(default=None, description="模板版本最后更新时间，ISO 8601 格式。")


class GenerationTemplateCandidate(BaseModel):
    template_code: str = Field(description="候选模板代码。")
    version: str = Field(description="候选模板版本。")
    drawing_type: str = Field(description="候选模板适用的图纸类型。")
    label: str = Field(description="候选模板显示名称。")
    priority: int = Field(description="候选模板优先级。")
    is_mock: bool = Field(description="候选模板是否为模拟模板。")
    worker_capability: str = Field(description="候选模板需要的 Worker 能力。")
    match_score: int = Field(description="模板匹配得分。")


class GenerationTemplateMatchView(BaseModel):
    status: Literal["selected", "template_not_found", "template_selection_required"] = Field(description="模板选择结果。")
    selected_template: GenerationTemplateCandidate | None = Field(default=None, description="唯一匹配或用户指定后选中的模板。")
    candidates: list[GenerationTemplateCandidate] = Field(default_factory=list, description="满足基本条件的模板候选。")
    reason: str = Field(description="选择、未匹配或需要人工选择的原因。")


class GenerationArtifactView(BaseModel):
    artifact_id: str = Field(description="生成产物 ID。")
    generation_id: str = Field(description="产物所属的生图任务 ID。")
    artifact_type: str = Field(description="产物类型，例如 png、pdf、model_manifest 或 log。")
    filename: str = Field(description="服务器保存并返回下载时使用的文件名。")
    mime_type: str | None = Field(default=None, description="文件 MIME 类型。")
    size_bytes: int = Field(description="文件大小，单位为字节。")
    sha256: str = Field(description="文件内容 SHA-256。")
    is_mock: bool = Field(description="是否由模拟 SolidWorks Worker 生成。")
    created_at: str | None = Field(default=None, description="产物上传时间，ISO 8601 格式。")
    url: str | None = Field(default=None, description="当前用户可访问的产物下载地址。")


class GenerationJobView(BaseModel):
    generation_id: str = Field(description="生图任务 ID。")
    review_id: str = Field(description="关联的审图任务 ID。")
    review_revision: int = Field(description="创建任务时固化的审图修订号。")
    parent_generation_id: str | None = Field(default=None, description="参数修改后再次生图所关联的上一版本任务 ID。")
    template_code: str = Field(description="任务固化的模板代码。")
    template_version: str = Field(description="任务固化的模板版本。")
    worker_capability: str = Field(description="领取任务所需的 Worker 能力代码。")
    parameter_schema_version: str = Field(description="生图参数包的 Schema 版本。")
    parameter_hash: str = Field(description="规范化参数包的 SHA-256。")
    parameter_package: dict[str, Any] | None = Field(default=None, description="任务创建时固化的生图参数快照。")
    readiness: GenerationReadinessView = Field(description="任务创建时固化的生图就绪状态。")
    requested_artifact_types: list[str] = Field(description="调用方希望 Worker 生成的产物类型。")
    execution_options: dict[str, Any] = Field(default_factory=dict, description="任务执行选项；模拟模式包含 mock_scenario。")
    status: Literal["queued", "claimed", "generating_3d", "generating_2d", "uploading", "completed", "failed", "cancelled"] = Field(description="生图任务状态。")
    stage: str = Field(description="当前执行阶段。")
    progress: int = Field(description="当前进度百分比。")
    error_code: str | None = Field(default=None, description="失败时的稳定机器可读错误代码。")
    error_message: str | None = Field(default=None, description="失败时供用户或开发人员查看的错误说明。")
    attempt_count: int = Field(description="任务领取或重试次数。")
    worker_id: str | None = Field(default=None, description="当前持有任务租约的 Worker ID。")
    lease_expires_at: str | None = Field(default=None, description="当前 Worker 租约过期时间。")
    is_final: bool = Field(description="是否为该审图单选定的最终版本。")
    is_stale: bool = Field(default=False, description="任务参数是否已落后于当前审图修订。")
    approved_by: dict[str, Any] | None = Field(default=None, description="确认最终版本的 ERP 用户信息。")
    approved_at: str | None = Field(default=None, description="确认最终版本的时间。")
    created_at: str | None = Field(default=None, description="任务创建时间。")
    updated_at: str | None = Field(default=None, description="任务最后更新时间。")
    started_at: str | None = Field(default=None, description="任务首次开始处理的时间。")
    completed_at: str | None = Field(default=None, description="任务完成或终止时间。")
    artifacts: list[GenerationArtifactView] = Field(default_factory=list, description="任务已上传的产物摘要。")


class GenerationReadinessResponse(BaseModel):
    review_id: str = Field(description="审图任务 ID。")
    review_revision: int | None = Field(description="当前审图修订号。")
    generation_readiness: GenerationReadinessView = Field(description="由服务端重新计算的生图就绪结果。")


class GenerationPackageResponse(GenerationReadinessResponse):
    parameter_package: GenerationParameterPackageV1 = Field(description="冻结的 spring_generation_parameters/v1 生图参数包。")


class GenerationTemplateListResponse(BaseModel):
    templates: list[GenerationTemplateView] = Field(description="当前启用的生图模板版本。")


class GenerationTemplateVersionsResponse(BaseModel):
    template_code: str = Field(description="模板代码。")
    versions: list[GenerationTemplateView] = Field(description="该模板当前启用的版本。")


class GenerationTemplateResponse(BaseModel):
    template: GenerationTemplateView = Field(description="创建或更新后的模板版本。")


class GenerationTemplateMatchResponse(BaseModel):
    review_id: str = Field(description="审图任务 ID。")
    review_revision: int | None = Field(description="当前审图修订号。")
    template_match: GenerationTemplateMatchView = Field(description="模板候选和自动选择结果。")


class GenerationJobResponse(BaseModel):
    generation_job: GenerationJobView = Field(description="生图任务详情。")


class GenerationWorkerClaimJobView(GenerationJobView):
    parameter_package: GenerationParameterPackageV1 = Field(description="领取任务时返回的完整冻结参数包。")


class GenerationWorkerClaimResponse(BaseModel):
    generation_job: GenerationWorkerClaimJobView = Field(description="Worker成功领取的任务和完整参数包。")


class GenerationJobCreateResponse(GenerationJobResponse):
    created: bool = Field(description="是否新建任务；幂等命中旧任务时为 false。")


class GenerationJobListResponse(BaseModel):
    review_id: str = Field(description="审图任务 ID。")
    generation_jobs: list[GenerationJobView] = Field(description="该审图单的全部生图版本。")


class GenerationArtifactResponse(BaseModel):
    artifact: GenerationArtifactView = Field(description="上传成功后的生成产物。")


class GenerationArtifactListResponse(BaseModel):
    generation_id: str = Field(description="生图任务 ID。")
    artifacts: list[GenerationArtifactView] = Field(description="该任务已上传的全部产物。")


class GenerationTemplateCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "template_code": "compression/general",
        "version": "v1",
        "drawing_type": "compression_spring",
        "label": "通用压缩弹簧模板",
        "priority": 100,
        "enabled": True,
        "required_fields": ["wire_diameter", "mean_diameter", "free_length", "total_coils"],
        "match_rules": {"ranges": {"wire_diameter": [0.5, 8.0]}},
        "parameter_mapping": {"wire_diameter": "D1@Sketch1"},
        "worker_capability": "solidworks_compression_v1",
    }]})

    template_code: str = Field(min_length=1, max_length=192, description="稳定的模板代码；同一模板的后续版本复用该代码。", examples=["compression/round-wire"])
    version: str = Field(min_length=1, max_length=64, description="首个不可变模板版本号。", examples=["v1"])
    drawing_type: str = Field(min_length=1, max_length=64, description="模板适用的图纸类型。", examples=["compression_spring"])
    label: str = Field(min_length=1, max_length=256, description="模板中文显示名称。")
    priority: int = Field(default=0, ge=-100000, le=100000, description="自动匹配优先级，数值越大越优先。")
    enabled: bool = Field(default=False, description="创建后是否立即启用。")
    is_mock: bool = Field(default=False, description="是否为本地模拟模板。")
    required_fields: list[str] = Field(default_factory=list, description="模板要求必须存在的审图参数字段。")
    match_rules: dict[str, Any] = Field(default_factory=dict, description="图纸类型、参数范围和结构特征等匹配规则。")
    parameter_mapping: dict[str, Any] = Field(default_factory=dict, description="审图参数到 SolidWorks 尺寸或属性的映射。")
    worker_capability: str = Field(min_length=1, max_length=192, description="能够执行该模板的 Worker 能力代码。")


class GenerationTemplateVersionCreate(BaseModel):
    version: str = Field(min_length=1, max_length=64, description="新的不可变模板版本号。", examples=["v2"])
    drawing_type: str = Field(min_length=1, max_length=64, description="模板适用的图纸类型。", examples=["compression_spring"])
    label: str = Field(min_length=1, max_length=256, description="模板中文显示名称。")
    priority: int = Field(default=0, ge=-100000, le=100000, description="自动匹配优先级，数值越大越优先。")
    enabled: bool = Field(default=False, description="创建后是否立即启用。")
    is_mock: bool = Field(default=False, description="是否为本地模拟模板。")
    required_fields: list[str] = Field(default_factory=list, description="模板要求必须存在的审图参数字段。")
    match_rules: dict[str, Any] = Field(default_factory=dict, description="图纸类型、参数范围和结构特征等匹配规则。")
    parameter_mapping: dict[str, Any] = Field(default_factory=dict, description="审图参数到 SolidWorks 尺寸或属性的映射。")
    worker_capability: str = Field(min_length=1, max_length=192, description="能够执行该模板的 Worker 能力代码。")


class GenerationTemplateStatusUpdate(BaseModel):
    enabled: bool = Field(description="是否启用该模板版本。", examples=[True])


class GenerationTemplateMatchRequest(BaseModel):
    template_code: str | None = Field(default=None, max_length=192, description="可选的指定模板代码；省略时由服务端自动匹配。", examples=["mock/compression-spring"])


class GenerationJobCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "expected_review_revision": 3,
        "idempotency_key": "review-123-r3-generation-1",
        "template_code": "mock/compression-spring",
        "parent_generation_id": None,
        "requested_artifact_types": ["pdf"],
        "mock_scenario": "success",
    }]})

    expected_review_revision: int = Field(ge=1, description="客户端当前审图修订号；不一致时返回 409。", examples=[3])
    idempotency_key: str = Field(min_length=8, max_length=128, description="调用方生成的幂等键，避免重复创建任务。", examples=["review-123-r3-generation-1"])
    template_code: str | None = Field(default=None, max_length=192, description="可选的指定模板代码；省略时自动选择唯一匹配模板。")
    parent_generation_id: str | None = Field(default=None, max_length=64, description="修改参数再次生图时关联的上一版本任务 ID。")
    requested_artifact_types: list[str] = Field(
        default_factory=lambda: ["pdf"],
        description="希望 Worker 生成的产物类型；SolidWorks V1 默认只需上传 PDF，PNG 由服务器生成。",
        json_schema_extra={"default": ["pdf"]},
    )
    mock_scenario: Literal["success", "fail_3d", "fail_2d", "timeout"] = Field(default="success", description="模拟 Worker 测试场景；真实 Worker 可忽略。")

    @field_validator("requested_artifact_types")
    @classmethod
    def validate_artifact_types(cls, values: list[str]) -> list[str]:
        allowed = {"sldprt", "slddrw", "pdf", "png", "dwg", "dxf", "step", "stl", "model_manifest", "log"}
        normalized = list(dict.fromkeys(str(item).strip().lower() for item in values if str(item).strip()))
        if not normalized or any(item not in allowed for item in normalized):
            raise ValueError("requested_artifact_types contains an unsupported value")
        return normalized


class GenerationWorkerClaim(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "worker_id": "solidworks-station-01",
        "capabilities": ["solidworks_compression_v1", "mock_solidworks_compression_v1"],
    }]})

    worker_id: str = Field(min_length=1, max_length=128, description="Worker 实例唯一标识。", examples=["solidworks-station-01"])
    capabilities: list[str] = Field(min_length=1, description="Worker 支持的模板能力代码；领取时按能力匹配。")


class GenerationWorkerHeartbeat(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "worker_id": "solidworks-station-01", "stage": "generating_3d", "progress": 35,
    }]})

    worker_id: str = Field(min_length=1, max_length=128, description="当前持有任务租约的 Worker ID。")
    stage: str | None = Field(default=None, max_length=64, description="Worker 当前执行阶段。")
    progress: int | None = Field(default=None, ge=0, le=99, description="当前进度百分比；完成前最大为 99。")


class GenerationWorkerStatus(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "worker_id": "solidworks-station-01", "status": "generating_2d", "stage": "generating_2d", "progress": 60,
    }]})

    worker_id: str = Field(min_length=1, max_length=128, description="当前持有任务租约的 Worker ID。")
    status: Literal["generating_3d", "generating_2d", "uploading"] = Field(description="下一任务状态；必须遵循固定阶段流转。")
    stage: str | None = Field(default=None, max_length=64, description="供用户查看的当前执行阶段。")
    progress: int | None = Field(default=None, ge=0, le=99, description="当前进度百分比；完成前最大为 99。")


class GenerationWorkerComplete(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"worker_id": "solidworks-station-01"}]})

    worker_id: str = Field(min_length=1, max_length=128, description="当前持有任务租约的 Worker ID。")


class GenerationWorkerFailed(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "worker_id": "solidworks-station-01",
        "error_code": "solidworks_rebuild_failed",
        "error_message": "模板重建失败：尺寸约束冲突。",
    }]})

    worker_id: str = Field(min_length=1, max_length=128, description="当前持有任务租约的 Worker ID。")
    error_code: str = Field(min_length=1, max_length=96, description="稳定的机器可读错误代码。", examples=["solidworks_rebuild_failed"])
    error_message: str = Field(min_length=1, max_length=4000, description="无敏感信息的可读错误说明。")
