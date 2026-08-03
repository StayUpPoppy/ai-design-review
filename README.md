# AI Design Review for Spring Drawings

这是一个从 0 到 1 的弹簧图纸 AI 审查 MVP。当前版本重点实现：

- 图纸文件探测：区分扫描 PDF、矢量 PDF、图片、CAD 文件
- 多来源识别结果融合：OCR / 几何分析 / 可选 VLM / 人工确认
- 弹簧参数标准化：线径、外径、自由长度、圈数、旋向、载荷点等
- 弹簧语义映射：把 OCR 文本、几何证据和模板字段映射成弹簧业务字段
- 基础规则审查：缺失字段、载荷关系、公差风险、工艺能力风险
- 审图证据生成：输出尺寸字段、几何证据和人工确认所需 JSON
- ERP 放行判断：默认扫描图纸必须人工确认后才允许进入 ERP

当前 MVP 已提供纯 Python 命令行流程、百度 OCR / RapidOCR / OCR JSON 适配器、几何分析适配器、FastAPI 上传接口和前后端分离的本地审查工作台。Werk24 代码仅作为历史可选适配器保留；LangGraph / VLM 复核 / ERP 推送节点可以在当前接口边界上继续接入。

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
- 上传 PDF/图片并勾选 `调用 Qwen3.7 视觉识别`：默认主流程，直接输出弹簧类型、尺寸字段、材料、表面处理和技术要求。
- 勾选 `调用 OCR`：可选兜底，百度高精度含位置 OCR 优先，失败或未配置时自动降级到本地 RapidOCR。
- 勾选 `调用几何分析`：可选证据层，检测线段、圆/弧、箭头候选、标题栏和图纸内容区域，输出 `dimension_evidence`。

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

- 图纸预览和全屏数据对比
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

安装 OCR 运行依赖：

```cmd
python -m pip install -r requirements.txt
```

`/api/health` 会显示 `qwen_runtime`、`ocr_runtime`、`geometry_runtime` 状态。当前 Windows CPU 环境已验证 `rapidocr 3.8.4 + onnxruntime 1.20.1` 可运行。

也可以显式传入候选识别结果：

```powershell
$env:PYTHONPATH="D:\YingKe\ai-design-review\src"
& ".\.venv\Scripts\python.exe" -m ai_design_review.cli review `
  --file "C:\Users\29580\Desktop\扫描全能王 2026-06-01 15.54(2).pdf" `
  --candidates "data/samples/spring_example_candidates.json" `
  --rules "config/factory_rules.json" `
  --out "outputs/spring_example_review.json"
```

## Qwen3.7 视觉识别

当前前端默认使用 Qwen3.7-Plus 作为主识别器。PDF 会先渲染成图片，图片文件会直接上传给 Qwen；Qwen 返回严格 JSON 后转换成本项目统一 candidate / review 结构。

配置 Qwen：

```powershell
Copy-Item .env.example .env
$env:QWEN_API_KEY="你的百炼或 DashScope API Key"
$env:QWEN_MODEL="qwen3.7-plus"
$env:QWEN_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

也可以直接把真实密钥写入本地 `.env`；`scripts\run_backend.cmd` 检测到该文件后会自动加载。`.env` 已加入 `.gitignore`。

每次 Qwen 识别都会在 job 目录生成 `qwen_vision_raw.json`，保存模型原始返回、解析后的 JSON 和转换后的 candidates，便于调试。

## OCR 与几何兜底

OCR Provider 默认为 `auto`：百度高精度含位置 OCR 优先，失败时自动降级到 RapidOCR。两种 Provider 都会输出统一的 `texts` 文本块，后续尺寸、载荷点和技术要求映射保持不变。

配置百度 OCR：

```powershell
Copy-Item .env.example .env
$env:OCR_PROVIDER="auto"
$env:BAIDU_OCR_API_KEY="你的 API Key"
$env:BAIDU_OCR_SECRET_KEY="你的 Secret Key"
```

直接运行 OCR：

```powershell
& ".\.venv\Scripts\python.exe" -m ai_design_review.cli extract-ocr `
  --file "C:\path\drawing.pdf" `
  --provider auto `
  --out "outputs/ocr_provider_candidates.json"
```

可选 Provider 为 `auto`、`baidu_ocr`、`rapidocr`。旧命令 `extract-paddleocr` 暂时保留为 `auto` 的兼容别名。

