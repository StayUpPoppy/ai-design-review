# 是否制扁（压缩弹簧可选工艺）

当前前端暂时隐藏“13 是否制扁”：参数表、审图工作台不显示该行，其余参数编号保持不变；指向该行的“去处理／定位参数”按钮一并隐藏。原图技术要求中的“制扁／不制扁”文字继续显示。字段含义仍为不制扁（整数0）、制扁（整数1）；真正缺失时沿用待确认默认0，图纸结果、冲突、人工值和人工清空不被默认值覆盖。

隐藏期间不提供该行的编辑、单项确认入口，也不纳入“全部确认可确认项”、计数及批量后续处理列表，避免确认不可见内容。已有值、确认状态、确认快照、历史记录和审计保留；AI对话应用修改仍保持原来的待确认规则。

未确认不阻止生图，生图就绪提示仍说明该字段未写入SW参数，参数行下方不重复显示小字；仍按原有八个必填建模参数、参数确认及合法性检查决定是否生图。不会根据磨平、并紧或外观推断制扁，不新增自动技术要求，不改变圈数、节距、刚度等公式。

## 识别和历史

OCR及视觉识别仅采用原图明确的制扁文字及原文依据。“不制扁”“无需制扁”等否定表达识别为0；不同位置要求相反时保留冲突，人工选择后方可确认。缺少明确文字的模型猜测保留诊断信息，不作为有效识别值。

旧订单缺字段时，读取视图补待确认默认值，不调用模型、不在GET请求中写库；后续正常保存持久化。已冻结任务及原参数重试沿用原参数包与请求，不补入新字段。

## 保存接口

沿用 `GET/PATCH /api/reviews/{job_id}` 和修订号、审计机制，无新接口或数据库迁移。内部字段示例：

```json
{
  "spring_parameters": {
    "flattening": {
      "value": 0,
      "unit": null,
      "tolerance_upper": null,
      "tolerance_lower": null,
      "source": ["solidworks_protocol_default"],
      "default_source": "flattening-default/v1",
      "evidence": "系统默认：不制扁，需人工确认。",
      "need_human_review": true
    }
  }
}
```

PATCH仍提交完整review、`expected_revision`及events。历史改值、单项和批量确认记录保持原样；隐藏后的批量确认事件不再包含`flattening`。正常保存继续保留该字段及其确认快照，不因隐藏自动清空或确认。保存失败可重试，修订冲突按现有流程处理。

## V2及SW契约

V2可选增加 `generation_parameters.spring_parameters.flattening`，仅当前值已确认、有效且无冲突时输出：

```json
{
  "label": "是否制扁",
  "value": 0,
  "unit": null,
  "tolerance_upper": null,
  "tolerance_lower": null,
  "confirmation_source": "human_confirmed"
}
```

前端预览、后端预览和实际请求一致增加 `modelParameters["是否制扁"] = 0/1`。0是有效值；缺失、无效或未确认时省略键，未确认的1不会被默认0替代。V1保持原契约，旧V2允许没有新字段。真实制扁建模需要SW接收端支持同名字段并另行联调，本仓库只负责展示、保存和传参。

## 验证与发布

离线回归：`scripts/test_flattening.py`、`test_flattening_ui.mjs`、`test_flattening_api.py`；批量及浏览器回归：`test_bulk_confirmation_ui.mjs`、`test_bulk_confirmation_browser.mjs`。共享样例校验前后端一致，临时数据库及模拟SW推送验证保存、并发修订、冻结请求和重试，不调用付费识别或真实SW。

本次仅调整前端显示，更新前端文件和资源版本后按 **Ctrl+F5** 刷新即可。前端由现有Nginx挂载目录提供，无需重建API、Worker、web或执行数据库迁移。识别、保存、生图就绪检查和SW传参沿用原规则，真实建模效果另行联调验收。
