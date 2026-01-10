# Interpreter 模块工作流程文档

本文档描述了 `interpreter` 模块的整体架构和执行流程。该模块负责将计划树中的任务节点转化为可执行的代码，并在 Docker 容器中安全执行。

## 模块架构

```
interpreter/
├── metadata.py           # 数据文件元数据解析
├── coder.py              # LLM 代码生成器
├── docker_interpreter.py # Docker 代码执行器
├── task_executer.py      # 单任务执行器（整合生成+执行）
├── plan_execute.py       # 计划树执行器（执行整个计划）
└── prompts/              # 提示词模板
    ├── coder_prompt.py
    └── task_executer.py
```

## 核心组件

| 组件 | 职责 |
|------|------|
| `DataProcessor` | 解析 CSV/TSV/MAT 数据文件，提取元数据 |
| `CodeGenerator` | 调用 LLM 生成 Python 代码，支持错误修复 |
| `DockerCodeInterpreter` | 在隔离的 Docker 容器中执行代码 |
| `TaskExecutor` | 协调代码生成和执行的完整流程 |
| `PlanExecutorInterpreter` | 按依赖顺序执行整个计划树 |

---

## 整体流程图

```mermaid
flowchart TD
    subgraph 输入
        A[计划ID + 数据文件路径]
    end

    subgraph PlanExecutorInterpreter
        B[加载计划树]
        C[初始化所有节点状态为 PENDING]
        D{获取可执行节点}
        E[选择一个节点执行]
        F[TaskExecutor 执行任务]
        G[更新节点状态到数据库]
        H{还有待执行节点?}
        I[返回执行结果]
    end

    subgraph TaskExecutor
        F1[解析数据文件元数据]
        F2[LLM 判断任务类型]
        F3{需要代码?}
        F4[CodeGenerator 生成代码]
        F5[Docker 执行代码]
        F6{执行成功?}
        F7[fix_code 修复代码]
        F8{重试次数 < 5?}
        F9[返回成功结果]
        F10[返回失败结果]
        F11[LLM 直接回答]
    end

    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
    H -->|是| D
    H -->|否| I

    F --> F1
    F1 --> F2
    F2 --> F3
    F3 -->|是 CODE_REQUIRED| F4
    F3 -->|否 TEXT_ONLY| F11
    F4 --> F5
    F5 --> F6
    F6 -->|是| F9
    F6 -->|否| F7
    F7 --> F8
    F8 -->|是| F5
    F8 -->|否| F10
    F11 --> F9
```

---

## 详细流程说明

### 1. 计划树执行流程 (PlanExecutorInterpreter)

```mermaid
flowchart LR
    subgraph 执行顺序
        L1[叶子节点] --> L2[父节点]
        L2 --> L3[根节点]
    end
```

**执行规则：**
- 从**叶子节点**开始执行，逐层向上
- 节点可执行条件：
  1. 状态为 `PENDING`
  2. 是叶子节点，或所有子节点已完成
  3. 所有依赖节点已完成
- 子节点的执行结果会作为**上下文**传递给父节点

**数据库持久化：**
每个节点执行完成后，将结果保存到数据库的 `execution_result` 字段：
```json
{
  "task_type": "code_required",
  "code": "import pandas as pd\n...",
  "code_description": "计算平均分",
  "code_output": "平均分: 78.0",
  "text_response": null,
  "generated_files": [],
  "error": null
}
```

### 2. 单任务执行流程 (TaskExecutor)

```mermaid
flowchart TD
    A[接收任务] --> B[解析数据文件元数据]
    B --> C[LLM 判断任务类型]
    C --> D{任务类型}
    
    D -->|CODE_REQUIRED| E[生成代码]
    E --> F[Docker 执行]
    F --> G{成功?}
    G -->|是| H[返回结果]
    G -->|否| I[修复代码]
    I --> J{尝试次数 < limit?}
    J -->|是| F
    J -->|否| K[返回失败]
    
    D -->|TEXT_ONLY| L[LLM 直接回答]
    L --> H
```

**任务类型判断：**
- `CODE_REQUIRED`: 需要编写代码的任务（计算、绘图、数据处理）
- `TEXT_ONLY`: 纯文本任务（解释、总结、问答）

**错误修复机制：**
- 代码执行失败后，自动调用 `fix_code` 修复
- 最多重试 **5 次**
- 每次将错误信息传递给 LLM 进行修复

### 3. Docker 代码执行 (DockerCodeInterpreter)

```mermaid
flowchart TD
    A[接收代码] --> B[检查/拉取镜像]
    B --> C[创建容器]
    C --> D[挂载工作目录]
    D --> E[执行 python -c code]
    E --> F{超时?}
    F -->|是| G[杀死容器]
    F -->|否| H[获取输出]
    H --> I[清理容器]
    G --> I
    I --> J[返回结果]
```

**安全特性：**
- `network_disabled=True` - 禁用网络
- `mem_limit="512m"` - 内存限制
- 超时自动终止
- 容器用后即删

**文件挂载：**
```
宿主机数据目录 → /workspace (容器)
```

---

## 数据流向

```mermaid
flowchart LR
    subgraph 输入
        CSV[CSV/TSV/MAT 文件]
        Plan[计划树]
    end

    subgraph 处理
        Meta[元数据提取]
        LLM[LLM 代码生成]
        Docker[Docker 执行]
    end

    subgraph 输出
        DB[(数据库)]
        Files[生成的文件]
        Result[执行结果]
    end

    CSV --> Meta
    Meta --> LLM
    Plan --> LLM
    LLM --> Docker
    Docker --> Files
    Docker --> Result
    Result --> DB
```

---

## 使用示例

### 执行整个计划

```python
from app.services.interpreter.plan_execute import execute_plan

result = execute_plan(
    plan_id=1,
    data_file_path="/path/to/data.csv",
    output_dir="./results"
)

print(f"成功: {result.success}")
print(f"完成节点: {result.completed_nodes}/{result.total_nodes}")
```

### 执行单个任务

```python
from app.services.interpreter.task_executer import execute_task

result = execute_task(
    data_file_path="/path/to/data.csv",
    task_title="计算平均值",
    task_description="计算 score 列的平均值"
)

if result.success:
    print(f"代码输出: {result.code_output}")
else:
    print(f"错误: {result.error_message}")
```

---

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `llm_provider` | `"qwen"` | LLM 提供商 |
| `docker_image` | `"agent-plotter"` | Docker 镜像名称 |
| `docker_timeout` | `120` (秒) | 代码执行超时时间 |
| `max_fix_attempts` | `5` | 代码修复最大尝试次数 |

---

## 错误处理

1. **代码生成失败**: 返回空代码，标记任务失败
2. **代码执行失败**: 自动调用 fix_code 修复，最多重试 5 次
3. **Docker 超时**: 强制终止容器，返回超时错误
4. **节点执行失败**: 记录错误，继续执行其他可执行节点
