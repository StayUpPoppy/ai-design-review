# 压缩弹簧材料库与搜索选择

配置 `DATABASE_URL` 时，压缩弹簧材料以 PostgreSQL 的 `spring_materials` 表为准；未配置时，本地模式读取 `config/compression_material_catalog.json`。下拉、识别匹配、材料修改校验、刚度、重量、设计校核和 SolidWorks 参数准备共用同一个目录入口。其他弹簧类型沿用现有流程。

材料下拉支持搜索。数据库材料可使用初始化命令按代码追加，材料数据随镜像发布。

## 数据和参数

初始化数据包含 108 条材料，来源为《审图材料标准表.xlsx》。JSON 记录源文件 SHA-256，每条材料保留来源名称、Excel 行号和排序。第 132–136 号依次为 `60Si2CrVAT`、`ASTM A229`、`GB/T 4357-2022-DH`、`ASTM A313 Type 302`、`ASTM A401`。`ASTM A313 302 SST` 可匹配第 135 号，`SWP-B` 仍匹配第 1 号 `SWPB`。

| 参数 | 单位 | 是否必填 |
| --- | --- | --- |
| 抗拉强度 `tensile_strength_mpa` | MPa | 否 |
| 剪切模量 `shear_modulus_mpa` | MPa | 是 |
| 弹性模量 `elastic_modulus_mpa` | MPa | 否 |
| 密度 `density_g_cm3` | g/cm³ | 是 |
| 许用剪应力 `allowable_shear_stress_mpa` | MPa | 否 |
| 许用应力系数 `allowable_stress_coefficient` | 无量纲 | 否 |

G、ρ 必须是有限正数。其余四项缺失时保存为 `null`；填写时也必须是有限正数。许用剪应力保留来源值，不按抗拉强度乘系数重算。本次只接通现有计算，不增加应力合格判定。

已有 15 种材料的代码、标准牌号、别名及六项数值保留。代码 10、11、15 保留规范名称 `Inconel X750`、`70#`、`Inconel 718`，表内原写法留存在 `source_display_name`。新材料名称沿用来源表。`60Si2Mn` 与 `60Si2MnA` 是独立材料，其 G 分别为 78000、78500 MPa。

数据库另外保存启用状态和更新时间。仅启用材料参与选择、匹配和计算。根据启用材料内容生成稳定 SHA-256 版本，时间戳不影响版本。

## 搜索、识别和兼容

- 点击材料框展开下拉，搜索框位于顶部，下方列表独立滚动。按名称、牌号或别名本地筛选，忽略大小写、空格及常见连接符。清空搜索恢复全部材料；每次打开重置搜索并标记当前选择。
- 支持方向键、回车、Esc、外部点击和 Tab；输入法选字期间回车不选材料。无结果显示“未找到匹配材料”。视口不足时向上展开，窄屏限制在视口内。
- 搜索、打开和关闭都不修改参数、确认状态或保存审图。实际改选/清空才进入原有修改、重新确认和保存流程，同一材料重复选择不产生编辑。搜索词不能当作新材料保存。
- 精确牌号优先；重叠文字采用较完整匹配。`SUS304-WPB` 不同时命中 `SUS304`，而 `SUS304-WPB 或 SUS304` 仍是两个候选，需要人工选择。
- 只有图纸明确允许且唯一匹配的替代材料才能自动采用，并保留原文依据。不推断近似材料等效，不把俄文字母转成形似拉丁字母，不凭裸数字匹配牌号。
- 加载失败保留原材料、禁用改选并显示重试入口。表外历史值作为原有材料显示，不成为新的目录选项。切换订单、关闭工作台或重建参数行时关闭面板，旧事件不能修改另一个订单。

## API、计算和快照

`GET /api/material-catalog` 沿用身份验证，保持 `{version, source, items}` 结构。数量不再固定为 15。每条材料返回 `id`、`display_name`、`standard_value`、`aliases`、六项参数及来源信息。可选属性没有数据时为 `null`。版本形式为 `company-materials/sha256:内容摘要`。

审图材料参数继续保存 `value`、`raw_value`、`standard_value`、`material_id`、`material_catalog_version`、选择来源及替代依据。目录代码不直接作为 SW `materialCode`；已确认材料通过现有标题栏属性输出。

刚度公式仍为 `k = G × d⁴ / (8 × D³ × n)`，现有重量估算使用 ρ。参数采用公司表内固定参考值，不按温度、线径或热处理修正。计算只读取当前材料，不回退到原图 `raw_value` 或旧 `standard_value`。数据库模式下，未启用或不存在的材料不能从旧属性 JSON 获取 G。

