# 知识库系统完整实现指南

本文档详细描述如何从零实现一个完整的知识库系统，包括 Web 端和 Server 端的实现，覆盖从创建知识库、添加文件、到与 LLM 对话时调用知识库的完整流程。

---

## 目录

1. [系统架构概述](#1-系统架构概述)
2. [数据模型设计](#2-数据模型设计)
3. [Server 端实现](#3-server-端实现)
4. [Web 端实现](#4-web-端实现)
5. [完整流程详解](#5-完整流程详解)
6. [核心代码示例](#6-核心代码示例)
7. [配置说明](#7-配置说明)

---

## 1. 系统架构概述

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Web 前端                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ 知识库管理   │  │ 文件上传    │  │ 聊天界面    │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP/WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Server 后端                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ API 路由    │  │ 文件处理    │  │ RAG 检索    │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ 数据模型    │  │ 向量数据库   │  │ Embedding   │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      外部服务/存储                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ 向量数据库   │  │ 文件存储    │  │ LLM API     │              │
│  │ (Chroma等)  │  │ (本地/S3)   │  │ (Ollama等)  │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 核心组件

| 组件 | 功能 | 技术选型 |
|------|------|----------|
| 知识库管理 | 创建、编辑、删除知识库 | FastAPI + SQLAlchemy |
| 文件处理 | 解析文档、文本分块 | LangChain Loader |
| 向量化 | 生成文本嵌入向量 | Sentence Transformers / OpenAI API |
| 向量数据库 | 存储和检索向量 | Chroma / Milvus / Qdrant |
| RAG 检索 | 相似度搜索、混合检索 | LangChain Retriever |
| 聊天集成 | 将检索结果注入提示词 | 自定义 Middleware |

---

## 2. 数据模型设计

### 2.1 知识库表 (Knowledge)

```python
# models/knowledge.py

from sqlalchemy import Column, Text, BigInteger, JSON
from sqlalchemy.orm import Base

class Knowledge(Base):
    """知识库元数据表"""
    __tablename__ = 'knowledge'
    
    id = Column(Text, primary_key=True, unique=True)  # 知识库唯一ID
    user_id = Column(Text)                            # 创建者ID
    name = Column(Text)                               # 知识库名称
    description = Column(Text)                        # 知识库描述
    meta = Column(JSON, nullable=True)                # 扩展元数据
    created_at = Column(BigInteger)                   # 创建时间戳
    updated_at = Column(BigInteger)                   # 更新时间戳
```

### 2.2 知识库-文件关联表 (KnowledgeFile)

```python
class KnowledgeFile(Base):
    """知识库与文件的关联表"""
    __tablename__ = 'knowledge_file'
    
    id = Column(Text, primary_key=True, unique=True)
    knowledge_id = Column(Text, ForeignKey('knowledge.id', ondelete='CASCADE'))
    file_id = Column(Text, ForeignKey('file.id', ondelete='CASCADE'))
    user_id = Column(Text)                            # 上传者ID
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
```

### 2.3 文件表 (File)

```python
class File(Base):
    """文件元数据表"""
    __tablename__ = 'file'
    
    id = Column(Text, primary_key=True, unique=True)
    user_id = Column(Text)
    filename = Column(Text)                           # 文件名
    path = Column(Text)                               # 文件存储路径
    meta = Column(JSON)                               # 文件元信息（MIME类型等）
    data = Column(JSON)                               # 文件处理后的数据
    hash = Column(Text)                               # 内容哈希（用于去重）
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
```

### 2.4 向量数据库结构

每个知识库对应一个 Collection（集合），Collection 名称使用知识库 ID：

```
Collection: {knowledge_id}
├── id: 向量唯一ID (UUID)
├── vector: 嵌入向量 (float[])
├── text: 文本内容
└── metadata: {
    │   file_id: 文件ID
    │   name: 文件名
    │   source: 来源
    │   chunk_index: 分块索引
    │   embedding_config: 嵌入配置
    }
```

---

## 3. Server 端实现

### 3.1 API 路由设计

```python
# routers/knowledge.py

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix='/api/v1/knowledge', tags=['knowledge'])

# ==================== 数据模型 ====================

class KnowledgeForm(BaseModel):
    """创建/更新知识库表单"""
    name: str
    description: str
    access_grants: Optional[list[dict]] = None  # 访问权限配置

class KnowledgeFileIdForm(BaseModel):
    """添加文件表单"""
    file_id: str

class KnowledgeResponse(BaseModel):
    """知识库响应"""
    id: str
    name: str
    description: str
    files: Optional[list[dict]] = None
    created_at: int
    updated_at: int

# ==================== API 接口 ====================

@router.post('/create', response_model=KnowledgeResponse)
async def create_knowledge(request: Request, form_data: KnowledgeForm, user=Depends(get_verified_user)):
    """创建新知识库"""
    # 1. 验证用户权限
    if not has_permission(user, 'workspace.knowledge'):
        raise HTTPException(401, '无权限创建知识库')
    
    # 2. 创建知识库记录
    knowledge = Knowledges.insert_new_knowledge(user.id, form_data)
    
    # 3. 为知识库生成嵌入向量（用于知识库搜索）
    await embed_knowledge_base_metadata(request, knowledge.id, knowledge.name, knowledge.description)
    
    return knowledge


@router.get('/list')
async def list_knowledge_bases(user=Depends(get_verified_user)):
    """获取用户可访问的知识库列表"""
    return Knowledges.get_knowledge_bases_by_user_id(user.id)


@router.get('/{id}')
async def get_knowledge_by_id(id: str, user=Depends(get_verified_user)):
    """获取知识库详情"""
    knowledge = Knowledges.get_knowledge_by_id(id)
    if not knowledge:
        raise HTTPException(404, '知识库不存在')
    
    # 权限检查
    if not has_access(user, knowledge, 'read'):
        raise HTTPException(403, '无访问权限')
    
    # 获取关联的文件列表
    files = Knowledges.get_files_by_id(id)
    return KnowledgeResponse(**knowledge.model_dump(), files=files)


@router.post('/{id}/file/add')
async def add_file_to_knowledge(id: str, form_data: KnowledgeFileIdForm, request: Request, user=Depends(get_verified_user)):
    """添加文件到知识库"""
    knowledge = Knowledges.get_knowledge_by_id(id)
    if not knowledge:
        raise HTTPException(404, '知识库不存在')
    
    # 权限检查
    if not has_access(user, knowledge, 'write'):
        raise HTTPException(403, '无写入权限')
    
    file = Files.get_file_by_id(form_data.file_id)
    if not file:
        raise HTTPException(404, '文件不存在')
    
    # 处理文件：解析内容、分块、向量化、存入向量数据库
    process_file(request, ProcessFileForm(file_id=file.id, collection_name=id), user=user)
    
    # 添加文件关联记录
    Knowledges.add_file_to_knowledge_by_id(knowledge_id=id, file_id=file.id, user_id=user.id)
    
    return {'status': True, 'message': '文件添加成功'}


@router.delete('/{id}')
async def delete_knowledge(id: str, user=Depends(get_verified_user)):
    """删除知识库"""
    knowledge = Knowledges.get_knowledge_by_id(id)
    if not knowledge:
        raise HTTPException(404, '知识库不存在')
    
    if knowledge.user_id != user.id and user.role != 'admin':
        raise HTTPException(403, '无删除权限')
    
    # 删除向量数据库中的 Collection
    VECTOR_DB_CLIENT.delete_collection(collection_name=id)
    
    # 删除知识库记录
    Knowledges.delete_knowledge_by_id(id)
    
    return {'status': True}
```

### 3.2 文件处理核心逻辑

```python
# routers/retrieval.py

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

class ProcessFileForm(BaseModel):
    file_id: str
    content: Optional[str] = None      # 可选：直接提供内容
    collection_name: Optional[str] = None  # 目标 Collection（知识库ID）

@router.post('/process/file')
def process_file(request: Request, form_data: ProcessFileForm, user=Depends(get_verified_user)):
    """
    处理文件并存入向量数据库
    流程：加载文件 → 文本分块 → 生成嵌入 → 存入向量数据库
    """
    file = Files.get_file_by_id(form_data.file_id)
    if not file:
        raise HTTPException(404, '文件不存在')
    
    collection_name = form_data.collection_name or f'file-{file.id}'
    
    # ========== Step 1: 加载文件内容 ==========
    if form_data.content:
        # 直接使用提供的内容
        docs = [Document(page_content=form_data.content, metadata={'file_id': file.id, 'name': file.filename})]
    else:
        # 使用 Loader 加载文件
        loader = Loader(
            engine=request.app.state.config.CONTENT_EXTRACTION_ENGINE,
            # ... 其他配置
        )
        docs = loader.load(file.filename, file.meta.get('content_type'), file.path)
        
        # 添加元数据
        docs = [
            Document(
                page_content=doc.page_content,
                metadata={**doc.metadata, 'file_id': file.id, 'name': file.filename, 'source': file.filename}
            )
            for doc in docs
        ]
    
    # ========== Step 2: 文本分块 ==========
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=request.app.state.config.CHUNK_SIZE,        # 默认 1500
        chunk_overlap=request.app.state.config.CHUNK_OVERLAP,  # 默认 100
        add_start_index=True,
    )
    docs = text_splitter.split_documents(docs)
    
    # ========== Step 3: 存入向量数据库 ==========
    result = save_docs_to_vector_db(
        request=request,
        docs=docs,
        collection_name=collection_name,
        metadata={'file_id': file.id, 'name': file.filename},
        user=user,
    )
    
    # 更新文件状态
    Files.update_file_data_by_id(file.id, {'status': 'completed', 'content': ' '.join([d.page_content for d in docs])})
    
    return {'status': True, 'collection_name': collection_name}
```

### 3.3 向量化存储

```python
# routers/retrieval.py

import uuid
import asyncio

def save_docs_to_vector_db(request: Request, docs: list[Document], collection_name: str, metadata: dict = None, user=None) -> bool:
    """
    将文档存入向量数据库
    流程：文本预处理 → 生成嵌入向量 → 存入向量数据库
    """
    # 文本预处理
    texts = [doc.page_content for doc in docs]
    metadatas = [
        {**doc.metadata, **(metadata or {}), 'embedding_config': {
            'engine': request.app.state.config.RAG_EMBEDDING_ENGINE,
            'model': request.app.state.config.RAG_EMBEDDING_MODEL,
        }}
        for doc in docs
    ]
    
    # 检查 Collection 是否存在
    if VECTOR_DB_CLIENT.has_collection(collection_name):
        # 如果是添加模式，保留现有数据
        pass
    else:
        # 创建新 Collection
        VECTOR_DB_CLIENT.create_collection(collection_name)
    
    # ========== 生成嵌入向量 ==========
    embedding_function = get_embedding_function(
        engine=request.app.state.config.RAG_EMBEDDING_ENGINE,
        model=request.app.state.config.RAG_EMBEDDING_MODEL,
        # ... 其他配置
    )
    
    # 异步生成嵌入
    embeddings = asyncio.run(
        embedding_function(texts, prefix=RAG_EMBEDDING_CONTENT_PREFIX, user=user)
    )
    
    # ========== 构建向量项 ==========
    items = [
        {
            'id': str(uuid.uuid4()),
            'text': text,
            'vector': embeddings[idx],
            'metadata': metadatas[idx],
        }
        for idx, text in enumerate(texts)
    ]
    
    # ========== 存入向量数据库 ==========
    VECTOR_DB_CLIENT.insert(collection_name=collection_name, items=items)
    
    log.info(f'Added {len(items)} items to collection {collection_name}')
    return True
```

### 3.4 知识库检索

```python
# retrieval/utils.py

from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever

async def query_collection(request, collection_names: list[str], queries: list[str], embedding_function, k: int) -> dict:
    """
    从多个 Collection 中检索相关文档
    支持：纯向量检索、混合检索（向量+BM25）、重排序
    """
    results = []
    
    # ========== 检查是否启用混合检索 ==========
    if request.app.state.config.ENABLE_RAG_HYBRID_SEARCH:
        return await query_collection_with_hybrid_search(
            collection_names=collection_names,
            queries=queries,
            embedding_function=embedding_function,
            k=k,
            reranking_function=request.app.state.RERANKING_FUNCTION,
            k_reranker=request.app.state.config.TOP_K_RERANKER,
            r=request.app.state.config.RELEVANCE_THRESHOLD,
            hybrid_bm25_weight=request.app.state.config.HYBRID_BM25_WEIGHT,
        )
    
    # ========== 纯向量检索 ==========
    # 生成查询向量
    query_embeddings = await embedding_function(queries, prefix=RAG_EMBEDDING_QUERY_PREFIX)
    
    for query_embedding in query_embeddings:
        for collection_name in collection_names:
            # 向量相似度搜索
            result = VECTOR_DB_CLIENT.search(
                collection_name=collection_name,
                vectors=[query_embedding],
                limit=k,
            )
            if result:
                results.append(result.model_dump())
    
    # 合并并排序结果
    return merge_and_sort_query_results(results, k=k)


async def query_collection_with_hybrid_search(collection_names, queries, embedding_function, k, reranking_function, k_reranker, r, hybrid_bm25_weight) -> dict:
    """
    混合检索：向量检索 + BM25 关键词检索 + 重排序
    """
    results = []
    
    for collection_name in collection_names:
        # 获取 Collection 中的所有数据
        collection_result = VECTOR_DB_CLIENT.get(collection_name=collection_name)
        
        for query in queries:
            # ========== BM25 检索器 ==========
            bm25_retriever = BM25Retriever.from_texts(
                texts=collection_result.documents[0],
                metadatas=collection_result.metadatas[0],
            )
            bm25_retriever.k = k
            
            # ========== 向量检索器 ==========
            vector_retriever = VectorSearchRetriever(
                collection_name=collection_name,
                embedding_function=embedding_function,
                top_k=k,
            )
            
            # ========== 组合检索器 ==========
            ensemble_retriever = EnsembleRetriever(
                retrievers=[bm25_retriever, vector_retriever],
                weights=[hybrid_bm25_weight, 1.0 - hybrid_bm25_weight],
            )
            
            # ========== 重排序 ==========
            if reranking_function:
                compressor = RerankCompressor(
                    embedding_function=embedding_function,
                    top_n=k_reranker,
                    reranking_function=reranking_function,
                    r_score=r,
                )
                compression_retriever = ContextualCompressionRetriever(
                    base_compressor=compressor,
                    base_retriever=ensemble_retriever,
                )
                result = await compression_retriever.ainvoke(query)
            else:
                result = await ensemble_retriever.ainvoke(query)
            
            results.append({
                'documents': [[d.page_content for d in result]],
                'metadatas': [[d.metadata for d in result]],
                'distances': [[d.metadata.get('score', 0) for d in result]],
            })
    
    return merge_and_sort_query_results(results, k=k)
```

### 3.5 获取知识库内容

```python
# retrieval/utils.py

async def get_sources_from_items(request, items, queries, embedding_function, k, reranking_function, k_reranker, r, hybrid_bm25_weight, hybrid_search, full_context, user) -> list:
    """
    从多个来源（知识库、文件、URL等）获取相关内容
    """
    sources = []
    
    for item in items:
        query_result = None
        collection_names = []
        
        # ========== 处理不同类型的来源 ==========
        if item.get('type') == 'collection':
            # 知识库类型
            knowledge_base = Knowledges.get_knowledge_by_id(item.get('id'))
            
            if knowledge_base and has_access(user, knowledge_base, 'read'):
                if full_context:
                    # 获取全部内容
                    files = Knowledges.get_files_by_id(knowledge_base.id)
                    documents = [file.data.get('content', '') for file in files]
                    query_result = {'documents': [documents], 'metadatas': [[{'file_id': f.id, 'name': f.filename} for f in files]]}
                else:
                    # 检索相关内容
                    collection_names.append(knowledge_base.id)
        
        elif item.get('type') == 'file':
            # 单文件类型
            collection_names.append(f'file-{item["id"]}')
        
        # ========== 执行检索 ==========
        if collection_names:
            query_result = await query_collection(
                request=request,
                collection_names=collection_names,
                queries=queries,
                embedding_function=embedding_function,
                k=k,
            )
        
        # ========== 构建返回结果 ==========
        if query_result:
            sources.append({
                'source': item,
                'document': query_result['documents'][0],
                'metadata': query_result['metadatas'][0],
                'distances': query_result.get('distances', [[]])[0],
            })
    
    return sources
```

---

## 4. Web 端实现

### 4.1 知识库管理页面

```typescript
// frontend/src/lib/services/knowledgeService.ts

export const createKnowledgeBase = async (name: string, description: string) => {
    const response = await fetch('/api/v1/knowledge/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description }),
    });
    return response.json();
};

export const getKnowledgeBases = async () => {
    const response = await fetch('/api/v1/knowledge/list');
    return response.json();
};

export const addFileToKnowledge = async (knowledgeId: string, fileId: string) => {
    const response = await fetch(`/api/v1/knowledge/${knowledgeId}/file/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_id: fileId }),
    });
    return response.json();
};
```

### 4.2 文件上传组件

```typescript
// frontend/src/lib/components/FileUpload.svelte

<script lang="ts">
    import { uploadFile } from '$lib/services/fileService';
    
    let files: File[] = [];
    let uploading = false;
    
    const handleFileSelect = async (event: Event) => {
        const target = event.target as HTMLInputElement;
        files = Array.from(target.files || []);
        
        uploading = true;
        for (const file of files) {
            // 上传文件
            const formData = new FormData();
            formData.append('file', file);
            const result = await uploadFile(formData);
            
            // 如果指定了知识库，添加到知识库
            if (knowledgeId && result.id) {
                await addFileToKnowledge(knowledgeId, result.id);
            }
        }
        uploading = false;
    };
</script>

<template>
    <input type="file" multiple on:change={handleFileSelect} />
    {#if uploading}
        <p>上传中...</p>
    {/if}
</template>
```

### 4.3 聊天界面集成知识库

```typescript
// frontend/src/lib/components/Chat.svelte

<script lang="ts">
    // 聊天时选择的知识库
    let selectedKnowledgeBases: string[] = [];
    
    const sendMessage = async (content: string) => {
        // 构建消息，包含知识库引用
        const message = {
            role: 'user',
            content: content,
            // 附加的知识库信息
            files: selectedKnowledgeBases.map(id => ({
                type: 'collection',
                id: id,
            })),
        };
        
        // 发送到后端
        const response = await fetch('/api/v1/chat/completions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model: selectedModel,
                messages: [message],
                stream: true,
            }),
        });
        
        // 处理流式响应...
    };
