# RAGFlow HTTP API 集成手册

> 面向 AI Design Review 的弹簧知识 RAG 接入。
>
> 来源：[RAGFlow HTTP API 官方参考](https://ragflow.com.cn/docs/http_api_reference)。本文按该页面于 2026-07-20 整理；页面当前标注为开发版 0.26.0。实施时以部署实例对应版本的官方文档为准。

## 1. 目标与边界

新增弹簧类型应使用 RAGFlow 中的标准、工艺规范和已确认案例辅助标准化及参数合理性判断，而不是新增一套 Python 弹簧业务规则。

RAGFlow 负责知识摄取、切片、检索、引用与可选的托管聊天。本项目仍负责通用控制：字段和单位解析、当前图纸参数摘要、JSON Schema 校验、引用审计、低置信度转人工确认和 ERP 放行控制。

原则：RAG 命中是业务依据；没有适用且足够的引用时，只能输出“需要人工确认”，不能自动补造参数或自动放行。

## 2. 基础约定

### 2.1 地址、认证与错误

~~~
Base URL: http(s)://<ragflow-host>
API prefix: /api/v1
Authorization: Bearer <RAGFLOW_API_KEY>
~~~

大多数管理、数据集、检索和 Chat API 都应携带 API Key。官方参考中搜索补全及部分问答增强接口示例使用登录令牌；调用这些可选能力前必须按部署版本确认令牌类型。调用方要同时检查 HTTP 状态码、响应 JSON 的 code（成功通常为 0）和 data 内容。

常见 HTTP 错误包括：400 参数错误、401 未授权、403 无权限、404 资源不存在、500 服务内部错误。块管理还可能返回业务错误码 1001（无效 Chunk ID）或 1002（块更新失败）。

### 2.2 本项目建议配置

密钥只能保存于后端 .env 或密钥管理服务，绝不可下发到浏览器或打印到日志。

~~~
RAGFLOW_BASE_URL=http://127.0.0.1:9380
RAGFLOW_API_KEY=<server-side-only>
RAGFLOW_STANDARDS_DATASET_ID=
RAGFLOW_PROCESS_DATASET_ID=
RAGFLOW_CASES_DATASET_ID=
RAGFLOW_STANDARDIZATION_CHAT_ID=
~~~

浏览器只访问本项目 FastAPI；FastAPI 以服务端身份调用 RAGFlow。

### 2.3 不使用已弃用路径

| 已弃用 | 新路径 |
|---|---|
| POST /api/v1/chats_openai/{chat_id}/chat/completions | POST /api/v1/openai/{chat_id}/chat/completions |
| POST /api/v1/chats/{chat_id}/completions | POST /api/v1/chat/completions |
| PUT /api/v1/chats/{chat_id}/sessions/{session_id} | PATCH /api/v1/chats/{chat_id}/sessions/{session_id} |
| PUT /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id} | PATCH /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id} |
| GET /v1/system/healthz | GET /api/v1/system/healthz |

## 3. 关键 API 速查

下表路径均相对于 RAGFLOW_BASE_URL。

### 3.1 健康检查

| 用途 | 方法与路径 | 认证 | 说明 |
|---|---|---|---|
| 服务依赖检查 | GET /api/v1/system/healthz | 不需要 | 返回 db、redis、doc_engine、storage 和总 status。建议反映到本项目 /api/health。 |

### 3.2 知识库管理

| 用途 | 方法与路径 | 关键字段 |
|---|---|---|
| 创建知识库 | POST /api/v1/datasets | name 必填；可设 description、embedding_model、permission、chunk_method、parser_config |
| 列出知识库 | GET /api/v1/datasets | page、page_size、name、id、include_parsing_status |
| 更新知识库 | PUT /api/v1/datasets/{dataset_id} | 更新名称、描述和解析/检索配置 |
| 删除知识库 | DELETE /api/v1/datasets | 高风险；仅管理后台使用 |

创建知识库时有两种互斥模式：

- 内置分块：传 chunk_method，可同时传 parser_config；
- 摄取管道：同时传 parse_type 与 pipeline_id。

两者不能混用。未指定时默认 chunk_method 为 naive。内置分块可选 naive、manual、qa、table、laws、book、paper、presentation、picture、one、email、tag。

建议按用途拆分知识库：

