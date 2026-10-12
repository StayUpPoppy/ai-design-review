# 设计校核值表格改版验收

## 最新调整：缩小字号与行距

2026-10-12，根据用户反馈“字体太大了不协调”，在保留表格结构的基础上缩小局部字体，参考周围参数行的实际字号，而非单独的生成示意图。

- 标题 20→14px，参数标签 16→13px，数值 18→14px，单位 14→11.5px，依据 13→10.5px；辅助表数值也统一为 14px。浏览器实测校核参数标签与上方参数标签均为 13px。
- 面板内边距缩至 12px 14px，区块间距 16→8px，表格单元格上下内边距 8→6px；保持右对齐、等宽数字和现有蓝白配色。
- 已检查实际参数面板上下文截图 `outputs/design-check-compact-qa/context.png`，以及 `desktop.png`、`narrow.png`、`missing-narrow.png`。同目录保留完整公式和缺项截图、`typography.json` 实测记录。519、390、320px 宽度下无横向溢出。
- `test_compression_design_table_browser.mjs` 通过，覆盖基准结果、真实编辑、材料异步加载、工作点增删、零值和缺项、两个折叠区、焦点与保存重开。本次仅修改样式和 CSS 缓存版本。
- 完成机械检测：检测器因缺少 HTML 解析模块降级为正则扫描；其列出的侧边强调线均位于本次未修改的状态提示或其他面板，保留原有语义。本次修改区域没有对应告警；不把降级结果视为完整可访问性审计。

以下为原表格布局的历史验收记录，原字号和原截图仅供追溯；最新样式以上述调整和 `design-check-compact-qa` 为准。

日期：2026-10-12。范围：现有压缩弹簧参数面板，采用用户选定的第一张参考图和批准的实施计划。

## 视觉依据与浏览器证据

- 选定参考：`C:/Users/29580/.codex/generated_images/01a123b7-c8c7-7c32-8d32-4f597436fbca/exec-43298539-0f9e-426d-861b-270354f6e290.png`，原尺寸 1161×1355。
- 参考等比例缩至 768×896；实现使用 768 CSS px、deviceScaleFactor=1，截图为 768×927。增加的高度包含计划要求的“完整公式与输入参数”折叠入口；未拉伸任何界面内容。
- 桌面实现：`outputs/design-check-table-qa/desktop.png`；窄面板：`outputs/design-check-table-qa/narrow.png`（390×1127）。
- 整体同屏比较：`outputs/design-check-table-qa/comparison.png`；主表文字和数值的局部同屏比较：`outputs/design-check-table-qa/comparison-rows.png`。
- 其他状态：`formulas.png`、`missing.png`、`missing-narrow.png` 位于同一目录。截图来自 Edge 渲染的生产前端组件，使用模拟 API 和并紧磨平基准数据。
- 主表状态：计算依据展开，完整公式收起；另行测试两个展开区和各自状态保留。

## 比较过程与结论

初次核对发现 [P2] 主表数值列偏左、辅助数值列偏右，行距比参考图松散。已调整主表和辅助表列宽、单位列间距，并把单元格上下内边距从 10px 调整为 8px。上述整体与局部比较文件均来自修正后的截图。

- **字体与排版：**沿用 Segoe UI Variable / Microsoft YaHei UI / Microsoft YaHei 字体栈。浏览器实测全部主表标签 16px、数值 18px、单位 14px，辅助数值 16px；数值采用 tabular-nums。实现使用批准计划的字号和字重，生成示意图的字体外观存在轻微差异，可接受。测量记录：`typography.json`。
- **间距与布局：**固定结果与动态工作点共用四列表格；辅助参数为三列表格。右对齐、分隔线、顺序和边距已与参考核对。520px 以下依据移至结果下一行；519、390、320px 宽度下均无横向溢出。
- **颜色：**保留 #f8fbff 背景、#dce7f5 边线、#21324a 标题、#1d4f91 数值及浅色表头；来源不新增合格或不合格判断。
- **资产质量：**参考仅包含可编辑表格文字、分隔线和原生 disclosure 标记，没有需替换的图片、插画或自定义图标；界面使用语义化 table 和原生 details。
- **文案与数据：**C=14、b=0.754、P′=2.9314、τ_b=451.2669、Q=0.00642403、工作应力 160.0034/229.0958 均一致；Pb=37.2287 N 和 Hb=6.3 mm 来源明确。完整公式、工程输入及异常原因保留在独立展开区，内部模型版本不进入工程输入展示。
- **状态与交互：**真实输入、材料异步加载及切换、载荷点增删和改名、有效零载荷、非法尺寸、保存重开、展开状态和光标保持均通过。缺项状态的长原因在窄面板完整换行。
- **可访问性：**表格具备列/行表头和 aria-label；展开区保留原生 summary、键盘行为和 focus-visible 样式。动态缺项提示使用文字表达。

修正后没有未解决的 P0/P1/P2 问题。P3：生成参考图与本机字体抗锯齿的细微差别不影响阅读和对齐，无需进一步调整。

## 验证

- `test_compression_design_table_browser.mjs`：基准、字体测量、来源、两级展开、真实编辑、材料加载、载荷点、零值/缺项、保存及响应式截图。
- `test_compression_design_checks_ui.mjs`、`test_compression_design_checks_browser.mjs`：C/b 推导、保护规则、失效输入、焦点与保存。
- `test_compression_design_values_ui.mjs`：61 个前后端一致性样例；`test_compression_design_values_browser.mjs`、`test_compression_design_values_api.py`：确认保护、联动及保存。
- `test_parameter_single_confirmation_races_ui.mjs`：确认及保存竞态。
- `test_solidworks_export_ui.mjs`：33 个前后端一致性样例；`test_solidworks_export_browser.mjs`、`test_solidworks_push_api.py`、`test_generation_package_ui.mjs`：预览、模拟推送和冻结请求。
- JavaScript 语法检查通过。当前 8088 网页及新版静态文件 HTTP 200，缓存版本正确，8770 API 健康状态为 ok。当前 web 挂载前端目录，无需重建服务。

浏览器未捕获未处理的页面错误。验收对象为模拟 API 下的生产组件，未发送实际 SW 任务。

final result: passed
