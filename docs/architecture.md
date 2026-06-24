# 弹簧图纸 AI 审查架构

## MVP 流程

```text
图纸上传
→ 文件探测
→ PDF/图片预处理
→ Qwen3.7 视觉主识别
→ 可选 OCR/几何证据提取
→ 候选结果融合
→ 弹簧参数标准化
→ 规则审查
→ 审图证据/确认数据生成
→ 人工确认
→ ERP 放行判断
```

## 前后端边界

当前项目采用前后端分离的本地 MVP 结构：

```text
frontend/
  index.html
  app.js
  styles.css

src/ai_design_review/
  api.py
  workflow.py
  engines/
```

前端独立运行在 `http://127.0.0.1:5173`，只通过 HTTP 调用后端 API。后端独立运行在 `http://127.0.0.1:8770`，负责上传文件、预览图生成、Qwen3.7 视觉识别、可选百度 OCR / RapidOCR 调用、几何分析、规则审查和审查结果存储。

后端需要保留 `/outputs`、`/tmp_pdf_pages`、`/artifacts` 这类静态结果目录，用于前端展示样例图和单次审查产生的预览图；这些目录不是前端应用代码托管入口。

## 推荐 LangGraph 节点

当前 `DrawingReviewWorkflow` 是纯 Python 同步实现，节点边界按未来 LangGraph 迁移设计：

| 节点 | 当前对应模块 | 说明 |
|---|---|---|
| `classify_file` | `preprocessing.probe_file` | 判断 PDF/图片/CAD，以及是否扫描件 |
| `render_pages` | `preprocessing.render_pdf_with_pdftoppm` | PDF 渲染为图片 |
| `cad_extract` | `engines.cad_adapter` | DXF/DWG 尺寸对象解析 |
| `qwen_vision_extract` | `engines.qwen_vision_adapter` | Qwen3.7-Plus 直接识别弹簧类型、尺寸、材料、表面处理和技术要求 |
| `ocr_extract` | `engines.ocr_providers` | 可选兜底：百度 OCR 优先、RapidOCR 本地降级，并统一输出文本块 |
| `geometry_extract` | `engines.geometry_adapter` | 可选证据层：线段、箭头、圆/弧、轮廓、标题栏、矢量 PDF 绘图对象 |
| `vision_review` | `engines.vision_adapter` | 后续阶段：VLM/LLM 复核低置信度字段、孤立尺寸和字段冲突 |
| `spring_semantic_map` | `semantic.apply_spring_semantic_mapping` | 将通用尺寸候选映射成弹簧业务字段 |
| `fuse_candidates` | `fusion.fuse_candidates` | 多来源融合、冲突识别 |
| `rule_check` | `rules.run_rule_checks` | 工艺、标准、ERP 放行规则 |
| `generate_balloons` | `balloons.generate_balloons` | 生成历史兼容的定位 JSON |
| `human_review` | 待实现 | 工程师确认和修正 |
| `erp_push` | 待实现 | 推送 ERP 工单/图纸/审查报告 |

## 多来源候选格式

每个识别工具最终都应该输出统一候选：

```json
{
  "field": "wire_diameter",
  "value": 1.5,
  "unit": "mm",
  "tolerance_upper": 0.05,
  "tolerance_lower": -0.05,
  "source": "ocr",
  "evidence": "线径Φ1.5±0.05",
  "confidence": 0.94,
  "page": 1,
  "position": {
    "x": 0.1,
    "y": 0.2,
    "width": 0.05,
    "height": 0.02,
    "coordinate_type": "normalized"
  },
  "suggested_region": "技术要求第1行"
}
```

Qwen 主识别结果可以没有稳定坐标，但必须给出 `evidence` 和 `confidence`。OCR 或几何分析如有坐标，应尽量填入 `position`。几何证据不直接覆盖尺寸字段，而是作为字段归属、低置信度复核和人工确认的依据。

## Qwen3.7 视觉识别适配器

`QwenVisionEngine` 是当前 MVP 默认主识别器：

- 默认模型：`qwen3.7-plus`。
- 默认接口：OpenAI 兼容 `chat/completions`。
- PDF 先渲染成高清图片，图片直接作为 data URL 输入模型。
- 模型必须返回严格 JSON，再转换为统一 candidates。
- 原始返回保存为 `qwen_vision_raw.json`，用于人工排查。

