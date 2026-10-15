# 压缩弹簧设计校核值

适用普通圆丝圆柱等节距弹簧；明确为变节距、锥形或非圆丝时显示不适用。结果用于展示理论计算和估算，不作材料许用应力判定。

节距缺失时使用图片公式 `t=(H0-a*d)/n`，支承圈数按两端合计：磨平 1.5/2/2.5 圈分别取 a=1/1.5/2；不磨 2/2.5 圈取 a=3/3.5。项目的支承圈数字段为单端圈数，需乘 2；未知端部或支承圈数不猜测。图纸、人工及已确认值不会自动替换，人工清空保留为空。已确认公式节距的输入变化后保留原值，标记失效并暂停相关校核，直到输入恢复或人工修改。

缺少单端支承圈数时，两端并紧且总圈数、有效圈数具有独立来源，可用 `(n1-n)/2` 补算并进入人工确认。圈数来自公司默认支承圈数规则、未确认的生图默认值、另一圈数或支承圈数时不反推，避免循环依赖。人工清空和直接输入保留原值；自动支承圈数在人工修改圈数期间失效，两个圈数当前值都确认后重算，仍需单独确认。明确原图值或人工值与公式冲突时只提示核对。

理论刚度使用 G、线径、中径、有效圈数，与图纸刚度分别保留。每个非压并载荷点单独计算工作应力；力值为空时可根据高度估算，估算不写回载荷点。零载荷有效，负数、非数字和未知单位不会当作缺值替换。Fb/Pb/压并载荷等明确标识的唯一点用于压并应力；多个压并点需核对。