| 知识库 | 内容 | 用途 |
|---|---|---|
| spring-standards | 国标、行标、客户标准、版本变更 | 标准化、公差、术语 |
| spring-process | 材料、热处理、表面处理、产线能力、检验规范 | 合理性与工艺风险 |
| spring-approved-cases | 已人工确认的参数包、异常处置案例 | 相似件辅助，不代替标准 |

### 3.3 文档摄取与解析

| 用途 | 方法与路径 | 说明 |
|---|---|---|
| 上传文档 | POST /api/v1/datasets/{dataset_id}/documents | type=local（默认）上传文件；也支持 type=web 抓取 URL、type=empty 创建空文档 |
| 更新文档 | PUT /api/v1/datasets/{dataset_id}/documents/{document_id} | 在解析前配置 meta_fields、chunk_method、parser_config |
| 查询文档/进度 | GET /api/v1/datasets/{dataset_id}/documents | 支持分页、run、名称、时间、后缀和元数据过滤 |
| 触发解析 | POST /api/v1/datasets/{dataset_id}/chunks | Body: document_ids |
| 停止解析 | DELETE /api/v1/datasets/{dataset_id}/chunks | Body: document_ids |
| 下载原文 | GET /api/v1/datasets/{dataset_id}/documents/{document_id} | 审计或核对原资料 |
| 删除文档 | DELETE /api/v1/datasets/{dataset_id}/documents | 高风险管理操作 |

上传只代表文档已经创建，不代表可检索。触发解析后必须轮询文档列表，确认对应文档解析完成，才可用于生产问答。

上传示例：

~~~
curl --request POST \
  --url "$RAGFLOW_BASE_URL/api/v1/datasets/$DATASET_ID/documents" \
  --header "Authorization: Bearer $RAGFLOW_API_KEY" \
  --form "file=@./GB_T_1239_2_2009.pdf"
~~~

### 3.4 Chunk 与元数据

| 用途 | 方法与路径 | 说明 |
|---|---|---|
| 添加人工块 | POST /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks | content、important_keywords、questions、tag_kwd、image_base64 |
| 查询块 | GET /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks | 人工核验切片质量 |
| 获取/更新/删除单块 | GET/PATCH/DELETE /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id} | 修正或下线错误知识 |
| 批量切换块可用性 | PATCH /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks | chunk_ids + available 或 available_int |
| 元数据汇总 | GET /api/v1/datasets/{dataset_id}/metadata/summary | 检查可筛选元数据 |
| 批量修改元数据 | POST /api/v1/datasets/{dataset_id}/metadata/update | selector 选择文档，updates/deletes 批量处理 |

标准表格、公式、单位和版本边界是高风险内容。建议使用人工块或至少人工抽检；发现过期/错误内容时将相关块设为不可用，不能只依靠提示词规避。

## 4. 两种检索与对话模式

### 4.1 独立检索 API：生产自动化首选

~~~
当前 review JSON
  -> 后端构造问题和元数据筛选
  -> POST /api/v1/retrieval
  -> 保存命中 Chunk 与引用
  -> 项目自身 LLM 生成结构化建议
  -> Schema、引用、置信度校验
~~~

接口：POST /api/v1/retrieval。

| 字段 | 要求 | 说明 |
|---|---:|---|
| question | 必填 | 由弹簧类型、参数、用户意图组成 |
| dataset_ids 或 document_ids | 至少一项 | 两者不能同时缺失 |
| similarity_threshold | 可选 | 最低相似度，官方默认 0.2 |
| vector_similarity_weight | 可选 | 向量权重，官方默认 0.3；其余为词项权重 |
| top_k | 可选 | 向量候选数，官方默认 1024 |
| rerank_id | 可选 | 重排序模型 |
| keyword | 可选 | 型号、标准号、材料牌号建议启用 |
| highlight | 可选 | 返回关键词高亮 |
| metadata_condition | 可选 | 限定弹簧类型、版本、状态、资料级别 |
| use_kg / toc_enhance | 可选 | 已构建知识图谱/目录增强时使用 |

压簧检索示例：

~~~json
{
  "question": "压缩弹簧，材料 SUS304，线径 1.5 mm，外径 12 mm，自由长度 35 mm，总圈数 8。图纸未标注精度等级。请检索适用标准、默认精度建议及外径和自由长度的公差依据。",
  "dataset_ids": [
    "<RAGFLOW_STANDARDS_DATASET_ID>",
    "<RAGFLOW_PROCESS_DATASET_ID>"
  ],
  "similarity_threshold": 0.35,
  "vector_similarity_weight": 0.45,
  "top_k": 30,
  "keyword": true,
  "highlight": true,
  "metadata_condition": {
    "logic": "and",
    "conditions": [
      {
        "name": "spring_type",
        "comparison_operator": "is",
        "value": "compression_spring"
      },
      {
        "name": "status",
        "comparison_operator": "is",
        "value": "active"
      }
    ]
  }
}
~~~

