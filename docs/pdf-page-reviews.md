# 多页PDF独立审图与物料编码

## 使用步骤

1. 像以前一样选择或拖入PDF，核对上传清单后点击“开始识别”。新上传的多页PDF自动按每页一张图处理，每文件最多50页。
2. 历史订单自动展开文件组。每页单独显示排队、识别中、完成或失败；完成一页即可点击打开审图，其余页继续识别。
3. 点击文件来源标题可打开只读“页面核对”清单，切换原PDF页码查看预览。失败页点“重试此页”，不重跑成功页。
4. 每页分别核对参数、载荷、技术要求并生成图纸。页面之间不共用或复制工程条件，也不会自动确认、生图或切换正在编辑的订单。
5. 需要物料编码时，在摘要“图号”右侧手工填写。默认留空；不用它推测材料、图号或名称。输入后自动保存，失败可重试。

物料编码仅去首尾空白，保留前导零、字母、连字符和内部空格，最多256字符；可随时清空。不新增确认步骤，不成为生图必填项。

## 范围与兼容

- 只支持未加密、可完整读取的1至50页PDF；超限、加密、损坏均明确报错，不静默截取。单页PDF保留原识别流程。
- 文档目录中重复的 `/PageMode` 仅在内存中处理。修复后重新严格检查，并用现有渲染器验证每页。原始上传文件保持原样。任一页校验失败时，整份文件在拆页登记前停止。原文件仍在的失败订单可以直接点“重试识别”。
- 多页拆单首期用于“一页一张独立图纸”。某页自身有多规格时，该页提示单独上传处理，其他页继续使用；不生成嵌套分组。
- 旧订单和缺少分页版本标记的旧任务不自动拆分，原重试方式保留。前端切换性能策略没有变化。
- 删除某页只删除该页；删除整个来源组需要一次确认并取消仍在处理的任务。原始PDF保留到整组清理，不因删除单页而删除。已删除页不会被任务重投或轮询自动恢复。
- 红点按每个成功页记录，打开一页不会清除其他页的未查看提示；来源组红点表示其内存在尚未查看的成功页。

## 接口与内部数据

不新增接口、数据库表、字段或迁移。复用source/variant父子关系以及父来源＋variant_id唯一约束。

新上传任务options.auto_split_pdf_pages="pdf-pages/v1"；来源审图source_kind="pdf_pages"，pdf_pages.pages保存稳定page_id、子记录ID和原始页码。子任务options.page_origin和子审图page_origin保存source_review_id、page_id、original_page及local_page=1。子PDF完整保留原页内容、页面框和旋转；本地PDF/OCR及气泡始终以局部第1页定位。

拆页准备任务只登记任务并释放worker，各页由现有持久队列依次领取、默认并发2。登记全部页面与任务在同一事务提交，稳定ID及租约防重复；源组公开状态由各页聚合，不占用worker等待子任务。GET /api/reviews/{source_id}/variants返回source_kind、creation_mode、页面状态和原页预览。POST /api/reviews/{page_id}/retry只重试该页；已保存有效Qwen响应时校验原文件与响应指纹后本地恢复，缓存失效不自动追加请求。

物料编码保存drawing_summary.material_code，包source.material_code冻结，solidworks_preview.materialCode及SW models[].materialCode读取同一快照。空值为null。新修改只影响新任务；历史冻结包和原参数重试不补写、不改动。

## 离线验证与部署

`scripts/test_pdf_pages.py` 使用临时数据库和模拟识别，覆盖六页独立拆分、单页重试、重复任务、删除取消、页数限制、加密和损坏文件。另验证目录 `/PageMode` 兼容、复用原件重试和渲染失败时整份文件停止。提供本地 `3-3.pdf` 时直接使用原件验证。

scripts/test_pdf_pages_browser.mjs覆盖处理中自动展开、逐页审图、来源清单、按页红点及重试；test_decimal_coils_drawing_name_browser.mjs增加物料编码保存、长度与切换保护。测试不调用云端识别或生产SW。

部署无需迁移，先更新worker，再更新API：

```bash
docker compose build api worker
docker compose up -d worker
docker compose up -d api
```

服务健康后Ctrl+F5刷新，核对六页独立记录及新任务JSON的materialCode。

整页预览/OCR/Qwen输入已统一限制最长边3000像素，细小证据仍从原PDF局部提取；最近3个订单可先显示缓存再核对版本。详见[性能与缓存说明](review-performance.md)。
