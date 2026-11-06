# 载荷高度尺寸链与力值公差

当前压缩弹簧识别同时支持P/F编号、直接工作高度、自由状态压缩量及载荷点之间的追加行程。新增识别继续使用原有Qwen请求；本地PDF文字/线段、已有OCR和有预算的本地OCR提供独立核实，不追加云端模型调用。

## 数值及证据

- 直接高度原样采用；自由压缩量使用`H=H0-S`；追加行程使用`H=H参考点-ΔS`。换算结果不再成为原始压缩量，反复保存和打开不会重复相减。
- 直接高度支持`H1=25mm`、`H1压缩到25mm`、`H1压缩至25mm`和对应的工作高度说明；压缩量、追加行程和不同P/F编号不会按同一条直接高度处理。原图核实关系优先于尚未核实的模型关系；模型不能自行认证高度。
- 同位置、同正文的重复OCR按一个物理位置核验，原始缓存及证据引用继续保留；不同位置或不同数值不直接合并。PDF只有力值文字、没有可核实高度时，继续利用同一原图已有OCR补核，不跳过载荷高度。
- 尺寸线必须确定起止位置。图形中先确定完整自由高度尺寸及载荷图的零位端，再区分从固定端量出的工作高度与从自由端量出的压缩量。连续尺寸基线按尺寸界线分段，不能把跨过两个单元的长线当成单项尺寸。
- 图片使用显示方向下的OCR框与本地线段，共享标注OCR缓存；位图线段先归一化尺度，再合并同一条界线的重复检测。缺少可靠端点时保留待核对，不按编号或力值大小猜尺寸链。
- 线段输入同时兼容OpenCV的`(N,1,4)`和`(N,4)`格式。辅助核验异常会保留识别结果和力值、记录诊断，将未核实高度留待核对，不中断整单；异常结果不写入核验成功缓存。
- 关系只在同页、同规格区域内建立；缺少规格区域不扩大为整页搜索。参考点解析为稳定`load_point_id`，排序和重命名不会改变计算依赖。
- 力值及公差按同一条标注绑定。N/kN/kgf绝对公差与百分比明确区分，支持对称、非对称和单边偏差；没有公差保持空值，0仍是有效值。不会从其他点或标准建议补公差。
- 刚度差商及载荷变化方向用于核对，不交换点位、不改力值或尺寸。参考尺寸属性保留；自由高度公差不自动转换为工作高度公差。

验收样例：自由高度133.35，参考压缩量7.58到P1，再压缩30.33到P2。P1高度125.77、力值1109.83N且公差为空；P2高度95.44、力值5550.05N及±221.96N。无历史锚点的原PDF及位图线段/模拟OCR均需通过；本功能不调整压并高度。

直接高度验收包括UQD06的11.414/9.474、UQD08的14.284/12.284、UQD04的21.15/9.668，均不做相减。`load-evidence/v3`使旧核验缓存重新判定；未确认自动值恢复后仍待确认，人工填写、清空和旧已确认值受保护。服务端保护的旧确认值使用可选`preserve_existing_value`标记，不能由模型产生。

## 审图JSON与兼容

`spring_parameters.load_points[].height_relation`为可选元数据：

| 字段 | 用途 |
|---|---|
| version、kind | `load-height/v2`；`absolute_height/free_deflection/incremental_deflection/unknown` |
| value、unit | 原始尺寸和单位，不存再次相减后的值 |
| base_label、base_point_id | 原参考编号及解析后的稳定ID，已有ID不会重新按编号配对 |
| mode | `automatic/manual`；人工改写或清空高度后单独保护，编辑力值不改变高度模式 |
| reference_only、evidence、evidence_refs | 原始参考属性、原文、页码和位置 |
| verified、verification_method、source_document_id | 服务端证据核实结果；模型和客户端不能自行认证原图尺寸 |
| status、reason、formula、last_inputs | 当前计算状态、原因、公式及实际依赖快照 |
| secant_rate、check_warning | 可计算的载荷差商及核对提示，不作为补算依据 |

原有`height/height_unit`保存最终工作高度；`load_tolerance_upper/lower/percent`继续保存力值公差。可选`force_tolerance_status`区分已标注、未标注和待核对。确认快照包含尺寸关系和力值公差；自动依赖变化撤销相关确认。缺失依据、循环或非法计算结果不会填0，已识别力值继续保留。

已有多规格`height_calculation: {formula: "H0-deflection", ...}`只有在保留明确原始`deflection`且与旧计算一致时才能迁移，不从现有高度倒推压缩量。人工修改、主动清空和来源不明的数据受到保护。

服务端正常读取可利用原文件/缓存生成内存修复结果；GET不写审图数据库或改变修订。`load_height_adjustment`记录待保存修正，前端通过原保存队列、CAS和审计落库。`load_point_recovery.applied_keys`记录已关联证据，防止删除后自动补回。已确认或人工改过的旧值保留，可选`load_relation_candidate`仅用于查看原图核对信息。

前端只增加简短换算提示及折叠依据，公差名称明确为“力值公差”。当前订单、用户与服务地址共同保护编辑回调，旧输入框销毁产生的迟到change事件不能激活其他订单。

SW和冻结参数包继续仅输出已确认有效的最终高度、力值及公差，以上识别元数据不进入SW正文。历史冻结请求和原参数重试保持原样；无新业务接口或数据库迁移。

## 离线验证与部署