## 几何分析适配器

`GeometryEngine` 当前默认输出：

- `dimension_evidence`：低层几何证据列表。
- `candidates`：以 `feature_type=dimension_evidence` 进入统一候选池。
- `diagnostics`：页面、运行时、降级原因和处理统计。

图片和扫描 PDF 的处理路径：

- PIL/NumPy 基础阈值：检测图纸内容区域和标题栏候选。
- OpenCV 可用时：检测线段、轮廓、箭头候选、圆/弧候选。
- OpenCV 不可用时：退化为水平/垂直暗线段扫描。

矢量 PDF 的处理路径：

- PyMuPDF 可用时读取 `page.get_drawings()` 和文本块坐标。
- PyMuPDF 不可用时跳过矢量几何，继续使用渲染图片做几何分析。

## 历史可选 Werk24 适配器

Werk24 不再作为默认产品方案。`Werk24Engine` 代码保留用于历史兼容和对比评估；CLI 命令仍要求显式 `--confirm-upload-to-werk24`，避免误传生产图纸。

Werk24 尺寸会先以 `werk24_dimension_{reference_id}` 形式进入候选池。下一层语义映射负责结合 OCR、几何证据和规则判断它是 `wire_diameter`、`outer_diameter`、`free_length` 还是载荷相关高度。

## VLM/LLM 复核约束

VLM/LLM 不作为 OCR 或几何分析的替代品，只处理低置信度字段、孤立尺寸、字段冲突和模板归属。模型输出必须满足：

- 不凭空补尺寸。
- 必须引用 OCR 文本块或 `dimension_evidence`。
- 只返回结构化 JSON。
- 低置信度结果必须标记 `need_human_review=true`。

当前语义映射已支持：

- `SUS 304 (JIS)` → `SUS304`
- 带 `0/-0.02` 公差的大尺寸 → `outer_diameter`
- 剩余最大线性尺寸 → `free_length`
- 技术要求 OCR 中的 `1.5±0.05` → `wire_diameter`
- 技术要求 OCR 中的 `H1/F1`、`H2/F2` → `load_points`
- 技术要求 OCR 中的 `300°C/20min`、`720h`、`30512-2014` → 对应技术要求

中文 OCR 失败时，例如 `右旋` 被识别成乱码，系统会保留 `handedness` 为缺失并要求人工确认。

## OCR Provider 与 OCR JSON 适配器

当前 OCR 路由支持：

- `auto`：百度高精度含位置 OCR 优先，异常时降级到 RapidOCR。
- `baidu_ocr`：仅调用百度云 OCR。
- `rapidocr`：仅使用本地 ONNX Runtime，不上传图纸。

PDF 会先按页渲染，图片会统一归一化为 PNG。所有 Provider 输出 `text`、`confidence`、`page`、`position`、`source`，再复用 `ocr_adapter` 中的弹簧字段映射。

同时保留 `OcrJsonEngine`，用统一文本块格式接入其他 OCR 服务：

```json
{
  "texts": [
    {
      "text": "2.总圈数:4，旋向：右旋",
      "confidence": 0.96,
      "page": 1,
      "source": "azure_ocr",
      "position": {
        "x": 0.1,
        "y": 0.7,
        "width": 0.3,
        "height": 0.05,
        "coordinate_type": "normalized"
      }
    }
  ]
}
```

`OcrJsonEngine` 已支持抽取：

- 图纸名称
- 图号
- 版本
- 材料
- 线径
- 总圈数
- 旋向
- 热处理
- 表面要求
- 盐雾
- 环保标准

混合审查时，CLI 的 `review --candidates` 支持多个候选文件，按顺序合并。

历史可选 Werk24 命令不在默认产品路径中。为了避免误传生产图纸，相关 CLI 命令必须显式带上：

```text
--confirm-upload-to-werk24
```

这表示操作者确认当前图纸允许上传到 Werk24 外部 API。

## ERP 放行原则

当前默认策略：

- 扫描图纸必须人工确认。
- 存在 `fail`、`missing`、`need_review` 时不允许进入 ERP。
- 单来源识别的关键尺寸默认需要人工确认，除非来源是人工确认或 CAD 原始对象。
