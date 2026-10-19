# 技术要求翻译与失败恢复

有效非空译文直接写入现有技术要求编辑框。不再校验外文残留、中文说明充分性，以及数字、单位、变量、材料或标准编号差异，也不再生成或展示工程差异警告。原文和历史失败信息继续保存在记录及审计中。

机器翻译或候选恢复后仍为待确认。用户确认并成功保存后，正文才进入新任务的 SW 请求；不增加生图拦截，不改变去重、原始证据及历史冻结请求。

## 翻译接口与配置

- POST /api/reviews/{job_id}/technical-requirements/translate 沿用订单权限、稳定 ID 和已保存正文／类型快照检查，只返回结果，不直接保存或确认。
- mode=translate 调用现有 Qwen 文本翻译器；mode=revalidate 只读取实际保存的响应／识别候选，不调用模型。
- 模型配置优先级：TECHNICAL_REQUIREMENT_TRANSLATION_MODEL → STANDARDIZATION_CHAT_MODEL → QWEN_MODEL，默认回退保持现状。复用 QWEN_API_KEY 或 DASHSCOPE_API_KEY、QWEN_BASE_URL。
- TECHNICAL_REQUIREMENT_TRANSLATION_TIMEOUT_SECONDS 默认30秒；临时网络错误、429及服务端错误最多重试一次。不增加自动补译或内容重试。
- 保留网络／超时、空译文、无效 JSON／格式、缺失／重复／错误条目 ID，以及无法还原占位符的异常处理。非空译文即使仍含外语、与原文相同或工程内容变化，也按成功结果处理。
- 提示词继续要求翻译全部说明并保留工程信息。送译前保护数字、公式、变量、单位、标准和牌号，返回后还原已知占位符。缺少或重复可还原的已知占位符不产生内容警告；未知、损坏或还原后仍残留的占位符不能写入正文。

## 输出快照与编辑

可选 translation_output_snapshot 保存已接受译文的正文和类型：

```json
{
  "translation_status": "translated",
  "translation_input_snapshot": {"content": "Setzlänge Ls=3.59 mm", "type": "process"},
  "translation_output_snapshot": {"content": "设定长度 Ls=3.59 mm", "type": "process"}
}
```

外语检测仅决定尚未翻译的输入是否需要调用模型。当前正文和输出快照一致时，不再次检测译文内容，也不禁止确认或导出；旧成功记录缺少输出快照时兼容读取，不因打开订单重复送译。

修改正文撤销旧确认并使旧输出快照失效，后续按新输入处理；仅修改类型时更新输出快照、撤销确认，不额外翻译。输入中的 2D/3D、明确工程变量和代号仍使用原有工程上下文识别规则。

翻译仅在草稿保存成功后启动。沿用串行保存、修订号、编辑计数和订单切换保护；编辑后改回原文，也不能接收过期响应。保存失败保留本地译文，重试保存不重新调用模型。

## 历史失败候选

- 优先复用 translation_error_details.candidate_content 和原输入快照；也可读取已保存的 qwen_vision_raw.json、candidates.json 或 recognized_content。候选必须来自实际保存的响应，非空且无无法还原的占位符。
- 唯一对应原文／类型、当前正文与输入快照一致且未被人工或 AI 修改时，自动恢复到编辑框并转为待确认。
- 有人工改动、多个候选或无法唯一对应时保留正文，通过“采用候选译文”明确选择；采用后仍待确认。
- 不再检查候选外语或工程差异。实际保存的候选即使与送译原文相同，也允许恢复；不能把没有翻译响应的原始识别文本当成候选。
- 没有保存候选时继续提供重新翻译或人工填写入口，不自动调用模型。保留原失败信息于恢复审计 technical_requirement_translation_recovered，区分 automatic／adopted。
- 历史中文工程缩写误判仍可本地解除失败，不改写原文；同一页面不循环重试失败的恢复请求。

## 数据与 SW

元数据沿用现有审图 JSON，无需数据库迁移。translation_warnings 和 translation_warning_snapshot 仅保留历史兼容，不再生成或展示。translation_error_code 新失败使用 request_failed、model_uncertain、invalid_response，兼容读取旧内容校验错误。

前端确认、批量确认、分组、参数包预览及后端 SW 输出共用成功状态与输出快照；已确认有效译文可包含 Cu/Ni/Ag、Ls、Ø、Di、FN、LABS。未确认、正在翻译、保存失败或真正接口失败的条目沿用现有处理。已冻结任务及幂等重试继续使用原请求。

## 验证

运行翻译、接口、历史恢复、工程符号、旧警告兼容、前端编辑与保存竞态测试，以及技术要求去重、SW预览／推送与任务冻结回归。共享样例覆盖三张德文截图、外语保留、工程内容变化、同文返回、协议异常和成功结果不重复送译。浏览器在桌面和窄面板中使用模拟响应验收，不新增真实云端识别或翻译调用。
