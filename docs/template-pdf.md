# 模板 PDF 出图

审图工作台的“生图参数包”中增加独立的“模板 PDF 出图”区域。用户确认参数、产品信息和成图技术要求后，点击按钮，页面先等待审图保存完成，再使用服务端已保存修订生成 PDF。SW 出图流程、参数包及任务队列继续使用原来的接口。

## 数据与输出

- 固定使用底部已中文化的 35-9 SVG，A4 竖版，保留商标、表格线和工程符号。外形及尺寸线固定，仅更新文字。
- 产品名称取 `drawing_summary.drawing_name`；物料编号取 `drawing_summary.material_code`，保留前导零及内部空格。顶部和底部编号同步填写。
- 材质使用已确认的材料牌号。客户、图纸日期为空；设计人使用已保存的 `generation_settings.username`，允许为空。版式、字体及 SW 姓名校验不阻断 PDF。
- 尺寸和载荷取共用参数契约的已确认有效数据，使用现有单位转换。刚度、节距、旋绕比等复用现有计算模块，并重新计算，不信任旧的诊断缓存。
- 技术要求与“成图技术要求预览”的服务端最终投影使用同一个函数，包括成图条目的删除状态。模板仅添加“技术要求”标题和自动换行，正文不截断、不重排编号。
- 最多两组工作载荷和一组压并载荷。使用真实的力/高度编号，保留数据顺序。角色不明确、编号无法匹配、容量超限时停止生成。
- 每个字段都赋值，空值清空，运行模板没有样图默认值。文字按实际字宽缩小，最小 2 mm；正文或单元格无法容纳时返回字段错误。
- FontTools 将动态字形转为路径，PyMuPDF 将 SVG 转为单页矢量 PDF。运行时不读取 DWG/DXF，不需要 CAD 或 SolidWorks。

## 接口

所有接口沿用现有身份认证和订单所属用户校验。

| 接口 | 内容 |
| --- | --- |
| `GET /api/reviews/{job_id}/template-pdf-readiness` | 返回 `review_id`、`review_revision`、`resources`、`readiness` 和 `technical_requirements_projection` |
| `POST /api/reviews/{job_id}/template-pdfs` | 根据已保存修订生成 PDF，成功返回 `created` 和 `template_pdf` |
| `GET /api/reviews/{job_id}/template-pdfs` | 当前订单的独立 PDF 历史 |
| `GET /api/template-pdfs/{pdf_id}/file?inline=true` | 授权预览；省略 `inline` 或使用 `false` 为下载 |

创建请求示例：

```json
{
  "expected_review_revision": 12,
  "idempotency_key": "pdf-unique-request-id"
}
```

客户端不传文件路径、SVG 或计算结果。服务端冻结对应修订的共用参数包、计算结果、最终技术要求和全部模板填充数据。

首次成功创建返回 201；同订单、同用户、同请求编号重试返回 200 和同一历史记录。重复编号用于其他修订或当前修订不一致返回 409；参数未就绪返回带 `readiness` 字段错误的 409；文字排版错误返回 422；资源、历史表或存储不可用返回 503。缺少资源时，就绪接口仍返回最终技术要求投影，历史下载继续可用。

## 私有资源包

正式资源位于项目私有目录 `.local-assets/template-pdf/35-9/`，不依赖临时 DWG 转换目录：

```text
35-9/
  template.svg
  fields.json
  fonts/
    primary.ttf
    fallback.ttf
```

资源包只含这四个运行文件和说明，不含 DWG、DXF、转换工具或预览。当前资源包放在已忽略的 `output/templates/35-9-13/template-pdf-runtime.zip`。解压后将 `35-9` 放到资源根目录，保持上述结构。

本地默认从项目的 `.local-assets/template-pdf/35-9` 读取；其他路径设置 `PDF_TEMPLATE_ROOT`，值必须指向包含 `template.svg` 和 `fields.json` 的目录。资源版本为四个文件内容的 SHA-256，写入每条历史记录。

```powershell
$env:PDF_TEMPLATE_ROOT = 'D:\private-resources\template-pdf\35-9'
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

资源在 API 加载时检查，每次查询出图状态也会检查；文件改变后自动更新缓存。缺少或损坏资源只禁用新 PDF 生成。已生成的 PDF 位于订单输出目录，与字体和模板的后续变化无关。

`.gitignore` 忽略私有资源和原转换/预览目录；`.dockerignore` 不将私有资源烘焙到镜像。业务代码、测试、数据库迁移和本说明正常纳入版本管理。

## 数据库与文件

Alembic 新增迁移 `20261122_01`，在既有迁移 `20261108_01` 后创建 `template_pdf_drawings`。每条记录保存用户、订单、审图修订、模板版本、冻结快照、最终正文、渲染数据、文件位置及生成时间。它与 SW 任务表分开。

先在目标环境备份数据库，再按现有部署流程升级迁移：

```sh
docker compose run --rm api alembic upgrade head
```

每次生成使用独立目录 `outputs/api_runs/<job_id>/template_pdf/<pdf_id>/`，保存填充 SVG 和 PDF。实际根目录沿用现有 API 输出配置。文件与历史记录均成功后才向前端提供下载；失败清理本次目录。订单删除时，历史记录级联删除，文件随订单目录清理。

## Docker 启用

将私有包单独复制到服务器，例如 `/srv/ai-review/template-pdf/35-9/`，在部署环境文件中设置：

```dotenv
PDF_TEMPLATE_RESOURCE_DIR=/srv/ai-review/template-pdf
```

Compose 为 API 设置 `PDF_TEMPLATE_ROOT=/app/template-pdf/35-9`，只读挂载 `${PDF_TEMPLATE_RESOURCE_DIR}:/app/template-pdf:ro`。Worker 不需要此资源。执行迁移、重建并启动 API 后，检查已保存订单的就绪接口和页面，使用测试订单生成、预览及下载一张 PDF。确认历史、用户隔离和订单删除后再开放使用。

本次本地验收使用临时 SQLite 数据库及测试订单；没有迁移实际业务数据库，也没有部署服务器。移除私有资源挂载可停用新 PDF 出图，已生成的历史文件继续保留；不要删除历史表或订单输出卷。

## 本地验证

```powershell
.venv\Scripts\python.exe scripts/test_template_pdf.py
node scripts/test_template_pdf_browser.mjs
.venv\Scripts\python.exe scripts/test_generation_api.py
.venv\Scripts\python.exe scripts/test_generation_settings.py
.venv\Scripts\python.exe scripts/test_solidworks_export.py
node scripts/test_generation_settings_browser.mjs
node scripts/test_technical_requirement_preview_browser.mjs
```

新增集成测试需要上述私有运行资源。浏览器脚本沿用项目现有的 Playwright/Edge 测试方式，支持本机已有运行时。样张和界面截图写到已忽略的 `outputs/template-pdf-qa/`，仅使用合成测试数据。

本次本地验收通过：新增 PDF 后端集成与浏览器流程、共用参数就绪检查、SW 设置与生图接口回归、238 个 SW 导出用例及 32 组编号样例、成图正文预览浏览器回归、30 个成图条目删除用例。新增迁移在临时 SQLite 中实际执行通过，未连接业务数据库。浏览器检查包含保存失败、空姓名、预览/下载、重复点击、切换订单、缺失资源、未刷新审图修订及桌面/窄屏布局；预览关闭按钮的修正经独立复核确认。PDF 样张验证为单页 A4、无栅格图片，并逐页渲染检查中文、特殊字符、实际载荷编号及带符号公差。
