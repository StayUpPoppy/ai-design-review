# AI Design Review for Spring Drawings

这是一个从 0 到 1 的弹簧图纸 AI 审查 MVP。当前版本重点实现：

- 图纸文件探测：区分扫描 PDF、矢量 PDF、图片、CAD 文件
- 多来源识别结果融合：CAD / Werk24 / OCR / 视觉模型 / 人工确认
- 弹簧参数标准化：线径、外径、自由长度、圈数、旋向、载荷点等
- 弹簧语义映射：把 Werk24 通用尺寸候选映射成弹簧业务字段
- 基础规则审查：缺失字段、载荷关系、公差风险、工艺能力风险
- 气泡图数据生成：输出前端可叠加的 bubble JSON
- ERP 放行判断：默认扫描图纸必须人工确认后才允许进入 ERP

当前 MVP 已提供纯 Python 命令行流程、Werk24 适配器、PaddleOCR/OCR JSON 适配器、FastAPI 上传接口和前后端分离的本地审查工作台。LangGraph / OpenAI Vision / ERP 推送节点可以在当前接口边界上继续接入。

## 前后端分离运行

当前运行方式已经拆成两个独立服务：

```text
frontend/                 独立浏览器工作台，默认请求 http://127.0.0.1:8770
src/ai_design_review/      FastAPI 后端和识别/审查流水线
```

在第一个 CMD 终端启动后端：

```cmd
scripts\run_backend.cmd
```

在第二个 CMD 终端启动前端：

```cmd
scripts\run_frontend.cmd
```

浏览器打开：

```text
http://127.0.0.1:5173/index.html
```

页面里的 `后端地址` 默认是 `http://127.0.0.1:8770`。如果你改了后端端口，只需要在页面输入框里改地址并点击 `检查后端`。

后端健康检查地址：

```text
http://127.0.0.1:8770/api/health
```

页面支持：

- 点击 `加载样例`：从后端加载 `outputs/mixed_review.json` 和样例图。
- 上传 PDF/图片并勾选 `调用 PaddleOCR`：本地 OCR 抽取扫描图文字，不上传外部服务。
- 勾选 `调用 Werk24` + `确认上传到 Werk24`：把当前图纸上传到 Werk24 API 抽取尺寸/气泡候选。
- 同时勾选 `调用 PaddleOCR`、`调用 Werk24`、`确认上传到 Werk24`：运行混合识别方案。

## 快速运行

```powershell
$env:PYTHONPATH="D:\YingKe\ai-design-review\src"
& ".\.venv\Scripts\python.exe" -m ai_design_review.cli sample
```

输出文件：

```text
outputs/spring_example_review.json
```

查看气泡图请使用上面的前后端分离工作台：先启动后端，再启动前端，打开 `http://127.0.0.1:5173/index.html`。

工作台支持：

- 图纸气泡展示
- 关键弹簧参数编辑
- 技术要求确认
- 扫描图纸人工确认
- ERP 放行预览
- 导出人工确认版 JSON

## 后端 API

启动 FastAPI 服务：

```cmd
scripts\run_backend.cmd
```

如果 `/api/health` 中 `paddleocr_runtime.status` 显示 `missing_paddlepaddle`，先安装 Paddle 推理引擎并重启服务：

```cmd
python -m pip install "paddlepaddle>=3.2,<3.3"
```

当前 Windows CPU 环境已验证 `paddlepaddle 3.2.2 + PaddleOCR PP-OCRv4 mobile` 可运行；`paddlepaddle 3.3.1 + PP-OCRv6` 在本机触发过 oneDNN/PIR 推理错误。

也可以显式传入候选识别结果：

```powershell
$env:PYTHONPATH="D:\YingKe\ai-design-review\src"
& ".\.venv\Scripts\python.exe" -m ai_design_review.cli review `
  --file "C:\Users\29580\Desktop\扫描全能王 2026-06-01 15.54(2).pdf" `
  --candidates "data/samples/spring_example_candidates.json" `
  --rules "config/factory_rules.json" `
  --out "outputs/spring_example_review.json"
```

## OCR 与混合审查

