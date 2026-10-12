# SolidWorks 命令格式

新建任务的 SW 请求与 `solidworks_preview` 使用相同模型投影。内部 `spring_generation_parameters/v2` 继续保留结构化材料、载荷点和原图技术要求；`solidworks_preview` 提供最终 SW 专用文本。

```json
{
  "TaskId": 1000000099,
  "models": [{
    "modelId": 1,
    "modelName": "订单2",
    "modelLabel": "压缩弹簧",
    "materialCode": null,
    "modelParameters": {
      "线径": 1.8,
      "中径": 25.2,
      "自由高度": 19,
      "圈数": 4,
      "有效圈数n": 2,
      "是否磨平": 1
    },
    "customProperties": {"旋向": "右旋"},
    "extraProperties": {
      "技术要求": "1.材料：SUS304。\n2.绕制方向：右旋。\n3.两端面表面粗糙度：Ra 12.5 μm。\n4.压并高度：Hb = 6.3 mm。\n5.当弹簧工作高度 H1 = 14.284 mm 时，对应工作载荷 F1 = 13.2 N。\n6.当弹簧工作高度 H2 = 12.284 mm 时，对应工作载荷 F2 = 18.9 N。\n7.总圈数：4 圈。\n8.工作圈数：2 圈。",
      "P'": 2.9314,
      "C": 14,
      "τ_b": 451.2669
    },
    "titleBlockProperties": {
      "材料": "SUS304",
      "重量": 0.00642403
    }
  }]
}
```

此例采用 SUS304、每端支承 1 圈、并紧磨平书页模型。Hb 已人工确认；没有图纸压并载荷 Fb，所以不把估算载荷写入技术要求。τ_b 仍使用有效估算结果。

- `P'` 使用 ASCII 单引号；三个计算键与“技术要求”并列，位于其后。值为 JSON 数字，四位小数，无单位字符串。合法零应力为 `0`，缺项、失效或不适用时省略对应键。
- 技术要求正文不重复标题，使用实际换行并连续编号。缺失条目跳过，其他已确认原图要求随后保留；只去除完整等价的独立参数句。
- 压并高度仅使用已确认、当前有效的输入或名义高度；上限参考不作为实际高度文字。唯一已确认的 Fb 与 Hb 高度一致时组合描述，不一致时分列并注明测试高度。没有 Fb 时只写 Hb。
- 工作点按原编号和顺序输出，保留百分比或绝对允差；支持 F3 等后续点。导出高度和力值转换为 mm、N，不支持的单位提示核对。
- `titleBlockProperties` 与 `extraProperties` 同级。材料为已确认纯牌号，技术要求继续保留材料；重量为当前单件重量 Q，JSON 数字，单位 kg，最多八位小数，不附单位字符串。缺失键独立省略，都缺失时发送空对象。
- 后端重新计算三个结果及重量，并在 `derived_parameters.solidworks_design_checks` 中冻结公式、输入、材料属性及版本。客户端缓存的 `design_checks` 不作为服务端依据。
- `solidworks_preview` 兼容旧 V2 记录缺少新增属性；历史任务的 `execution_options.solidworks_payload` 不改写。接口和数据库无需迁移，回调继续使用 `/api/solidworks/status`。