拉簧、扭簧、异形簧只需改变 spring_type、字段摘要和问题模板；业务知识来自新知识库，无需增加一套 Python 弹簧规则。

### 4.2 RAGFlow 托管 Chat Assistant

| 用途 | 方法与路径 |
|---|---|
| 创建助手 | POST /api/v1/chats |
| 查询助手 | GET /api/v1/chats 或 GET /api/v1/chats/{chat_id} |
| 创建会话 | POST /api/v1/chats/{chat_id}/sessions |
| 聊天 | POST /api/v1/chat/completions |
| OpenAI 兼容聊天 | POST /api/v1/openai/{chat_id}/chat/completions |

创建助手可配置 dataset_ids、llm_id、llm_setting、prompt_config、similarity_threshold、vector_similarity_weight、top_n、rerank_id。prompt_config.system 可使用保留变量 {knowledge}，prompt_config.quote 用于展示来源。

POST /api/v1/chat/completions 的模式：

1. 不传 chat_id：使用租户默认模型；
2. 传 chat_id 不传 session_id：使用助手并创建会话；
3. chat_id 与 session_id 均传：延续会话。

~~~
{
  "chat_id": "<RAGFLOW_STANDARDIZATION_CHAT_ID>",
  "session_id": "<OPTIONAL_SESSION_ID>",
  "stream": false,
  "question": "请依据知识库判断该弹簧的外径公差建议，并列出引用来源。"
}
~~~

流式模式是 SSE，最终响应中才可能包含完整引用。OpenAI 兼容端点使用 messages/stream 结构，支持 extra_body.reference、reference_metadata 和 metadata_condition。

## 5. AI Design Review 的推荐实现

自动标准化与合理性判断应采用“检索与生成解耦”，即使用独立检索 API，而不是将 RAGFlow 的自然语言聊天回答直接写回参数。

| 比较项 | 独立检索 + 项目 LLM（推荐） | RAGFlow 托管聊天 |
|---|---|---|
| 当前 review JSON | 可以完整传入 | 需转为会话文本 |
| 结构化 JSON | 复用既有 Schema 校验 | 需额外约束和解析 |
| 审计 | 可保存每次检索与字段映射 | 要解析聊天引用 |
| 适用场景 | 自动建议、合理性、参数包 | 工程师知识问答 |

后端接入点：

~~~
POST /api/reviews/{job_id}/standardize
POST /api/reviews/{job_id}/standardization-chat
POST /api/reviews/reasonableness
~~~

建议增加统一的 ragflow_client 适配层：

~~~
health()                 -> GET  /api/v1/system/healthz
retrieve(question, ...)  -> POST /api/v1/retrieval
create_dataset(...)      -> POST /api/v1/datasets
upload_document(...)     -> POST /api/v1/datasets/{id}/documents
parse_documents(...)     -> POST /api/v1/datasets/{id}/chunks
~~~

业务模块只消费归一化引用，不能散落鉴权和 HTTP 异常处理。

建议将下列结构附加到 review 或每个建议中：

~~~json
{
  "rag_references": [
    {
      "dataset_id": "…",
      "document_id": "…",
      "document_name": "GB_T_1239_2_2009.pdf",
      "chunk_id": "…",
      "content": "相关原文的安全截断",
      "similarity": 0.82,
      "vector_similarity": 0.87,
      "term_similarity": 0.74,
      "metadata": {
        "standard_no": "GB/T 1239.2-2009",
        "status": "active"
      }
    }
  ]
}
~~~

每个标准化建议、合理性风险和人工确认项必须关联至少一个 rag_references 条目。

## 6. 知识元数据规范