曲度系数和剪应力采用 [Newcomb Spring 提供的 Wahl 修正公式](https://www.newcombspring.com/resources/compression-spring-stress)：`K=(4C-1)/(4C-4)+0.615/C`，`τ=8*P*Dm*K/(π*d³)`。

两端不并紧使用 [Victory Spring 设计手册表7.1](https://victoryspring.ca/wp-content/uploads/2021/01/comprehensive-spring-design.pdf) 补充模型：不磨平时 `n=n1`、`t=(H0-d)/n1`、`Hb=(n1+1)*d`；磨平时 `n=n1-1`、`t=H0/n1`、`Hb=n1*d`，不依赖支承圈数。明确圈数关系冲突时暂停自动几何补算，已有力值的工作应力继续计算。

压并应力优先使用唯一明确压并力值，缺少高度不阻断。无力值时，先采用有效图纸或人工压并高度，否则采用当前端型名义高度；估算必须满足 `0<Hb<H0`。无效、过期或人工主动清空的实际高度不回退为名义值。名义高度独立于节距；节距缺失或失效只阻断依赖它的长度、重量。

参数区统一显示“压并高度”。缺少图纸或人工值时，`solid_height` 补算当前模型的名义高度，标为 `value_kind=nominal_estimate` 和“名义估算 / 待确认”；确认后仍保留估算身份。人工值和图纸值使用 `input_height`，人工清空不回填。名义高度依赖线径、圈数、端部条件，不依赖线径公差、自由高度或节距。未确认自动值联动重算；已确认自动值过期时保留旧值并暂停高度估算，应用新候选值后需重新确认。

含公差的上限参考只在标准校核与展开计算依据中显示，不替代参数行高度。上限采用不磨 `(n1+1.5)*dmax`，磨削约3/4圈时 `n1*dmax`，其中 `dmax=d+上偏差`；缺少公差注明按名义线径。标准上限建议只供参考或确认校核依据，不可覆盖名义或实际高度。旧 `reference_limit` 自动参考转为待确认的名义值，原值、来源、确认记录保留在 `legacy_reference_limit`；旧上限的确认状态不转移给名义值。无法确认旧记录用途时提示核对，不凭数值猜测。

`design_checks` 版本为 `compression-design-v2`；保留结果字段并增加 `reference_solid_height_limit`、`solid_height_used`，`nominal_solid_height` 始终只表示当前模型的名义值。应力记录 Pb、使用的 Hb、模型和来源。已确认自动圈数、节距、名义高度保留旧值和确认记录；依赖变化后标记失效并提供新候选值，应用后重新确认，恢复原依赖后恢复有效。单端支承圈数按下文固定公式与圈数确认联动规则处理。版本升级本身不使未变化的书页公式失效。展开长度使用总圈数，刚度使用有效圈数。

后端 `standardizers/design_checks.py` 和前端 `compression-design-checks.js` 使用共享样例核对结果。审图 JSON 的 `design_checks` 是派生结果，读取、保存和标准化时重新计算。GET 不自动写回数据库或本地文件。材料目录加载后页面重新计算当前草稿，编辑过程中不读取旧输入框覆盖参数。

长度支持 mm/cm/m/in，力值支持 N/kN/kgf；旧记录缺少单位时按原字段默认单位处理。Q 使用密度 g/cm³ 与尺寸 mm，乘 10⁻⁶ 得 kg，显示至八位小数。

验证：`test_compression_design_values.py`、`test_compression_design_values_ui.mjs`、`test_compression_design_values_api.py`、`test_compression_design_values_browser.mjs`，并运行既有 C/b、确认状态、保存竞态、材料和生图回归测试。

## 新公式候选与可选建议

节距、有效圈数、压并高度的有效重算候选，同时显示于参数行与“可选建议”。支承圈数仍仅在原参数行提示。两处共用候选计算和应用入口；应用后更新公式、实际输入和依赖快照，撤销旧确认，仍须在参数行重新确认，不沿用普通建议的自动确认行为。数值相同但输入依据变化也可应用；输入缺失或恢复原依赖时即时刷新。

`parameter_reasonableness.suggestions[]` 增加可选字段（旧建议缺少时维持原行为）：

```json
{
  "suggestion_kind": "formula_candidate",
  "suggestion_id": "formula_candidate:pitch:fnv1a32:计算快照哈希",
  "source": "formula",
  "target_field": "pitch",
  "current_value": 3.4438,
  "suggested_value": 3.6125,
  "application_mode": "value",
  "status": "available",
  "formula_candidate": {
    "value": 3.6125,
    "unit": "mm",
    "formula": "t = H0 / n1",
    "inputs": {"free_length": 28.9, "total_coils": 8, "end_type": "两端不并紧", "end_grinding": "两端磨削"},
    "purpose": "pitch",
    "source_fields": ["free_length", "wire_diameter", "active_coils", "total_coils", "support_coils", "end_type", "end_grinding", "pitch_type"],
    "basis": "当前端型公式；待人工确认",
    "status": "calculated"
  }
}
```

上例展示字段结构，实际 `inputs`、公式及哈希以当前模型计算快照为准。用途 `purpose` 为 `pitch`、`active_coils`、`nominal_estimate` 或 `reference_limit`。候选标识按字段及规范化计算快照生成，另保留原有依赖令牌；服务端独立复算，前端不信任陈旧候选。名义高度和上限参考按用途区分，明确应用上限候选后保持该用途，不迁移为名义值。

同字段、用途和方案去重，不同方案单列冲突且不计入批量应用。批量按依赖顺序试算并复算每层；下游值改变时跳过，显示新候选供用户再次决定。单项和批量共用撤销记录，恢复本次影响字段的数值、公式、用途、依赖及确认信息，保留之后无关字段的编辑；涉及字段已有后续编辑或确认时拒绝覆盖。建议消失后仍保留撤销入口。沿用审图修订号、审计、保存队列与失败重试，不新增接口或数据库字段。

验证：`test_formula_candidates.py`、`test_formula_candidates_ui.mjs`（共享样例及批量试算）、`test_formula_candidates_browser.mjs`（真实点击、保存重开、失败重试、即时联动、焦点和窄面板），并回归已有建议、确认、保存竞态与 SW 输出。

## 单端支承圈数固定公式与确认联动

自动值统一为 `(total_coils-active_coils)/2`，要求两端并紧、总圈数大于有效圈数、输入完整有效且具有独立依据。人工直接编辑圈数是独立输入；仅确认公司默认支承圈数推导出的有效圈数不解除循环依赖。原图明确两端支承不对称时不按均分补算。沿用现有参数输入校验，不调整其它计算公式。

识别器只提取明确单端标注，不自行推算。各来源在融合前统一分类为 `support_coils_origin=drawing_single_end/drawing_total/inferred/unknown`，明确单端证据优先于无依据的模型算术；原始候选文件不改写。参数保留可选 `support_coils_original`（原值、原文、来源、页码、坐标及原确认快照），仅供内部追溯，参数行不再提供“查看原识别依据”入口。未确认的模型推算或没有明确单端依据的自动值，按固定公式校正；例如16/14识别成2时改为1圈、待确认。原图明确单端值、人工填写或人工清空不自动覆盖；冲突通过参数行 `support_coils_conflict` 和合理性警告展示，用户可明确应用公式候选。

上传后人工修改总圈数或有效圈数时，自动支承圈数暂停使用并显示等待确认及试算候选。两项当前值都已确认后，自动重算单端值；原自动值即使已确认，也撤销其确认快照及 manual_confirmations。数值相同但输入不同亦需重新确认，输入未变不反复撤销。批量确认只确认用户本轮看到的公式快照，不把本轮新重算的支承圈数一起自动确认。该字段仍不加入“可选建议”。

`support_coils_adjustment` 保存自动调整前后值、实际输入及旧确认信息。GET仅计算返回视图，不写数据库或JSON文件；前端打开旧订单后，通过现有审计/保存队列提交 `support_coils_recalculated` 事件。保存与圈数确认使用同一队列和修订号机制；失败保留页面修改并重试。已确认值不因打开订单静默改写，用户后续修改并确认圈数时才触发自动值重算；历史冻结SW请求不变。

验证：`test_support_coils.py`（共享样例及压缩弹簧9离线重放）、`test_support_coils_ui.mjs`（完整前后端快照与确认顺序）、`test_support_coils_api.py`（GET只读、权威重算、保存重开及保护）、`test_support_coils_browser.mjs`（真实输入/确认、批量待确认、审计、失败重试和晚到保存响应）。不增加云端模型调用或数据库迁移。
