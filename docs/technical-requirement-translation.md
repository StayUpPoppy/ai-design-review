# 外文技术要求中文化

技术要求只保留一个编辑入口：现有侧栏的中文文本框。机器翻译后重新待确认；其他参数不受影响。原文可展开核对，不作为另一份可编辑数据源。

## 后端与配置

- Qwen 视觉识别直接给出中文 `content`、`original_content`、`source_language` 和证据。
- 识别保存前检查译文；必要时批量调用独立文本翻译器。不调用 RAG/标准化。
- 复用 `QWEN_API_KEY`（或 `DASHSCOPE_API_KEY`）、`QWEN_BASE_URL`。模型优先级为 `TECHNICAL_REQUIREMENT_TRANSLATION_MODEL` → `STANDARDIZATION_CHAT_MODEL` → `QWEN_MODEL`。
- `TECHNICAL_REQUIREMENT_TRANSLATION_TIMEOUT_SECONDS` 默认 30 秒；临时网络错误、429 和服务端错误最多重试一次。配置错误、工程信息不一致和无效响应不反复调用。
- `POST /api/reviews/{job_id}/technical-requirements/translate` 校验订单归属、稳定 ID 和已保存文本/类型快照；只计算，不保存，不代替人工确认。
- 可选 `mode` 默认为 `translate`；`revalidate` 只读取和核验已保存识别记录，不调用模型。响应保留旧字段，增加可选 `recovery_mode`（automatic/preview/unavailable）、`translation_candidates` 和 `recovery_reason`。preview 的候选不直接写入 `content`。
- 中文化与工程信息一致性分开判断。已有可用中文且无真实外文说明时直接显示；数值、公差符号、单位、公式变量、材料/工艺代号及标准编号不同只产生警告，不退回外文、不再次调用模型，也不自动纠正译文或结构化参数。小数逗号等价换点，ГОСТ/GOST 仍可等价；Б/B、СТ ЦКБА/STsKBA 不直接等价，其差异必须保留。
- 空译文、缺项/重复/未知 ID、无法还原的占位符及真实外文说明仍失败。明确的整数条目编号在工程比较与占位符保护前剥离；编号仍保留在元数据中，`12.5 mm` 等普通尺寸不剥离。
- 新增可选 `translation_warnings`（类别、说明、原文/译文对照）和 `translation_warning_snapshot`（当前正文、类型）。警告译文为 `translated`，编辑后旧快照不再适用。状态枚举、接口模式和数据库表不变。
- 元数据保存在现有审图 JSON；不改变 `raw_content` 的术语归一化语义。识别初始翻译审计与审图创建在同一事务内写入，修订号仍为 1。

## 历史数据与前端

打开历史订单会自动检查当前外文文本，包括人工修改或已确认内容。没有原图原文时，以实际送译的当前文本作为原文，不伪造图纸记录。成功/失败均撤销该项旧确认。

新增或修改的外文只在草稿保存成功后送译。正在输入、保存失败或标准化运行时不启动翻译；一批结果通过现有串行保存保存一次。条目被编辑、删除或切换订单后，旧响应不得改写输入。409 冲突复用服务器/本地值选择，技术要求按稳定 ID 合并，保留无关服务器修改。

同一内容翻译失败后，刷新不会自动重试；用户可以点击“翻译失败·重试”，或修改内容后再译。保存失败保留本地译文，点击“重试保存”只重试保存，不重新调用模型。人工填写中文后仍按原流程确认。

### 中文工程缩写与历史误判恢复

`2D/3D`（含小写）可紧挨中文，不需要翻译；外文说明中的工程缩写不使整句话被放行，`3Dprinting` 等单词也不按缩写或材料牌号剔除。翻译仍保护 `2D/3D` 标识，改变或删除标识产生工程差异提示，由用户确认。

历史条目仅在失败原因是“译文仍包含外语说明”、原文与当前文字相同、失败快照与当前文字/类型一致且新规则确认无需翻译时自动重新检查。复用现有翻译接口返回 `not_required`，不调用 Qwen；清除失败状态后仍待人工确认，保留原文、来源及原失败记录。恢复产生 `technical_requirement_translation_recovered` 审计，来源为 `translation_validation`，不伪装成机器翻译或人工采纳。

不能仅因当前文字看起来是中文而解除工程信息不一致、缺项或历史依据不足的失败；已有译文证据的安全恢复另按下节校验。恢复请求失败时保留原误判证据，显示重试入口，同一页面不循环检查；最终保存失败保留本地结果，重试只保存。未确认的恢复条目不进入生图参数包，确认并保存后按原流程输出到 SW。

### 工程代号与已有中文译文恢复

`F₃/F3` 的数字下标表示同一变量；`F3/F2` 不是等价变量。`Ц15.hr`、`Б-1-1,5` 作为完整工艺/材料代号识别，数字小数逗号可等价比较为小数点。不同变量、牌号、标准或公式仍准确提示差异。`СТ ЦКБА` 和 `ST TsKBA` 不自动等价，文本翻译应保留原标准标识；包含这些工程代号的中文不误判为外文说明。前后端分类复用同一组样例测试，真实外文不因含有工程代号而放行。