| 字段 | 示例 | 作用 |
|---|---|---|
| spring_type | compression_spring | 最关键的知识隔离 |
| spring_family | cold_coiled_cylindrical | 细分结构 |
| document_kind | standard / process / approved_case | 资料优先级 |
| standard_no / standard_version | GB/T 1239.2-2009 / 2009 | 版本追溯 |
| material | SUS304 | 材料匹配 |
| manufacturing_method | cold_coiled | 工艺匹配 |
| status | active / superseded / draft | 排除失效资料 |
| authority | national_standard / company_approved | 证据等级 |
| effective_from / effective_to | ISO 日期 | 生效区间 |
| source_doc_id / revision | 文控编号 / 版次 | 审计 |
| confidentiality | internal / restricted | 访问控制 |

已确认案例必须以 case_status 区分：approved 可辅助；rejected 与 superseded 默认不可检索。案例永远是经验辅助，不得伪装为标准条文。

## 7. 上线检查清单

- [ ] GET /api/v1/system/healthz 的全部依赖为 ok；
- [ ] API Key 仅在后端保存；
- [ ] 标准、工艺、已确认案例知识库已分开；
- [ ] 生产资料已设置 spring_type、status、版本和来源元数据；
- [ ] 关键公式/表格 Chunk 已人工抽检；
- [ ] 查询强制过滤 spring_type 和 status=active；
- [ ] 每次结果保存 Chunk 引用、相似度和检索时间；
- [ ] 无命中、低相似度、引用冲突或 Schema 失败时均转人工确认；
- [ ] 新代码未调用任何已弃用路径；
- [ ] RAGFlow 不可用时，系统明确降级，不能把“未检索到”误判为“参数合理”。

## 8. 第一阶段落地顺序

1. 建立 spring-standards，导入压簧标准并完善元数据；
2. 用 POST /api/v1/retrieval 跑通“当前压簧参数 -> 标准 Chunk 与引用”；
3. 后端封装 ragflow_client，并将健康状态写入 /api/health；
4. 标准化接口先展示 RAG 建议与引用，不自动改字段；
5. 接入合理性诊断，输出风险、建议和引用；
6. 审计、人工确认和失败降级验证后，再扩展到拉簧、扭簧、异形簧。

## 9. 官方全量 HTTP API 分类索引

前文是本项目的落地指南。本节补齐官方 HTTP API 参考页当前目录中的全部能力分类，便于评估而不需要反复翻页。对“当前不进入弹簧审查主链”的能力仍保留索引，但明确标记其适用边界。

### 9.1 全量目录与本项目适用性

| 官方分类 | 官方能力 | 当前建议 | 说明 |
|---|---|---|---|
| 错误代码与弃用别名 | HTTP/业务错误、兼容迁移路径 | 必须遵循 | 所有客户端的通用约定 |
| OpenAI 兼容 API | Chat Assistant、Agent 的 OpenAI 风格 completions | 可选 | 适合复用现有 OpenAI 客户端 |
| 数据集管理 | Dataset CRUD、GraphRAG、RAPTOR | 核心 + 可选增强 | Dataset CRUD 是核心；GraphRAG/RAPTOR 先评估质量和成本 |
| 数据集内文件管理 | 上传、更新、下载、列出、删除、解析、停止解析 | 核心 | 知识摄取主链 |
| 数据集内块管理 | Chunk CRUD、可用性、元数据、检索 | 核心 | 知识质量与审计主链 |
| 聊天助手管理 | Chat Assistant CRUD | 可选 | 工程师知识问答，不直接自动改参 |
| 会话管理 | Chat/Agent 会话、对话、反馈、语音、导图、推荐问题 | 可选 | 仅在使用 RAGFlow 托管交互时接入 |
| 智能体管理 | Agent CRUD、Canvas DSL | 后续评估 | 不作为第一阶段 RAG 检索依赖 |
| 记忆管理 | Memory CRUD 与消息记忆检索 | 暂不接入 | 与图纸审查的可审计知识库不同 |
| 系统 | 健康检查 | 核心 | 部署健康与降级判断 |
| 文件管理 | 平台文件夹、文件、附件转换 | 可选 | 需要统一管理资料目录时使用 |
| 搜索应用管理 | Search App CRUD 与流式搜索补全 | 可选 | 适合独立知识搜索页 |

### 9.2 OpenAI 兼容 API

| 能力 | 方法与路径 | 备注 |
|---|---|---|
| Chat Assistant 补全 | POST /api/v1/openai/{chat_id}/chat/completions | messages、stream；可用 extra_body.reference、reference_metadata、metadata_condition |
| Agent 补全 | POST /api/v1/agents_openai/{agent_id}/chat/completions | OpenAI 风格 Agent 调用 |

用途是兼容客户端，不代表可以跳过本项目自己的字段 Schema、引用保存和人工确认。

