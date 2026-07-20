# RAGFlow HTTP 接口清单（按接口目录图）

> 本文件严格按照“RAGFlow 接口目录图”的分组与接口顺序整理，作为 AI Design Review 对接 RAGFlow 的接口台账。
>
> 目录来源：用户提供的接口截图。路径映射依据 RAGFlow HTTP API 官方参考页于 2026-07-20 核对。截图中的 BUG 标记原样保留，它表示当前对接方需要重点验证的接口，不应直接理解为 RAGFlow 官方已确认的产品缺陷。

## 1. 通用约定

### 1.1 基础地址与鉴权

~~~
Base URL: http(s)://<ragflow-host>
API prefix: /api/v1
Header: Authorization: Bearer <RAGFLOW_API_KEY>
~~~

除健康检查和少数使用登录令牌的可选端点外，以下接口使用 RAGFlow API Key。客户端必须同时判断 HTTP 状态码、响应 JSON 的 code 和 data。

### 1.2 版本兼容说明

接口目录图中有两处使用 PUT，但当前官方 HTTP API 参考已将其标记为弃用：

| 目录图方法 | 目录图接口 | 当前官方建议 |
|---|---|---|
| PUT | 更新块 | PATCH /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id} |
| PUT | 更新聊天助手里的会话 | PATCH /api/v1/chats/{chat_id}/sessions/{session_id} |

本文件会同时保留“目录图方法”和“建议实现方法”。如果当前 RAGFlow 前面还有自定义网关，最终以该网关的契约为准。

### 1.3 成功与异步任务

- 成功响应通常为 code = 0；
- 文档解析、知识图谱和 RAPTOR 构建均可能是异步任务：提交成功不表示已可以检索；
- 图纸审查业务应在解析/构建状态完成后再允许使用相关知识；
- 删除数据集、文档、Chunk、知识图谱均是管理端高风险操作，不得由普通审图链路触发。

## 2. 数据集管理

| 目录图接口 | 目录图方法 | 当前官方路径 | 关键请求字段 | 对接说明 |
|---|---|---|---|---|
| 创建数据集 | POST | /api/v1/datasets | name 必填；可选 description、embedding_model、permission、chunk_method、parser_config | 建立标准、工艺、已确认案例等知识库 |
| 删除数据集 | DELETE | /api/v1/datasets | 数据集 ID 或 IDs | 仅知识库管理后台可用 |
| 更新数据集 | PUT | /api/v1/datasets/{dataset_id} | 名称、描述、解析或检索配置 | 不要在已有生产文档解析时随意改分块策略 |
| 获取所有数据集 | GET | /api/v1/datasets | page、page_size、name、id、include_parsing_status | 服务启动时可校验固定知识库是否存在 |
| 获取知识图谱 | GET | /api/v1/datasets/{dataset_id}/knowledge_graph | dataset_id | GraphRAG 成果查看 |
| 删除知识图谱 | DELETE | /api/v1/datasets/{dataset_id}/knowledge_graph | dataset_id | 高风险管理操作 |
| 构建知识图谱（BUG） | POST | /api/v1/datasets/{dataset_id}/run_graphrag | dataset_id | 返回 graphrag_task_id；先在测试库验证 |
| 获取知识图谱构建状态（BUG） | GET | /api/v1/datasets/{dataset_id}/trace_graphrag | dataset_id | 轮询任务进度与失败信息 |

### 数据集使用约束

建议至少分为三个 Dataset：spring-standards、spring-process、spring-approved-cases。检索时必须按 spring_type 和 status=active 过滤，不能把过期标准、草稿资料或未批准案例混入生产回答。

知识图谱适合跨章节关系追溯；对公差、公式、数值等精确知识，最终仍应引用原始 Chunk，不能引用摘要替代。

## 3. 数据集内的文件管理

