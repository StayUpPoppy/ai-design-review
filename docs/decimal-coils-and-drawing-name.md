# 圈数小数与图纸名称编辑

总圈数和有效圈数使用有限正数。单项确认、批量确认、就绪检查、手动及对话导出、前后端预览和新SW任务采用相同契约。人工输入不取整、不截断、不转字符串；有效圈数仍不得大于总圈数，其他工程检查及公式计算精度不变。不并紧时仍按原协议省略SW建模字段“有效圈数n”。

摘要中的“图纸名称”可直接输入、纠错或清空，图号编辑继续保留。名称存于 `drawing_summary.drawing_name`，提交时仅去除首尾空白，最多512个Unicode字符，内部空格保留。超长输入保留在本地并明确提示，缩短后可继续保存；空名称不阻止生图。名称无需单独确认，不撤销弹簧参数确认，也不重命名上传文件、图号、类型或订单ID。

保存成功后原地更新历史标题与悬停提示，空名称依次回退图号和订单ID。排序、识别状态及新结果红点保持原有逻辑；保存序号和审图修订保护旧列表响应，进度回执不提供已有订单的名称。保存失败保留输入并可重试，CAS冲突支持保留本地名称或采用服务器名称；跨订单及跨登录会话响应不回写当前输入。

新参数包将当前保存名称冻结到 `source.drawing_name`，实际SW请求 `models[].modelName` 使用该快照；为空则使用弹簧类型名称。历史冻结请求与原参数重试保持原值，修改名称或圈数只影响新任务。无需新接口或数据库迁移。

示例（摘录）：

```json
{
  "source": {"drawing_name": "客户 弹簧001-A"},
  "generation_parameters": {
    "spring_parameters": {
      "total_coils": {"label": "总圈数", "value": 10.5, "unit": null, "confirmation_source": "human_confirmed"},
      "active_coils": {"label": "有效圈数", "value": 8.25, "unit": null, "confirmation_source": "human_confirmed"}
    }
  },
  "solidworks_preview": {"modelParameters": {"圈数": 10.5, "有效圈数n": 8.25}}
}
```

实际SW模型中的对应内容：

```json
{"modelName": "客户 弹簧001-A", "modelParameters": {"圈数": 10.5, "有效圈数n": 8.25}}
```

离线验证：`scripts/test_decimal_coils_drawing_name.py` 使用临时SQLite与模拟SW验证数字契约、精度、长度边界、列表、修订冲突、冻结和原参数重试。`scripts/test_decimal_coils_drawing_name_browser.mjs` 使用本地前端和模拟接口验证单项/批量确认、名称输入、失败恢复、旧响应、焦点及桌面/窄面板。公共SW样例同时包含10.5/8.25和多位小数，验证前后端一致。测试不调用云端模型或生产SW。

API及worker变更需执行 `docker compose up -d --build api worker`；前端缓存版本更新后Ctrl+F5刷新。