### 9.3 数据集扩展能力：知识图谱与 RAPTOR

| 能力 | 方法与路径 | 何时使用 |
|---|---|---|
| 获取知识图谱 | GET /api/v1/datasets/{dataset_id}/knowledge_graph | 可视化或验证已构建图谱 |
| 删除知识图谱 | DELETE /api/v1/datasets/{dataset_id}/knowledge_graph | 高风险管理操作 |
| 启动 GraphRAG 构建 | POST /api/v1/datasets/{dataset_id}/run_graphrag | 需要跨章节、多跳关系推理时 |
| 查询 GraphRAG 状态 | GET /api/v1/datasets/{dataset_id}/trace_graphrag | 轮询异步构建任务 |
| 启动 RAPTOR 构建 | POST /api/v1/datasets/{dataset_id}/run_raptor | 需要长文档层级摘要检索时 |
| 查询 RAPTOR 状态 | GET /api/v1/datasets/{dataset_id}/trace_raptor | 轮询异步构建任务 |

对于技术标准中的精确数值、公差和公式，第一阶段不要用 RAPTOR 摘要替代原始 Chunk 引用。它更适合长篇规范的概览与定位；最终结论仍要回到原始条文或已审校块。

### 9.4 完整文档与 Chunk 管理索引

#### 数据集内文档

| 能力 | 方法与路径 |
|---|---|
| 上传本地文件、网页或空文档 | POST /api/v1/datasets/{dataset_id}/documents |
| 更新文档配置与 meta_fields | PUT /api/v1/datasets/{dataset_id}/documents/{document_id} |
| 下载文档 | GET /api/v1/datasets/{dataset_id}/documents/{document_id} |
| 列出文档 | GET /api/v1/datasets/{dataset_id}/documents |
| 删除文档 | DELETE /api/v1/datasets/{dataset_id}/documents |
| 解析文档 | POST /api/v1/datasets/{dataset_id}/chunks |
| 停止解析文档 | DELETE /api/v1/datasets/{dataset_id}/chunks |

#### 数据集内 Chunk

| 能力 | 方法与路径 |
|---|---|
| 添加 Chunk | POST /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks |
| 列出 Chunk | GET /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks |
| 获取单个 Chunk | GET /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id} |
| 删除 Chunk | DELETE /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks |
| 更新单个 Chunk | PATCH /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id} |
| 批量更新 Chunk 可用性 | PATCH /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks |
| 汇总文档元数据 | GET /api/v1/datasets/{dataset_id}/metadata/summary |
| 批量更新或删除元数据 | POST /api/v1/datasets/{dataset_id}/metadata/update |
| 独立检索 Chunk | POST /api/v1/retrieval |

### 9.5 Chat Assistant 与会话管理索引

#### Chat Assistant

| 能力 | 方法与路径 |
|---|---|
| 创建 | POST /api/v1/chats |
| 更新 | PUT /api/v1/chats/{chat_id} |
| 获取 | GET /api/v1/chats/{chat_id} |
| 部分更新 | PATCH /api/v1/chats/{chat_id} |
| 删除单个/批量 | DELETE /api/v1/chats/{chat_id} 或 DELETE /api/v1/chats |
| 列表 | GET /api/v1/chats |

#### Chat 会话与交互

| 能力 | 方法与路径或能力名 | 备注 |
|---|---|---|
| 创建会话 | POST /api/v1/chats/{chat_id}/sessions | 可带 name、user_id |
| 更新会话 | PATCH /api/v1/chats/{chat_id}/sessions/{session_id} | 不使用旧 PUT |
| 列出/获取会话 | GET /api/v1/chats/{chat_id}/sessions | 也支持按会话 ID 获取 |
| 删除会话消息 | 会话消息删除接口 | 用于会话历史维护 |
| 提交消息反馈 | 会话消息反馈接口 | 可记录点赞/问题反馈 |
| 删除会话 | DELETE /api/v1/chats/{chat_id}/sessions | ids 或 delete_all |
| 与 Chat Assistant 对话 | POST /api/v1/chat/completions | 支持 chat_id、session_id、messages/question、stream |
| 生成相关问题 | POST /api/v1/chat/recommandation | 知识问答体验增强，不参与业务判断 |

官方会话目录还包含“与 Agent 创建会话、与 Agent 对话、列出/删除 Agent 会话、文本转语音、语音转文本、生成思维导图”。这些可用于独立助手产品，但不应进入第一阶段参数标准化主链。