| 目录图接口 | 目录图方法 | 当前官方路径 | 关键请求字段 | 对接说明 |
|---|---|---|---|---|
| 上传文档 | POST | /api/v1/datasets/{dataset_id}/documents | 默认 type=local，multipart file；也支持 type=web 与 type=empty | 上传后记录返回的 document_id |
| 更新指定文档的配置 | PUT | /api/v1/datasets/{dataset_id}/documents/{document_id} | name、meta_fields、chunk_method、parser_config | 解析前写入弹簧类型、标准版本、有效状态等元数据 |
| 下载文档 | GET | /api/v1/datasets/{dataset_id}/documents/{document_id} | dataset_id、document_id | 审计、抽查原始资料 |
| 获取上传的所有文档列表 | GET | /api/v1/datasets/{dataset_id}/documents | page、page_size、name、run、suffix、metadata_condition | 用于查询解析状态、定位 document_id |
| 删除文档 | DELETE | /api/v1/datasets/{dataset_id}/documents | ids 或 delete_all | 仅管理后台；避免业务流程误删 |
| 解析指定数据集中文档 | POST | /api/v1/datasets/{dataset_id}/chunks | document_ids | 异步触发解析、切块、嵌入与索引 |
| 停止解析指定文档 | DELETE | /api/v1/datasets/{dataset_id}/chunks | document_ids | 仅用于取消/故障恢复 |

### 推荐摄取顺序

~~~
创建或确认 Dataset
  -> 上传文档
  -> 更新 document 的 meta_fields / parser_config
  -> 触发解析
  -> 轮询文档列表中的 run 状态
  -> 抽查 Chunk
  -> 标记为可参与生产检索
~~~

上传完成不等于索引完成。任何未完成解析的资料不得作为“没有检索结果”的依据。

## 4. 数据集内的区块管理

| 目录图接口 | 目录图方法 | 建议实现方法与路径 | 关键请求字段 | 对接说明 |
|---|---|---|---|---|
| 添加块 | POST | POST /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks | content；可选 important_keywords、questions、tag_kwd、image_base64 | 可人工录入或修订高价值标准条款 |
| 列表区块 | GET | GET /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks | keywords、page、page_size、id | 用于人工检查切分质量 |
| 删除区块 | DELETE | DELETE /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks | chunk_ids 或 delete_all | 管理端操作；优先下线而非删除 |
| 更新块 | PUT | PATCH /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id} | content、important_keywords、questions、positions、tag_kwd、available、image_base64 | 当前官方推荐 PATCH；PUT 为旧别名 |
| 检索区块（BUG） | POST | POST /api/v1/retrieval | question；dataset_ids 或 document_ids；可选 threshold、top_k、rerank、metadata_condition | 项目自动标准化和合理性判断的首选 RAG 接口 |

### Chunk 可用性接口

目录图未单列，但区块治理必须纳入：

| 用途 | 方法与路径 | 作用 |
|---|---|---|
| 批量更新块可用性 | PATCH /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks | 传 chunk_ids 和 available 或 available_int；可将错误、失效或未审核资料下线 |
| 获取单个块 | GET /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id} | 审核具体内容与来源位置 |
| 获取元数据汇总 | GET /api/v1/datasets/{dataset_id}/metadata/summary | 检查 spring_type、status、standard_version 等元数据分布 |
| 批量更新元数据 | POST /api/v1/datasets/{dataset_id}/metadata/update | 依据 selector 更新或删除文档元数据 |

### 检索区块（BUG）验证要求

在接入生产标准化之前，至少验证：

1. question 与 dataset_ids 的组合能返回 Chunk；
2. metadata_condition 能正确隔离压簧、拉簧、扭簧等知识；
3. 返回结果中能取得 document_id、document_name、chunk_id、content、similarity、vector_similarity、term_similarity 和位置；
4. 无命中、低相似度、服务超时均被本项目识别为“需人工确认”，不能默认为参数合理；
5. 结果引用可被保存到 review 的 rag_references。

## 5. 聊天助手管理

| 目录图接口 | 目录图方法 | 当前官方路径 | 关键请求字段 | 对接说明 |
|---|---|---|---|---|
| 创建聊天助手 | POST | /api/v1/chats | name 必填；可选 dataset_ids、llm_id、llm_setting、prompt_config | 用于工程师知识问答，不直接改写审查字段 |
| 更新聊天助手 | PUT | /api/v1/chats/{chat_id} | 可更新 name、dataset_ids、模型与检索/提示配置 | 改动提示词或知识库关联需版本记录 |
| 删除聊天助手 | DELETE | /api/v1/chats/{chat_id} 或 /api/v1/chats | chat_id 或 ids | 仅管理后台 |
| 列表聊天助手（ChatId） | GET | /api/v1/chats；按需 GET /api/v1/chats/{chat_id} | page、page_size、keywords、name、id | 获取可用助手或按 ChatId 校验配置 |