文本调用先保护不重叠的工程信息跨度（完整标准、公式、代号优先），用 `⟦ENG_0000⟧` 等不透明占位符送译。提示词要求各返回一次；已知标识还原，缺失或重复记录工程差异，未知或无法还原的残留标识属于无效响应，不能进入正文输出。源文中的类似占位符也先保护，绝不作为程序指令。不会把占位符或未采纳候选作为 SW 的数据源。

打开订单时同一失败正文只执行一次本地证据核验，先读取 `qwen_vision_raw.json`，再读取未融合 `candidates.json`；记录缺失时可核对已保存的 `recognized_content`。原图序号和类型不作为唯一匹配键。只有能唯一对应原文、正文/类型与失败快照一致、未通过人工或 AI 对话改写的可用中文才自动恢复，工程差异随中文作为警告保留；第 11、13 条无需重新上传即可恢复已有候选。人工改写、匹配不确定时展示默认收起的候选对照，用户点击“采用候选译文”后仍待确认。不存在可用中文候选时保留失败，不猜测、不恢复删除项、不自动重新调用 Qwen；按钮“重新翻译”才触发模型。

恢复记录 `technical_requirement_translation_recovered` 审计，source 为 `translation_validation`，metadata 区分 automatic/adopted；不会标为人工确认或新的机器翻译。请求返回时及采用候选前均检查订单、条目、正文、类型和编辑计数，输入改回原文也不会接受已过期响应。保存失败保留本地文本，仅重试保存。

失败保留可选 `translation_error_code` 和 `translation_error_details`：request_failed、model_uncertain、invalid_response、foreign_prose_remaining；历史 engineering_mismatch 继续兼容读取，新结果使用警告。错误就近解释原因和未输出后果；剩余外文和模型说明默认收起，原文及候选使用已有原生 details/summary。

中文卡片无差异显示“已翻译，请核对后确认”；有差异显示“译文与原文存在工程信息差异，请核对后确认”，提供默认收起且支持键盘的“查看差异”。工程差异不增加二次确认，允许单项或“全部确认可确认项”采纳，已完成翻译的表面处理规则保持一致。空内容、重复项和正在翻译的条目仍不能确认。确认审计保存稳定 ID、确认文本、原文和当时的差异；批量确认保存 `translation_warning_acknowledgements`。

## 输出与生图

服务端参数包及两个前端导出入口排除外文说明和同一输入的失败条目，即使历史确认标记为已确认。生图就绪检查将此类遗漏列为警告而非建模阻断；页面和生图确认弹窗明确提示“以下技术要求未写入本次图纸”，并可定位。

已确认且成功保存的中文（包括带差异警告的中文）保留编号、类型前缀及粗糙度优先规则，不再包含独立 `技术要求\n` 标题。未确认/保存失败结果不进入实际 SW 任务；警告本身不阻止导出，真实外文不能仅凭 `translated` 状态绕过检查。没有改变建模字段、包版本、SW 回调或已冻结旧任务。

## 界面与验证

沿用白底蓝色控件的工程工作台，不重设计页面。翻译状态就近显示在原输入框下方，原文采用原生 `details/summary`，错误和按钮可在窄侧栏换行；确认和保存重试含义分开。桌面与手机均用真实前端、模拟接口检查自动翻译、确认、重试及键盘展开原文，QA 图在 Git 忽略的 `outputs/translation-ui-qa/`。不新增发布用位图。

手工 impeccable 扫描因解析器依赖缺失退化为正则扫描，已有风险/最终版本侧边提示等告警属于既有界面，未在本功能中重设计；实际布局、焦点和状态通过浏览器检查。未调用真实付费 Qwen，翻译语义质量仍需部署后用真实外文订单人工核对。

主要测试：`test_technical_translation.py`、`test_technical_translation_api.py`、`test_technical_translation_ui.mjs`、`test_technical_translation_browser.mjs`。同时回归参数单次确认、技术要求/AI 方案、表面处理、粗糙度、参数包及 OpenAPI。

工程标识与历史安全恢复新增 `test_technical_translation_revalidation.py`、`test_technical_translation_revalidation_ui.mjs`。浏览器用模拟响应验证历史恢复、候选采用、待确认/输出约束及窄屏布局；不发起付费 Qwen 请求或真实 SW 任务。

警告策略新增 `test_technical_translation_warnings.py`、`test_technical_translation_warnings_ui.mjs`；使用真实订单已保存的第 11、13 条原文和中文候选样例，不在生产代码硬编码译文。覆盖序号与尺寸、工程差异、占位符异常、历史恢复、编辑竞态、保存失败、单项/批量确认审计、两个导出入口及冻结 SW 输出。浏览器的 desktop/mobile-warnings.png 核对原生差异展开及窄屏换行。

浏览器测试使用 Playwright；可设置 `CODEX_NODE_MODULES` 指向依赖目录，设置 `TRANSLATION_TEST_BROWSER_CHANNEL=msedge` 使用已安装的 Edge。

## 部署

拉取代码后重建并重新创建 `api`、`worker`，无需数据库迁移或重建 PostgreSQL。当前 Compose 的前端目录挂载模式下更新前端文件并强制刷新即可；其他部署方式按既有静态文件发布流程更新。不要因为翻译失败让 SolidWorks 重传图纸。

```sh
docker compose build api worker
docker compose up -d --force-recreate api worker
```
