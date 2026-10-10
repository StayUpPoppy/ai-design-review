# 压缩弹簧材料选择

压缩弹簧的材料行使用公司材料表中的 15 种材料。目录存放于 `config/compression_material_catalog.json`，前端选项、识别匹配和剪切模量读取同一份版本化配置；部署后不依赖原始 Excel 文件。其他弹簧类型继续沿用原有材料流程。

## 识别和选择

- 原图主要材料唯一匹配目录时自动选中完整名称，例如 `SUS304 不锈钢`，仍待人工确认。
- 主要材料未匹配时，仅采用图纸明确允许且唯一匹配的替代材料；替代技术要求和原文依据保留。`INCONEL 750` 是本项目为 X750 配置的明确别名，不表示俄文原材料与 X750 等效。
- 主要材料冲突、多个可用替代材料、泛称“类似材料”或没有材料信息时，不自动选择。
- 未匹配材料的原文仍可核对，不因清空选择而删除。俄文字母不转成形似的拉丁字母，也不只凭数字匹配材料。
- 新的人工或 AI 材料修改限定为目录选项。改选/清空撤销原确认；明确识别或允许替代的唯一匹配项可按原安全规则批量确认。
- 历史人工修改和已确认的原值不自动替换。非目录显示名称的旧值显示为“原有材料”，改选后采用目录名称。

## 数据及只读 API

`GET /api/material-catalog` 沿用现有用户身份验证，返回：

```json
{
  "version": "company-compression-materials-v1",
  "source": "公司材料标准.xlsx",
  "items": [
    {
      "id": "4",
      "display_name": "SUS304 不锈钢",
      "standard_value": "SUS304",
      "aliases": ["SUS304", "SUS 304"],
      "shear_modulus_mpa": 71500
    }
  ]
}
```

示例省略其余 14 项；`source` 以实际配置为准。目录加载失败时材料原值保留，选项暂不可改选，点击“重试加载材料”重新读取，不触发审图保存。

审图 JSON 的 `spring_parameters.material`：

- `value`：当前完整显示名称，同时用于生图输出。
- `standard_value`：当前选择的标准牌号，不是旧原图牌号。
- `raw_value`：原图材料文字。
- `material_id`、`material_catalog_version`：目录标识和版本。
- `material_selection_source`：`drawing | drawing_substitute | manual | ai`。
- `material_match_status`：`matched | empty | unmatched | conflict`。
- `material_selection_reason`、`material_substitution_evidence`：匹配说明与替代依据。

这些可选元数据仅存于审图 JSON 和审计事件，不进入冻结生图参数包，目录 ID 不写入 SW `materialCode`。目录读取不修改数据库；审图更改沿用串行保存、重试和修订号冲突处理。

## 固定参考 G 与刚度

目录内材料使用公司表内的固定 G：SUS304/SUS316 为 71500 MPa，SUS631 为 73500 MPa，17-7PH 为 75500 MPa，Inconel X750 为 79000 MPa，Inconel 718 为 77200 MPa。SUS631 和 17-7PH 是两个独立选项，不合并。

仍使用 `k = G × d⁴ / (8 × D³ × n)`。G 不按温度、线径或热处理修正；计算依据标明“公司材料表固定参考值”，不是对所有工况适用性的保证。本功能不新增应力或重量计算。

材料行不重复显示当前材料、原图材料和 G 的说明；相关数据及审计记录仍保留。未匹配、冲突和加载失败提示照常显示，替代依据默认折叠；没有提示时说明区域隐藏，不占额外空间。

计算只解析当前材料选择，不回退到原图旧 `raw_value` 或残留旧 `standard_value`。表外历史材料只能使用当前牌号已有的明确配置，无配置时提示不能计算。材料或配置变化不静默覆盖图纸值、人工刚度或已确认结果；沿用现有公式/建议重新核对流程。

历史公式明确记录旧 G，且按当前公司表计算的结果已不同，会显示“公式参考待更新”及旧/新 G 的提示，阻止误作安全公式批量确认；读取仅生成提示，不改写保存值或既有确认。单纯目录版本变化但 G 和结果相同，不制造过期提示。缺失的历史原图材料记录也不会用人工选择值补造。

## 导出、SW 与部署

只有已确认材料进入参数包和 SW：

```json
"extraProperties": {
  "材料": "SUS304 不锈钢"
}
```

两个前端参数包导出入口和实际 SW 请求使用同一当前名称。材料缺失或待确认的原警告、八个必填建模参数、技术要求及回调协议不变，已冻结旧任务不改写。

部署更新代码后执行：

```sh
docker compose build api worker
docker compose up -d --no-deps --force-recreate api worker
```

当前 web 挂载前端目录，更新前端文件及缓存版本后强制刷新即可，无需构建 web 镜像或进行数据库迁移。

本地回归入口：

```sh
python scripts/test_compression_material_catalog.py
python scripts/test_material_recognition.py
python scripts/test_material_catalog_generation.py
node scripts/test_material_catalog_ui.mjs
node scripts/test_material_catalog_browser.mjs
```

测试不调用付费识别或翻译模型；浏览器脚本使用模拟订单和 API。