当前本地 `.venv` 已接入 PaddleOCR；也保留了 OCR JSON 适配器，后续可接 Azure OCR、百度 OCR 或阿里 OCR，只要输出 `texts` 文本块即可。

把 OCR 文本块转为候选：

```powershell
$env:PYTHONPATH="D:\YingKe\ai-design-review\src"
& ".\.venv\Scripts\python.exe" -m ai_design_review.cli extract-ocr-json `
  --ocr-json "data/samples/ocr_example.json" `
  --out "outputs/ocr_candidates.json"
```

Werk24 + OCR 混合审查：

```powershell
& ".\.venv\Scripts\python.exe" -m ai_design_review.cli review `
  --file "C:\Users\29580\Desktop\扫描全能王 2026-06-01 15.54(2).pdf" `
  --candidates "outputs/werk24_candidates.json" "outputs/ocr_candidates.json" `
  --rules "config/factory_rules.json" `
  --out "outputs/mixed_review.json"
```

这条链路会让 Werk24 负责尺寸/气泡，OCR 负责中文字段，例如 `右旋`、图号、版本、标题栏和表面要求。

## Werk24 接入

项目已实现 `Werk24Engine`，会调用 Werk24 的 `AskMetaData`、`AskFeatures`、`AskBalloons`，并映射为本项目统一 candidate JSON。

先配置环境变量：

```powershell
$env:W24TECHREAD_AUTH_TOKEN="你的 Werk24 token"
$env:W24TECHREAD_AUTH_REGION="eu"
$env:PYTHONPATH="D:\YingKe\ai-design-review\src"
```

只抽取 Werk24 候选结果：

```powershell
& ".\.venv\Scripts\python.exe" -m ai_design_review.cli extract-werk24 `
  --file "C:\Users\29580\Desktop\扫描全能王 2026-06-01 15.54(2).pdf" `
  --out "outputs/werk24_candidates.json" `
  --confirm-upload-to-werk24
```

抽取后直接进入审查流程：

```powershell
& ".\.venv\Scripts\python.exe" -m ai_design_review.cli review-werk24 `
  --file "C:\Users\29580\Desktop\扫描全能王 2026-06-01 15.54(2).pdf" `
  --candidates-out "outputs/werk24_candidates.json" `
  --out "outputs/werk24_review.json" `
  --confirm-upload-to-werk24
```

注意：Werk24 会输出通用尺寸候选，例如 `werk24_dimension_12345`。这些候选还需要后续的 OCR/视觉模型/规则节点映射成弹簧语义字段，比如线径、外径、自由长度和载荷点。

`--confirm-upload-to-werk24` 是有意设计的安全开关。使用它表示你确认该图纸允许上传到 Werk24 外部 API。

## 生产建议

推荐逐步接入：

1. `Werk24`：尺寸、公差、GD&T、气泡候选坐标。
2. `PaddleOCR / Azure Document Intelligence`：中文技术要求、标题栏。
3. `OpenAI Vision + Structured Outputs`：弹簧语义映射和冲突解释。
4. `LangGraph`：把识别、融合、规则审查、人工确认、ERP 推送编排成可恢复流程。
5. `Postgres + MinIO/S3`：保存结构化参数、审查记录、原图和气泡图。

## 目录说明

```text
src/ai_design_review/
  cli.py                 命令行入口
  workflow.py            审图主流程
  preprocessing.py       文件探测和 PDF 渲染辅助
  fusion.py              多来源候选结果融合
  rules.py               弹簧规则审查
  balloons.py            气泡数据生成
  io_utils.py            JSON 读写
  engines/               外部识别引擎适配器接口

config/
  factory_rules.json     工厂工艺能力和 ERP 放行规则

data/samples/
  spring_example_candidates.json  当前样图的候选识别结果

prompts/
  spring_review_agent.md AI 审查 Agent 主提示词

scripts/
  smoke_test.py          本地冒烟测试
  test_werk24_mapping.py Werk24 返回结构映射测试
  test_ocr_json_mapping.py OCR JSON 映射测试
  test_mixed_review.py   Werk24 + OCR 混合审查测试
```
"# ai-design-review" 

```
后端启动：
scripts\run_backend.cmd
前端启动：
scripts\run_frontend.cmd
```

传入文件格式DWG PDF 图片