```powershell
.venv/Scripts/python.exe scripts/test_load_height_relations.py
.venv/Scripts/python.exe scripts/test_load_line_evidence.py
.venv/Scripts/python.exe scripts/test_load_direct_height_evidence.py
node scripts/test_load_height_relations_ui.mjs
.venv/Scripts/python.exe scripts/test_load_height_relations_api.py
node scripts/test_load_height_relations_browser.mjs
```

`LOAD_HEIGHT_TEST_PDF`可指定验收PDF；本地提供的原图优先使用。接口测试在没有该附件时生成临时的同类尺寸链PDF。浏览器、Qwen及SW使用模拟响应；数据库使用临时SQLite，不修改真实订单。

后端及前端更新后执行`docker compose up -d --build api worker`，检查服务健康并Ctrl+F5刷新。高度换算及主脚本缓存版本为`20261103-load-graph-v1`。

## 通用名称与双语载荷表（v3）

Pn、Fmin、F_A、数字、下标和中文工况名只用于标识，不再用固定F/P白名单决定高度是否有效。名称之外，必须有力值单位/明确工程语境；刚度N/mm、压力MPa、力矩N·mm仍不能当作载荷。原编号和稳定ID分别保存。

本地核验支持Height/Load、安装高度/载荷等纵向相邻行及横向列头表格。高度和力值须各有单位，且属于同一列/行、同一载荷区块；合并标题不作为数值。OCR重复框合并，完整15框中的1和5不再制造多个高度；不同单元数字不能拼接。匹配仍限同页和本规格区域，多处不同高度保留冲突。核验方式为table_cells，折叠依据保留高度与力值单元的证据引用。

NBM200M-2454采用表格15mm/142.1N，图示13±0.5独立保留；Pn±5N仍绑定原力值。表格关系无法核实时提示“表格中的高度与载荷关联尚未核实”，尺寸链提示起止关系，缺少参考点及多高度冲突分别保留原因。直接高度不会再次相减。旧订单复用保存响应与OCR缓存修复未确认自动值，人工/已确认值不静默替换。


## 图形载荷直接高度补核（v4）

新增通路只补核缺失/未核实高度；已有明确文字、载荷表、尺寸链及v3成功缓存优先保留。原轴向Hough线段输入不变；位图额外使用本地LSD保留倾斜线、引出线和折线，PDF复用原矢量线段，不增加云端调用。

共同基准、尺寸基线两端界线和载荷曲线交点必须成立。根据标注直接接触或可追踪的引出线落点关联载荷竖线，多个可能配对不能唯一消歧时保持待核对；不按编号、数字大小、左右顺序或刚度反选。少量照片倾斜与四方向旋转在局部坐标核验后换回原图坐标。范围限定同页及本规格，尺寸之外的重复OCR和无关数字不会成为高度。短断线只在两侧共线支持时补连，交叉但不接端点的线不当作连通引出线。

本地原照片重放：回位弹簧F1为22.5mm/29.26N、F2为20mm/42.56N，公差均空；主弹簧F1为32mm/805±81N、F2为29mm/1496±150N。主弹簧的26属于另一界线，不借给F2。两图均为absolute_height，改变自由高度也不再次相减。

height_relation可选元数据：

- `geometry_evidence`：`load-graph/v1`、基准、尺寸端点、载荷落点、曲线及引出线路径，坐标均为原图归一化坐标；核验方式为`dimension_graph`或`dimension_leader`。
- `verification_failure`：引出线分叉、多个合理配对等具体原因；前后端显示同一待核对说明。
- `graphic_hint`：当前Qwen请求提供的可选位置候选；不信任其自带核验标记，也不单独用于认证。
- `geometry_candidate`：与成功结果不同的图形候选，仅追溯，不替换当前结果或确认。

核验缓存为`load-evidence/v4`；原v3缓存的成功点继续复用，混合缓存仅补核未成功点。旧订单在内存恢复未确认自动高度，正常保存队列/CAS/审计落库，人工值、清空、已确认及成功原图关系受保护。辅助检测失败不会写入成功缓存。以上元数据不进入SW，冻结任务和原参数重试不变。

参数编辑器的数值和公差事件绑定当前订单、用户/服务范围及审图对象；销毁旧输入框产生的迟到change/input不得重新激活上一订单。

## 标准号显示精简

标准号仅从主要参数和高级参数编辑列表隐藏，计数及该列表的批量确认不包含此项。模板、原值、原确认、识别保存、精度/标准化及确认单/PDF保留。气泡坐标和字段ID保留；前端按13个主参数显示编号，2号为通用精度等级。标准号和压并高度的气泡隐藏，分别通过“标准化”页签和高级参数行定位。仅隐藏或导航不保存/撤销确认。

新增离线检查：

```powershell
.venv/Scripts/python.exe scripts/test_load_graph_geometry.py
.venv/Scripts/python.exe scripts/test_load_graph_geometry.py --local
.venv/Scripts/python.exe scripts/test_load_graph_recovery_api.py --local
node scripts/test_bulk_confirmation_ui.mjs
node scripts/test_bulk_confirmation_browser.mjs
node scripts/test_load_height_relations_browser.mjs
```

`--local`额外使用本地保存的两张原照片、原响应和OCR缓存；普通测试使用自带图形样例及临时SQLite。浏览器全部模拟接口，不发起识别或生产SW请求。部署仍为`docker compose up -d --build api worker`，无需数据库迁移，Ctrl+F5后重新打开旧订单即可补核。