历史人工值、确认状态和证据不因目录升级而改写。目录版本变化但 G 和结果未变时，不制造公式过期提示。新参数包保存所用材料属性和版本；已有冻结任务、SW 重试继续使用冻结值。

API、Worker 启动时加载材料快照。配置数据库但表缺失、数据为空、连接失败或数据不合法时明确失败，不回退到 JSON。修改材料表后需要重启 API 和 Worker，本阶段不提供动态刷新。

## 初始化和 Docker 更新

首次部署先执行 `docker compose up -d postgres`。已有数据库升级前先备份，然后依次执行，每一步成功再执行下一步：

```bash
bash deploy/backup_postgres.sh
docker compose build api worker
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m ai_design_review.material_catalog_seed
docker compose up -d --no-deps --force-recreate api worker
docker compose ps
```

首次无业务数据时可以跳过备份，仍须先迁移、初始化，再启动 API 和 Worker。首次启动前端执行 `docker compose up -d web`。

初始化命令用单个事务导入空表。已有数据与整份目录一致时直接返回；存在差异时列出代码并退出。

已有部署添加第 132–136 号材料时，在同步代码后运行：

```bash
docker compose build api worker
docker compose run --rm --no-deps api python -m ai_design_review.material_catalog_seed --append 132 133 134 135 136
docker compose up -d --no-deps api worker
```

追加模式检查指定代码和现有材料的牌号及别名。相同记录会跳过，发现冲突时整批回滚。PostgreSQL 导入期间锁定材料表。原数据库结构适用，重启后刷新浏览器即可从材料下拉搜索新牌号。

沿用 `postgres_data` 持久化卷。重建 API、Worker 不删除材料数据，不使用 `docker compose down -v` 更新。web 挂载前端目录，同步文件和缓存版本后刷新浏览器即可。

检查容器日志并使用正常用户身份访问材料接口。标准目录有 108 条启用材料。可选择 `ASTM A313 Type 302`，核对 G=68950 MPa、ρ=7.92 g/cm³。应用回退使用旧镜像和对应前端，保留材料表和数据。

## 验证入口

```bash
python scripts/test_material_catalog_database.py
python scripts/test_compression_material_catalog.py
python scripts/test_material_recognition.py
python scripts/test_material_catalog_generation.py
python scripts/test_compression_stiffness.py
node scripts/test_material_catalog_ui.mjs
node scripts/test_material_catalog_browser.mjs
```

数据库脚本使用临时 SQLite，验证迁移、初始化、按代码追加、冲突回滚、快照、API/Worker 启动、材料匹配、计算及冻结生成。浏览器脚本使用模拟订单/API 验证搜索、键盘、输入法、确认、保存重试、切换订单和桌面/窄屏布局。`UNIT_TEST_BROWSER_CHANNEL=msedge` 可使用已安装 Edge，`MATERIAL_TEST_SCREENSHOTS=0` 可关闭截图。

### 本次验证记录（2026-11-08）

- 材料数据库 11 项测试、材料匹配/识别、生成参数、压缩刚度、材料 UI 及刚度 UI 回归通过。
- 在隔离 PostgreSQL 16 容器执行完整 Alembic 迁移至 `20261108_01`，导入 103 条；新 Docker 镜像内再次初始化返回内容一致。实际 API 返回数量、版本及 `60Si2MnA` 的 G、ρ 正确。
- API、Worker 容器删除后重建，PostgreSQL 重启，材料数量和内容版本保持一致。测试使用独立数据库，没有部署业务服务器。
- Edge 模拟 API 测试覆盖 1440、1100、390px 宽度。桌面和窄屏截图已检查，搜索框固定在选项列表上方，无横向越界。截图位于忽略目录 `outputs/material-catalog-qa/`。
- 扩展检查发现两项既有失败：`test_api_documentation.py:282` 仍要求旧“每端磨270°”描述，当前原有描述为“磨面角≥270°”；`test_compression_design_checks_ui.mjs:153` 的直径联动场景预期旋绕比 9、实际为 10。本次未修改对应 SW 文档字段、直径计算脚本或这两个测试，不将它们计为通过。
- 界面机械检查提示的 11 项 CSS 警告均位于本次未修改的边条和布局动画规则；新增搜索样式没有命中该检查。此次验证不代表全项目测试全部通过。