### 9.6 Agent 管理与 Agent 对话

| 能力 | 方法与路径 | 备注 |
|---|---|---|
| 列出 Agent | GET /api/v1/agents | 可按分页、名称或 ID 过滤 |
| 创建 Agent | POST /api/v1/agents | 需要 title 与 Canvas DSL |
| 更新 Agent | PUT /api/v1/agents/{agent_id} | 可修改 title、description、dsl |
| 删除 Agent | DELETE /api/v1/agents/{agent_id} | 高风险管理操作 |
| 与 Agent 对话 | POST /api/v1/agents/chat/completions | 可返回 trace；可带 openai-compatible=true |
| Agent OpenAI 兼容对话 | POST /api/v1/agents_openai/{agent_id}/chat/completions | 适合 OpenAI SDK 接入 |

Agent 适合将检索、工具和多步操作编排为 RAGFlow Canvas。当前项目先采用明确的“检索 API -> 自身 LLM -> Schema 校验”路径；若后续要把知识问答、图纸辅助或工具链编排完全迁至 RAGFlow，再单独评估 Agent DSL。

### 9.7 Memory 管理索引

| 能力 | 方法与路径或资源 |
|---|---|
| 创建记忆 | POST /api/v1/memories |
| 更新记忆 | PUT /api/v1/memories/{memory_id} |
| 列出记忆 | GET /api/v1/memories |
| 获取记忆配置 | GET /api/v1/memories/{memory_id}/config |
| 删除记忆 | /api/v1/memories/{memory_id} |
| 列出记忆消息 | messages 资源的列表接口 |
| 添加消息 | messages 资源的写入接口 |
| 遗忘消息 | messages 资源的遗忘接口 |
| 更新消息状态 | messages 资源的状态接口 |
| 搜索消息 | GET /api/v1/messages/search |
| 获取最近消息/消息内容 | messages 资源的读取接口 |

Memory 的 raw、semantic、episodic、procedural 类型服务于对话长期记忆。它和“标准、工艺、受控案例”知识库的版本治理目标不同，因此第一阶段不作为标准化或合理性证据源。

### 9.8 文件与搜索应用管理索引

#### 文件管理

| 能力 | 方法与路径 |
|---|---|
| 上传文件 | POST /api/v1/files（multipart/form-data） |
| 上传运行时附件文档 | POST /v1/document/upload_info |
| 创建文件夹或虚拟文件 | POST /api/v1/files（application/json） |
| 列出文件 | GET /api/v1/files |
| 获取父目录 | GET /api/v1/files/{file_id}/parent |
| 获取所有祖先目录 | GET /api/v1/files/{file_id}/ancestors |
| 删除文件 | DELETE /api/v1/files |
| 下载文件 | GET /api/v1/files/{file_id} |
| 移动或重命名 | POST /api/v1/files/move |
| 链接到数据集并转换为文档 | POST /api/v1/files/link-to-datasets |

第一阶段可直接使用“数据集内文档上传”接口；当需要 RAGFlow 内的资料目录、复用附件或统一文件权限时，再启用文件管理链路。

#### 搜索应用

| 能力 | 方法与路径 |
|---|---|
| 创建搜索应用 | POST /api/v1/searches |
| 列出搜索应用 | GET /api/v1/searches |
| 获取搜索应用 | GET /api/v1/searches/{search_id} |
| 更新搜索应用 | PUT /api/v1/searches/{search_id} |
| 删除搜索应用 | DELETE /api/v1/searches/{search_id} |
| 流式搜索补全 | POST /api/v1/searches/{search_id}/completions |

搜索应用的 completions 返回 SSE 答案和引用；官方参考对此接口的示例使用登录令牌而非 API Key。它适合后续提供独立“弹簧知识搜索”页面，不应直接绕过图纸审查流程。

### 9.9 目录覆盖结论

现在本文已覆盖官方参考页中的错误/弃用、OpenAI 兼容、数据集、知识图谱、RAPTOR、文档、Chunk、元数据、独立检索、Chat Assistant、会话、Agent、Memory、系统、文件和搜索应用全部分类。

为避免复制一份会迅速过期的上万行官方文档，本文对当前项目核心链路保留了关键字段、示例和落地约束；对暂不接入的高级能力保留完整分类与路径索引，并以官方参考页作为参数级权威来源。