把 OCR 文本块转为候选：

```powershell
$env:PYTHONPATH="D:\YingKe\ai-design-review\src"
& ".\.venv\Scripts\python.exe" -m ai_design_review.cli extract-ocr-json `
  --ocr-json "data/samples/ocr_example.json" `
  --out "outputs/ocr_candidates.json"
```

OCR 候选审查链路：

```powershell
& ".\.venv\Scripts\python.exe" -m ai_design_review.cli review `
  --file "C:\Users\29580\Desktop\扫描全能王 2026-06-01 15.54(2).pdf" `
  --candidates "outputs/ocr_candidates.json" `
  --rules "config/factory_rules.json" `
  --out "outputs/mixed_review.json"
```

API 上传时默认运行 Qwen3.7 视觉识别。OCR 和几何分析可在高级选项中手动开启，用于补充文字候选和几何证据。

每次 OCR 都会在 job 目录生成 `ocr_diagnostics.json`，记录页面、Provider、耗时、HTTP 状态、重试与降级原因，但不会记录百度密钥或访问令牌。

每次启用几何分析都会在 job 目录生成 `geometry_evidence.json`，记录低层几何证据和诊断信息。几何证据不会直接覆盖尺寸字段，只作为“为什么这个数字可能属于这个字段”的依据。

## CentOS 7 Docker 部署

完整的 PostgreSQL、审查修改留痕和 Nginx 部署步骤见 [docs/deployment_centos7.md](docs/deployment_centos7.md)。CentOS 7 宿主机无需更换，运行环境全部由 Docker 容器提供。

生产服务器使用 Docker 运行 Python 3.11，避免 CentOS 7 宿主机旧版系统库影响 ONNX Runtime：

```bash
docker build -t ai-design-review:latest .
docker run -d --name ai-design-review \
  --restart unless-stopped \
  -p 8770:8770 \
  --env-file .env \
  -v "$PWD/outputs:/app/outputs" \
  ai-design-review:latest
```

`.env` 至少配置 `OCR_PROVIDER`。使用百度 OCR 时再配置 `BAIDU_OCR_API_KEY` 和 `BAIDU_OCR_SECRET_KEY`；缺少百度凭据时 `auto` 会自动使用 RapidOCR。

## 历史可选 Werk24 接入

Werk24 不再作为默认产品方案。项目仍保留 `Werk24Engine`，仅用于历史兼容或单独对比评估；新流程默认走 OCR + 几何分析 + 可选 VLM 复核。

如果确实要单独评估 Werk24，可以配置环境变量：

## rag向量数据库

Embedding 模型 bge-large-zh-v1.5 https://www.modelscope.cn/models/AI-ModelScope/bge-large-zh-v1.5/


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

注意：Werk24 会输出通用尺寸候选，例如 `werk24_dimension_12345`。这些候选仍需要后续 OCR/几何证据/视觉模型/规则节点映射成弹簧语义字段，比如线径、外径、自由长度和载荷点。

`--confirm-upload-to-werk24` 是有意设计的安全开关。使用它表示你确认该图纸允许上传到 Werk24 外部 API。

## 生产建议

推荐逐步接入：

1. `百度 OCR / 百度 PaddleOCR-VL + RapidOCR`：中文技术要求、标题栏、尺寸数字、坐标与本地降级。
2. `OpenCV + PyMuPDF 几何分析`：线段、箭头、圆/弧、轮廓、标题栏和矢量 PDF 绘图对象，输出 `dimension_evidence`。
3. `VLM/LLM Structured JSON`：只处理低置信度字段、孤立尺寸、字段冲突和模板归属，必须引用 OCR 或几何证据。
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
  test_geometry_adapter.py 几何证据提取测试
  test_werk24_mapping.py 历史可选 Werk24 返回结构映射测试
  test_ocr_json_mapping.py OCR JSON 映射测试
  test_ocr_providers.py  OCR Provider、坐标解析与自动降级测试
  test_mixed_review.py   多来源候选融合审查测试
```
"# ai-design-review" 

```
后端启动：
scripts\run_backend.cmd
前端启动：
scripts\run_frontend.cmd
```

传入文件格式DWG PDF 图片

## ragflow公网网址
http://111.170.173.2:18080/

## docker
docker compose up -d
docker compose down
http://127.0.0.1:8088
http://127.0.0.1:8088/api/health

# 公网地址
http://111.170.173.2:8088/