Chat Assistant 可托管提示词、模型和检索配置。对于自动标准化/合理性输出，仍推荐先使用独立检索接口，再由本项目 LLM 按既有 JSON Schema 生成受控结果。

## 6. 会话管理

| 目录图接口 | 目录图方法 | 建议实现方法与路径 | 关键请求字段 | 对接说明 |
|---|---|---|---|---|
| 创建聊天助手会话 | POST | POST /api/v1/chats/{chat_id}/sessions | name；可选 user_id | 保存知识问答上下文 |
| 更新聊天助手里的会话 | PUT | PATCH /api/v1/chats/{chat_id}/sessions/{session_id} | name | 当前官方推荐 PATCH；PUT 为旧别名 |
| 列表聊天助手里的会话 | GET | GET /api/v1/chats/{chat_id}/sessions | page、page_size、id | 查询和恢复会话 |
| 删除聊天助手里的会话 | DELETE | DELETE /api/v1/chats/{chat_id}/sessions | ids 或 delete_all | 用户或后台显式操作 |
| 与聊天助手对话 | SSE | POST /api/v1/chat/completions，stream=true | chat_id、session_id、messages 或 question | 接收 text/event-stream，并保留最终引用与 session_id |

非流式聊天同样使用 POST /api/v1/chat/completions，但设置 stream=false。传 chat_id 不传 session_id 时，RAGFlow 会自动创建会话；生产系统应接住返回的 session_id。

## 7. Agent

| 目录图接口 | 目录图方法 | 当前官方路径 | 关键请求字段 | 对接说明 |
|---|---|---|---|---|
| 与 Agent 对话非流式 | POST | /api/v1/agents/chat/completions，stream=false | agent_id、messages；可选 session_id、return_trace | 返回最终 data、引用和可选 trace |
| 与 Agent 对话 | SSE | /api/v1/agents/chat/completions，stream=true | agent_id、messages；可选 session_id | 消费 SSE 分片，完成时保存 session_id 与 trace |
| 列出来所有的 Agent | GET | /api/v1/agents | page、page_size、title/name、id | 选择或校验可用 Agent |

Agent 也可用 OpenAI 兼容路径 POST /api/v1/agents_openai/{agent_id}/chat/completions。Agent 的 Canvas DSL 适合复杂编排，但不属于第一阶段 RAG 数据对接的必要依赖。

## 8. 接口目录对应关系

~~~
数据集管理
  -> Dataset 创建、版本管理、GraphRAG 任务
数据集内文件管理
  -> 资料进入知识库并完成解析
数据集内区块管理
  -> 校验知识质量、元数据筛选、检索引用
聊天助手管理 + 会话管理
  -> 工程师可追溯的 RAG 知识问答
Agent
  -> 后续复杂流程编排或独立助手
~~~

本项目第一阶段的实际必经接口只有：创建/获取 Dataset、上传/配置/解析/查询文档、Chunk 审核、POST /api/v1/retrieval 和 GET /api/v1/system/healthz。截图中标有 BUG 的知识图谱与检索接口应先完成独立验收，再接入业务流程。

## 9. 对接验收清单

- [ ] RAGFlow 健康检查通过；
- [ ] Dataset、Document、Chunk、Chat、Session、Agent 的 ID 命名和存储位置明确；
- [ ] 文档已完整解析，关键 Chunk 已人工抽检；
- [ ] 检索能按 spring_type、status、标准版本过滤；
- [ ] 检索结果可返回并保存引用信息；
- [ ] 图中两个 BUG 接口已在测试环境验证并形成结果记录；
- [ ] PUT 到 PATCH 的迁移策略已与实际部署版本确认；
- [ ] 无结果、超时、鉴权失败、解析未完成均安全降级为人工确认；
- [ ] 不向浏览器暴露 RAGFlow API Key。
