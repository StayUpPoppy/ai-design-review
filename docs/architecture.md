# 弹簧图纸 AI 审查架构

## MVP 流程

```text
图纸上传
→ 文件探测
→ PDF/图片预处理
→ 多引擎识别
→ 候选结果融合
→ 弹簧参数标准化
→ 规则审查
→ 气泡数据生成
→ 人工确认
→ ERP 放行判断
```

## 推荐 LangGraph 节点

当前 `DrawingReviewWorkflow` 是纯 Python 同步实现，节点边界按未来 LangGraph 迁移设计：

| 节点 | 当前对应模块 | 说明 |
|---|---|---|
| `classify_file` | `preprocessing.probe_file` | 判断 PDF/图片/CAD，以及是否扫描件 |
| `render_pages` | `preprocessing.render_pdf_with_pdftoppm` | PDF 渲染为图片 |
| `cad_extract` | `engines.cad_adapter` | DXF/DWG 尺寸对象解析 |
| `werk24_extract` | `engines.werk24_adapter` | Werk24 尺寸、公差、气泡候选 |
| `ocr_extract` | `engines.ocr_adapter` | 中文技术要求和标题栏识别 |
| `vision_extract` | `engines.vision_adapter` | 视觉模型做弹簧语义映射 |
| `spring_semantic_map` | `semantic.apply_spring_semantic_mapping` | 将通用尺寸候选映射成弹簧业务字段 |
| `fuse_candidates` | `fusion.fuse_candidates` | 多来源融合、冲突识别 |
| `rule_check` | `rules.run_rule_checks` | 工艺、标准、ERP 放行规则 |
| `generate_balloons` | `balloons.generate_balloons` | 生成前端气泡 JSON |
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

如果 Werk24 返回气泡坐标，应尽量填入 `position`。如果 OCR 只有文本块坐标，也可以填入文本块区域。

## Werk24 适配器

`Werk24Engine` 当前请求：

- `AskMetaData`
- `AskFeatures`
- `AskBalloons`

输出：

- `outputs/werk24_candidates.json`：统一候选字段和 Werk24 原始返回
- `outputs/werk24_review.json`：候选字段进入审查流程后的结果

必需环境变量：

```text
W24TECHREAD_AUTH_TOKEN
W24TECHREAD_AUTH_REGION
```

Werk24 尺寸会先以 `werk24_dimension_{reference_id}` 形式进入候选池。下一层语义映射负责判断它是 `wire_diameter`、`outer_diameter`、`free_length` 还是载荷相关高度。

当前语义映射已支持：

- `SUS 304 (JIS)` → `SUS304`
- 带 `0/-0.02` 公差的大尺寸 → `outer_diameter`
- 剩余最大线性尺寸 → `free_length`
- 技术要求 OCR 中的 `1.5±0.05` → `wire_diameter`
- 技术要求 OCR 中的 `H1/F1`、`H2/F2` → `load_points`
- 技术要求 OCR 中的 `300°C/20min`、`720h`、`30512-2014` → 对应技术要求

中文 OCR 失败时，例如 `右旋` 被识别成乱码，系统会保留 `handedness` 为缺失并要求人工确认。

## OCR JSON 适配器

当前本地 PaddleOCR 运行条件不完整：安装了 `paddleocr`，但缺少 `paddle` 推理引擎，且本地缓存是旧版 `pdmodel/pdiparams`，不能直接供 PaddleOCR 3.x 新管线使用。

因此先提供 `OcrJsonEngine`，用统一文本块格式接入任意 OCR 服务：

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

为了避免误传生产图纸，CLI 的 Werk24 命令必须显式带上：

```text
--confirm-upload-to-werk24
```

这表示操作者确认当前图纸允许上传到 Werk24 外部 API。

## ERP 放行原则

当前默认策略：

- 扫描图纸必须人工确认。
- 存在 `fail`、`missing`、`need_review` 时不允许进入 ERP。
- 单来源识别的关键尺寸默认需要人工确认，除非来源是人工确认或 CAD 原始对象。
