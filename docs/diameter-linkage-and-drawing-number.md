# 三径联动与可编辑图号

## 操作

圆柱、圆截面压缩弹簧首次人工编辑外径、内径或中径后，以最后修改项为主控、固定当前线径，立即重算另外两项：外径＝中径＋线径，内径＝中径－线径。后续修改线径仍保持主控直径。原图值、人工值和已确认值都会联动；数值或计算输入变化后，相关直径重新待确认。输入恢复为旧值也不会恢复旧确认。公差保留，仅将相关标准化结果标记过期。

缺少有效线径、直径非法、单位无法换算或内径非正数时，关联项保留最后有效值并标记失效，不能直接确认或生图。恢复有效输入后重算。旧订单打开不会自动启用新联动；非圆柱或非圆截面结构不套用该关系。已有公式推导的线径在启用后作为固定输入，避免外径与线径互相反推。

图号在原摘要位置直接编辑。未识别时可补填，也可清空；失焦或生成/切换前提交至现有保存队列。仅去首尾空白，保留 `00123`、`YD-001 23` 等字符串。失败保留输入并提供重试。图号不需要另行确认，不改变订单名称、文件名或ID。保存后历史订单提示同步更新。

## 数据和兼容

- `drawing_summary.drawing_no` 仍为可选字符串；空值表示未填写。新参数包使用当前已保存图号生成 `source.drawing_no`，新SW请求将非空字符串写入 `titleBlockProperties.客户图号`。历史任务、冻结请求及原参数重试保持原图号。
- 审图JSON可选 `diameter_linkage`：`version: compression-diameters/v1`、`driver_field`（三种直径之一）、`inputs`（主控直径/线径的实际值及单位）、`status: calculated/invalid`、`reason` 和首次联动前的 `original_parameters`。仅供内部状态恢复，不进入SW。
- 关联项用 `diameter_linkage_managed` 和既有公式元数据记录依赖，避免旧补全逻辑覆盖新关系；错误原因使用 `diameter_linkage_error`。原图证据和修改前值保留在原记录、联动快照及审计中。
- `diameter_linkage_updated` 审计事件记录整组参数、联动元数据和相关确认状态。修订冲突时以线径和三径为一组选择服务器值或本地值，不能逐项混合；图号按独立字段合并。
- 精度反推保留独立公差快照。系统联动的名义值不升级为独立输入；反推所需的当前几何由主控直径和线径计算，人工选择精度仍保持人工模式。
- 复用现有PATCH、修订号、保存队列、权限及审计，无新增接口或数据库迁移。

## 离线验证

```powershell
.venv/Scripts/python.exe scripts/test_diameter_linkage.py
node scripts/test_diameter_linkage_ui.mjs
.venv/Scripts/python.exe scripts/test_diameter_drawing_no_api.py
node scripts/test_diameter_drawing_no_browser.mjs
```

共享样例覆盖三个方向、主控切换、线径变化、来源保护的调整、确认撤销、同值依赖变化、非法几何、单位和精度反推。API测试使用临时SQLite和模拟SW，覆盖保存重开、修订冲突、图号字符串和冻结任务。浏览器使用模拟接口，验证即时联动、焦点、保存失败重试、整组冲突、跨订单晚到回执及桌面/窄面板。截图在忽略目录 `outputs/diameter-drawing-no-qa/`，不调用云端识别或真实生产生图。

部署前完成精度、参数建议、AI修改、确认、气泡和SW回归。执行 `docker compose up -d --build api worker` 后检查健康状态；前端更新JS/CSS缓存版本，Ctrl+F5刷新。

本次桌面与390px窄面板使用模拟订单检查，输入框保留原位置，联动不替换正在输入的控件。机械界面检查因本机缺少HTML解析模块降级为正则检查；报告的既有侧边强调线及侧栏尺寸动画不在本次修改范围，不作为本次新增问题，也不宣称完成全站无障碍审计。
