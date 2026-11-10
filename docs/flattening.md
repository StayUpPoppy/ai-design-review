# 是否制扁（压缩弹簧可选工艺）

参数表在“端面磨削”后显示“是否制扁”，前方显示与现有编号同样式的蓝色圆圈序号13。13仅为参数行显示序号，不增加原图气泡或点击定位功能；该行不显示单位、公差、默认值说明和未确认小字。数值下拉框占用原数值与公差两列，与旋向、端部形式、端面磨削对齐，右侧保留确认按钮。下拉选项为不制扁（整数0）、制扁（整数1）。真正缺失时补系统默认0，保持待确认；图纸结果、冲突、人工值和人工清空不被默认值覆盖。

支持单项确认和批量确认。默认0也计入可确认项，这是该字段的例外，其他系统默认参数的批量排除规则不变。批量跳过缺失、无效、冲突或失效项。改选后须重新确认；AI对话应用修改也保持待确认。

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

PATCH仍提交完整review、`expected_revision`及events。改值采用`parameter_value_updated`；单项确认采用现有`recognized_value_confirmed`/`modified_value_confirmed`，批量采用`safe_fields_confirmed`并在`metadata.fields`中包含`flattening`。确认记录和快照保留实际人工操作，同时保留原默认或识别来源。保存失败可重试，修订冲突按现有流程处理。

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

同步代码后执行 `docker compose up -d --build api worker`；浏览器Ctrl+F5刷新。前端由现有Nginx挂载目录提供，无需重建web或执行数据库迁移。真实建模效果另行联调验收。
