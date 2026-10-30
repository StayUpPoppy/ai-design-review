# 载荷识别证据与待核对候选

载荷候选在语义归一化后、尺寸角色重排和参数融合前分类。明确的 H/F 标注、载荷要求文字或高度/载荷表头进入原有载荷流程；候选所属区域内的未注尺寸标题、范围边界和公差信息联合识别为非载荷内容。不会用整页的“公差”关键词排除其他区域真实载荷，也不按数值范围删除候选。

视觉提示要求逐字保留 evidence，并通过 source_context 保留 kind、table_title、headers、row_text、unit_evidence。模型生成的编号或“载荷表第一行”不是独立证据。结构化工程接口的载荷字段保留；人工输入不重新过滤。旧审图保留原分类记录；载荷高度及力值公差可按下文独立证据规则进行本地核对，已确认及人工值受到保护。

review.load_point_diagnostics 为可选数组；旧记录缺少时按空数组展示。每项包含 candidate_id、status、original_candidate、page、evidence、source_context、reason_code、reason。状态为 pending / excluded / promoted / dismissed，promoted 项另存 promoted_load_point_id。候选 ID 按原始候选生成稳定摘要；重复候选去重，原文完整保留。reported_units 保留视觉模型实际报出的单位，界面不会把缺失单位标成已识别的 mm/N。

pending 项默认展开在独立待核对区；excluded、promoted、dismissed 项在默认收起的识别说明中查看。核对后加入预填现有新增表单，支持已知 cm/m/in 和 kN/kgf 换算，以及力值绝对允差换算。未知单位清空预填数值并提示按 mm/N 核对。加入不替代现有确认；忽略也保留原始证据。两项操作使用现有完整快照、修订号和审计事件保存，重复编号不覆盖原载荷。

只有 spring_parameters.load_points 参与计算、就绪检查和 SW 参数包。诊断列表不作为额外生图拦截项，历史冻结 SW 请求不改变。GET 不写回数据库；无需迁移。载荷合理性在统一为 mm/N 后检查，不修改原始值；缺项和不支持单位不会直接作数值比较。

验证脚本：test_load_point_recognition.py、test_load_point_recognition_api.py、test_load_point_recognition_browser.mjs。图纸错误基准为自由高度80、三组公差表数字30/315、120/1000、2000/3200；正常基准为订单2的 H1=14.284/F1=13.2N、H2=12.284/F2=18.9N。浏览器截图在 outputs/load-recognition-qa，使用模拟 API，不代表实际模型准确率。

2026-10-12 实图验收：用户明确批准后，使用部署容器中既有 DashScope/qwen3.7-plus 配置对两张原图各调用一次。压缩弹簧10的自由高度为80 mm，视觉模型未提取公差表数字为载荷，正式载荷列表及工作应力均为空。订单2保留 H1=14.284 mm/F1=13.2 N、H2=12.284 mm/F2=18.9 N，两个±10%允差均保留。原始响应及处理结果保存在 outputs/load-recognition-qa/{spring10,order2}-live.json，摘要为 live-summary.json；最终代码离线复核同一批候选通过。此次是容器识别流程验收；真实网页登录上传未执行（无登录会话），网页编辑、确认、保存及竞态通过模拟 API 浏览器测试。

界面沿用现有设计，桌面及320/390px宽度截图已核对。Impeccable机械检查使用正则回退（HTML解析依赖缺失，未计算对比度），告警为现有页面其他区域的侧边强调线，本次不改动这些区域；未据此声称完整视觉审计通过。

## 工作高度换算与力值公差

支持P/F编号、按原图证据核实的工作高度／压缩量／追加行程，力值和公差按同一标注绑定。新增可选高度关系元数据、旧订单本地恢复及人工编辑保护，现有SW结构不变。详见[载荷高度尺寸链与力值公差](load-height-relations.md)。