</script>

<template>
    <!-- 知识库选择器 -->
    <div class="knowledge-selector">
        {#each knowledgeBases as kb}
            <button on:click={() => selectedKnowledgeBases.push(kb.id)}>
                {kb.name}
            </button>
        {/each}
    </div>
    
    <!-- 聊天输入 -->
    <input on:keydown={(e) => e.key === 'Enter' && sendMessage(inputValue)} />
</template>
```

---

## 5. 完整流程详解

### 5.1 创建知识库流程

```
┌──────────────────────────────────────────────────────────────────┐
│                    创建知识库完整流程                              │
└──────────────────────────────────────────────────────────────────┘

用户操作                    前端                      后端
   │                         │                         │
   │  输入名称、描述          │                         │
   │─────────────────────────>│                         │
   │                         │  POST /knowledge/create │
   │                         │─────────────────────────>│
   │                         │                         │  1. 验证用户权限
   │                         │                         │  2. 创建 Knowledge 记录
   │                         │                         │     (id=UUID, user_id, name, description)
   │                         │                         │  3. 生成知识库嵌入向量
   │                         │                         │     (用于知识库语义搜索)
   │                         │                         │  4. 存入 knowledge-bases Collection
   │                         │                         │
   │                         │  返回 KnowledgeResponse │
   │                         │<─────────────────────────│
   │  显示创建成功            │                         │
   │<─────────────────────────│                         │
```

### 5.2 添加文件到知识库流程

```
┌──────────────────────────────────────────────────────────────────┐
│                    添加文件完整流程                                │
└──────────────────────────────────────────────────────────────────┘

用户操作                    前端                      后端
   │                         │                         │
   │  选择文件                │                         │
   │─────────────────────────>│                         │
   │                         │  POST /files/upload     │
   │                         │─────────────────────────>│
   │                         │                         │  1. 保存文件到存储
   │                         │                         │  2. 创建 File 记录
   │                         │                         │     (id, filename, path, meta)
   │                         │  返回 file_id           │
   │                         │<─────────────────────────│
   │                         │                         │
   │  选择知识库添加          │                         │
   │─────────────────────────>│                         │
   │                         │  POST /knowledge/{id}/file/add
   │                         │─────────────────────────>│
   │                         │                         │
   │                         │                         │  ┌─────────────────────┐
   │                         │                         │  │ process_file() 流程 │
   │                         │                         │  └─────────────────────┘
   │                         │                         │  1. 加载文件内容
   │                         │                         │     - PDF: PyPDFLoader
   │                         │                         │     - Word: Docx2txtLoader
   │                         │                         │     - Excel: ExcelLoader
   │                         │                         │     - 文本: TextLoader
   │                         │                         │
   │                         │                         │  2. 文本分块
   │                         │                         │     - RecursiveCharacterTextSplitter
   │                         │                         │     - chunk_size=1500, overlap=100
   │                         │                         │
   │                         │                         │  3. 生成嵌入向量
   │                         │                         │     - 本地: SentenceTransformer
   │                         │                         │     - API: OpenAI/Ollama embeddings
   │                         │                         │
   │                         │                         │  4. 存入向量数据库
   │                         │                         │     - Collection: {knowledge_id}
   │                         │                         │     - items: [{id, text, vector, metadata}]
   │                         │                         │
   │                         │                         │  5. 创建 KnowledgeFile 关联
   │                         │                         │
   │                         │  返回成功               │
   │                         │<─────────────────────────│
   │  显示添加成功            │                         │
   │<─────────────────────────│                         │
```

### 5.3 与 LLM 对话调用知识库流程

```
┌──────────────────────────────────────────────────────────────────┐
│                    RAG 对话完整流程                                │
└──────────────────────────────────────────────────────────────────┘

用户操作                    前端                      后端
   │                         │                         │
   │  选择知识库              │                         │
   │─────────────────────────>│                         │
   │                         │  记录 selectedKBs       │
   │                         │                         │
   │  输入问题                │                         │
   │─────────────────────────>│                         │
   │                         │  POST /chat/completions │
   │                         │  body: {                │
   │                         │    model,               │
   │                         │    messages: [{         │
   │                         │      role: 'user',      │
   │                         │      content: '问题',   │
   │                         │      files: [{          │
   │                         │        type: 'collection',│
   │                         │        id: 'kb-xxx'     │
   │                         │      }]                 │
   │                         │    }]                   │
   │                         │  }                      │
   │                         │─────────────────────────>│
   │                         │                         │
   │                         │                         │  ┌─────────────────────┐
   │                         │                         │  │ Middleware 处理流程 │
   │                         │                         │  └─────────────────────┘
   │                         │                         │
   │                         │                         │  1. 检测到 files 字段
   │                         │                         │     包含知识库引用
   │                         │                         │
   │                         │                         │  2. 生成查询向量
   │                         │                         │     - 可选：先用 LLM 生成多个查询
   │                         │                         │     - embedding_function(query)
   │                         │                         │
   │                         │                         │  3. 检索知识库
   │                         │                         │     ┌─────────────────────┐
   │                         │                         │     │ get_sources_from_items │
   │                         │                         │     └─────────────────────┘
   │                         │                         │     - 验证用户访问权限
   │                         │                         │     - query_collection()
   │                         │                         │       - VECTOR_DB_CLIENT.search()
   │                         │                         │       - 或混合检索 + 重排序
   │                         │                         │     - 返回 top_k 个相关文档
   │                         │                         │
   │                         │                         │  4. 构建 RAG 提示词
   │                         │                         │     ┌─────────────────────┐
   │                         │                         │     │ rag_template()      │
   │                         │                         │     └─────────────────────┘
   │                         │                         │     模板格式：
   │                         │                         │     """
   │                         │                         │     使用以下上下文信息回答问题：
   │                         │                         │     
   │                         │                         │     [CONTEXT]
   │                         │                         │     {documents}
   │                         │                         │     
   │                         │                         │     用户问题：{query}
   │                         │                         │     """
   │                         │                         │
   │                         │                         │  5. 注入到系统消息
   │                         │                         │     messages = [
   │                         │                         │       {role: 'system', content: rag_prompt},
   │                         │                         │       {role: 'user', content: query}
   │                         │                         │     ]
   │                         │                         │
   │                         │                         │  6. 调用 LLM API
   │                         │                         │     - Ollama / OpenAI / 其他
   │                         │                         │     - 流式返回响应
   │                         │                         │
   │                         │  SSE 流式响应           │
   │                         │<─────────────────────────│
   │  显示回答 + 引用来源     │                         │
   │<─────────────────────────│                         │
```

---

## 6. 核心代码示例

### 6.1 完整的知识库服务类

```python
# services/knowledge_service.py

import uuid
import time
from typing import Optional, List
from sqlalchemy.orm import Session
from models.knowledge import Knowledge, KnowledgeFile, KnowledgeModel
from retrieval.vector.factory import VECTOR_DB_CLIENT

class KnowledgeService:
    """知识库服务类"""
    
    def create_knowledge(self, user_id: str, name: str, description: str, db: Session) -> KnowledgeModel:
        """创建知识库"""
        knowledge = Knowledge(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=name,
            description=description,
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        db.add(knowledge)
        db.commit()
        db.refresh(knowledge)
        return KnowledgeModel.model_validate(knowledge)
    
    def add_file(self, knowledge_id: str, file_id: str, user_id: str, db: Session) -> bool:
        """添加文件到知识库"""
        # 检查知识库是否存在
        knowledge = db.query(Knowledge).filter_by(id=knowledge_id).first()
        if not knowledge:
            raise ValueError('知识库不存在')
        
        # 检查文件是否已添加
        existing = db.query(KnowledgeFile).filter_by(
            knowledge_id=knowledge_id, file_id=file_id
        ).first()
        if existing:
            raise ValueError('文件已存在于知识库中')
        
        # 创建关联记录
        kf = KnowledgeFile(
            id=str(uuid.uuid4()),
            knowledge_id=knowledge_id,
            file_id=file_id,
            user_id=user_id,
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        db.add(kf)
        
        # 更新知识库时间
        knowledge.updated_at = int(time.time())
        db.commit()
        return True
    
    def get_files(self, knowledge_id: str, db: Session) -> List[dict]:
        """获取知识库中的所有文件"""
        from models.files import File
        
        results = db.query(File).join(
            KnowledgeFile, File.id == KnowledgeFile.file_id
        ).filter(
            KnowledgeFile.knowledge_id == knowledge_id
        ).all()
        
        return [{'id': f.id, 'filename': f.filename, 'meta': f.meta} for f in results]
    
    def delete_knowledge(self, knowledge_id: str, db: Session) -> bool:
        """删除知识库"""
        knowledge = db.query(Knowledge).filter_by(id=knowledge_id).first()
        if not knowledge:
            return False
        
        # 删除向量数据库 Collection
        try:
            VECTOR_DB_CLIENT.delete_collection(collection_name=knowledge_id)
        except Exception as e:
            log.warning(f'删除向量 Collection 失败: {e}')
        
        # 删除关联记录（CASCADE 会自动处理）
        db.delete(knowledge)
        db.commit()
        return True
```

### 6.2 完整的 RAG 检索服务

```python
# services/rag_service.py

import asyncio
from typing import List, Optional
from retrieval.vector.factory import VECTOR_DB_CLIENT
from retrieval.utils import query_collection, get_embedding_function

class RAGService:
    """RAG 检索服务"""
    
    def __init__(self, config):
        self.config = config
        self.embedding_function = get_embedding_function(
            engine=config.RAG_EMBEDDING_ENGINE,
            model=config.RAG_EMBEDDING_MODEL,
            # ...
        )
    
    async def search_knowledge(self, knowledge_ids: List[str], query: str, top_k: int = 5) -> dict:
        """从知识库中检索相关内容"""
        results = await query_collection(
            request=None,  # 或传入 request 对象
            collection_names=knowledge_ids,
            queries=[query],
            embedding_function=self.embedding_function,
            k=top_k,
        )
        return results
    
    async def search_with_hybrid(self, knowledge_ids: List[str], query: str, top_k: int = 5, bm25_weight: float = 0.5) -> dict:
        """混合检索：向量 + BM25"""
        from retrieval.utils import query_collection_with_hybrid_search
        
        results = await query_collection_with_hybrid_search(
            collection_names=knowledge_ids,
            queries=[query],
            embedding_function=self.embedding_function,
            k=top_k,
            reranking_function=None,  # 可选
            k_reranker=top_k * 2,
            r=0.0,
            hybrid_bm25_weight=bm25_weight,
        )
        return results
    
    def build_rag_prompt(self, documents: List[str], query: str, template: str = None) -> str:
        """构建 RAG 提示词"""
        if template is None:
            template = """
使用以下上下文信息回答用户问题。如果上下文中没有相关信息，请说明。

上下文信息：
{context}

用户问题：{query}

请基于上下文信息给出准确、详细的回答：
"""
        
        context = '\n\n---\n\n'.join(documents)
        return template.format(context=context, query=query)
```

### 6.3 聊天中间件集成

```python
# middleware/chat_middleware.py

from fastapi import Request
from services.rag_service import RAGService
from services.knowledge_service import KnowledgeService

async def process_chat_request(request: Request, body: dict, user):
    """处理聊天请求，集成 RAG"""
    
    messages = body.get('messages', [])
    last_message = messages[-1] if messages else {}
    
    # 检查是否有知识库引用
    files = last_message.get('files', [])
    knowledge_ids = [f['id'] for f in files if f.get('type') == 'collection']
    
    if not knowledge_ids:
        return body  # 无知识库引用，直接返回
    
    # ========== RAG 检索 ==========
    query = last_message.get('content', '')
    rag_service = RAGService(request.app.state.config)
    
    # 检索相关内容
    sources = await rag_service.search_knowledge(
        knowledge_ids=knowledge_ids,
        query=query,
        top_k=request.app.state.config.TOP_K,
    )
    
    # 构建上下文
    documents = sources.get('documents', [[]])[0]
    metadatas = sources.get('metadatas', [[]])[0]
    
    # ========== 构建 RAG 提示词 ==========
    rag_prompt = rag_service.build_rag_prompt(
        documents=documents,
        query=query,
        template=request.app.state.config.RAG_TEMPLATE,
    )
    
    # ========== 注入到消息 ==========
    # 添加系统消息
    system_message = {
        'role': 'system',
        'content': rag_prompt,
    }
    messages.insert(0, system_message)
    
    # 更新 body
    body['messages'] = messages
    
    # 保存 sources 用于返回引用
    return body, {'sources': sources}
```

---

## 7. 配置说明

### 7.1 核心配置项

```python
# config.py

class RAGConfig:
    """RAG 相关配置"""
    
    # ========== 嵌入配置 ==========
    RAG_EMBEDDING_ENGINE = ''  # 空=本地, 'openai', 'ollama', 'azure_openai'
    RAG_EMBEDDING_MODEL = 'all-MiniLM-L6-v2'  # 嵌入模型
    RAG_EMBEDDING_BATCH_SIZE = 1  # 批处理大小
    
    # ========== 文本分块配置 ==========
    CHUNK_SIZE = 1500           # 分块大小
    CHUNK_OVERLAP = 100         # 分块重叠
    TEXT_SPLITTER = 'character' # 'character' 或 'token'
    
    # ========== 检索配置 ==========
    TOP_K = 5                   # 检索返回数量
    TOP_K_RERANKER = 10         # 重排序候选数量
    RELEVANCE_THRESHOLD = 0.0   # 相关性阈值
    
    # ========== 混合检索配置 ==========
    ENABLE_RAG_HYBRID_SEARCH = False  # 是否启用混合检索
    HYBRID_BM25_WEIGHT = 0.5          # BM25 权重 (0-1)
    
    # ========== 重排序配置 ==========
    RAG_RERANKING_MODEL = ''    # 重排序模型
    
    # ========== 提示词模板 ==========
    RAG_TEMPLATE = """
使用以下上下文信息回答用户问题：

{{CONTEXT}}

用户问题：{{QUERY}}

请基于上下文信息给出回答：
"""
    
    # ========== 向量数据库配置 ==========
    VECTOR_DB = 'chroma'  # 'chroma', 'milvus', 'qdrant', 'pgvector'
```

### 7.2 向量数据库配置

```python
# 不同向量数据库的配置示例

# Chroma (默认)
CHROMA_HOST = 'localhost'
CHROMA_PORT = 8000

# Milvus
MILVUS_HOST = 'localhost'
MILVUS_PORT = 19530
MILVUS_TOKEN = ''

# Qdrant
QDRANT_HOST = 'localhost'
QDRANT_PORT = 6333
QDRANT_API_KEY = ''

# pgvector
PGVECTOR_HOST = 'localhost'
PGVECTOR_PORT = 5432
PGVECTOR_USER = 'postgres'
PGVECTOR_PASSWORD = ''
PGVECTOR_DATABASE = 'vectordb'
```

---

## 8. API 接口汇总

### 8.1 知识库管理 API

| 接口 | 方法 | 功能 |
|------|------|------|
| `/api/v1/knowledge/create` | POST | 创建知识库 |
| `/api/v1/knowledge/list` | GET | 获取知识库列表 |
| `/api/v1/knowledge/{id}` | GET | 获取知识库详情 |
| `/api/v1/knowledge/{id}/update` | POST | 更新知识库 |
| `/api/v1/knowledge/{id}` | DELETE | 删除知识库 |
| `/api/v1/knowledge/{id}/file/add` | POST | 添加文件 |
| `/api/v1/knowledge/{id}/file/remove` | POST | 移除文件 |
| `/api/v1/knowledge/{id}/files` | GET | 获取文件列表 |

### 8.2 文件处理 API

| 接口 | 方法 | 功能 |
|------|------|------|
| `/api/v1/files/upload` | POST | 上传文件 |
| `/api/v1/files/{id}` | GET | 获取文件信息 |
| `/api/v1/files/{id}` | DELETE | 删除文件 |
| `/api/v1/retrieval/process/file` | POST | 处理文件（向量化） |

### 8.3 检索 API

| 接口 | 方法 | 功能 |
|------|------|------|
| `/api/v1/retrieval/query/collection` | POST | 检索 Collection |
| `/api/v1/retrieval/process/text` | POST | 处理文本 |
| `/api/v1/retrieval/process/web` | POST | 处理网页 |

---

## 9. 最佳实践建议

### 9.1 文件处理优化

1. **分块策略**：根据文档类型选择合适的分块大小
   - 技术文档：chunk_size=1000, overlap=100
   - 长文档：chunk_size=2000, overlap=200
   - 问答场景：chunk_size=500, overlap=50

2. **启用 Markdown 分块**：对于 Markdown 文档，按标题分块效果更好

3. **去重处理**：使用内容哈希避免重复存储

### 9.2 检索优化

1. **混合检索**：启用向量+BM25 混合检索，提高召回率

2. **重排序**：使用重排序模型对检索结果进行精排

3. **多查询扩展**：用 LLM 将用户问题扩展为多个查询

### 9.3 性能优化

1. **批量嵌入**：设置合适的 batch_size 提高嵌入效率

2. **异步处理**：文件处理使用异步，避免阻塞

3. **缓存策略**：对常用查询结果进行缓存

---

## 10. 参考代码位置

基于 Open-WebUI 项目的参考实现：

| 功能 | 文件路径 |
|------|----------|
| 知识库数据模型 | `backend/open_webui/models/knowledge.py` |
| 知识库 API 路由 | `backend/open_webui/routers/knowledge.py` |
| 文件处理逻辑 | `backend/open_webui/routers/retrieval.py` (第1528-1768行) |
| 向量化存储 | `backend/open_webui/routers/retrieval.py` (第1322-1519行) |
| 检索逻辑 | `backend/open_webui/retrieval/utils.py` (第407-544行) |
| 获取知识库内容 | `backend/open_webui/retrieval/utils.py` (第926-1178行) |
| 聊天集成 | `backend/open_webui/utils/middleware.py` (第1925-1978行) |
| 文档加载器 | `backend/open_webui/retrieval/loaders/main.py` |
| 向量数据库接口 | `backend/open_webui/retrieval/vector/main.py` |
| Chroma 实现 | `backend/open_webui/retrieval/vector/dbs/chroma.py` |

---

本文档提供了知识库系统的完整实现指南，涵盖从数据模型、API 设计、文件处理、向量化、检索到聊天集成的全部流程。可根据实际项目需求进行调整和扩展。