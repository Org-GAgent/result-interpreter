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
    ├── coder_prompt.py       # 代码生成提示词
    └── task_executer.py      # 任务执行提示词（任务分类、信息收集）
```

## 核心组件

| 组件 | 职责 |
|------|------|
| `DataProcessor` | 解析 CSV/TSV/MAT 数据文件，提取元数据 |
| `CodeGenerator` | 调用 LLM 生成 Python 代码，支持错误修复和可视化分析 |
| `DockerCodeInterpreter` | 在隔离的 Docker 容器中执行代码 |
| `TaskExecutor` | 协调信息收集、代码生成和执行的完整流程 |
| `PlanExecutorInterpreter` | 按依赖顺序执行整个计划树，生成分析报告 |

---

## 整体流程图

```mermaid
flowchart TD
    subgraph 输入
        A[计划ID + 数据文件路径列表]
    end

    subgraph PlanExecutorInterpreter
        B[加载计划树]
        B1[初始化分析报告 MD]
        C[初始化所有节点状态为 PENDING]
        D{获取可执行节点}
        E[选择一个节点执行]
        F[TaskExecutor 执行任务]
        F_VIS{有可视化?}
        F_VIS_Y[追加到分析报告]
        G[更新节点状态到数据库]
        H{还有待执行节点?}
        I[完成分析报告]
        J[返回执行结果]
    end

    subgraph TaskExecutor
        F1[解析所有数据文件元数据]
        F2[信息收集阶段]
        F3[LLM 判断任务类型]
        F4{需要代码?}
        F5[CodeGenerator 生成代码]
        F6[Docker 执行代码]
        F7{执行成功?}
        F8[fix_code 修复代码]
        F9{重试次数 < 5?}
        F10[返回成功结果]
        F11[返回失败结果]
        F12[LLM 直接回答]
    end

    A --> B
    B --> B1
    B1 --> C
    C --> D
    D --> E
    E --> F
    F --> F_VIS
    F_VIS -->|是| F_VIS_Y
    F_VIS -->|否| G
    F_VIS_Y --> G
    G --> H
    H -->|是| D
    H -->|否| I
    I --> J

    F --> F1
    F1 --> F2
    F2 --> F3
    F3 --> F4
    F4 -->|是 CODE_REQUIRED| F5
    F4 -->|否 TEXT_ONLY| F12
    F5 --> F6
    F6 --> F7
    F7 -->|是| F10
    F7 -->|否| F8
    F8 --> F9
    F9 -->|是| F6
    F9 -->|否| F11
    F12 --> F10
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

**多数据文件支持：**
- 支持传入多个数据文件 `data_file_paths: List[str]`
- 所有文件的元数据会被解析并传递给 LLM
- 可以进行单独分析或跨数据集比较分析

**分析报告自动生成：**
- 每个计划创建独立的 Markdown 报告文件
- 每次有可视化任务完成时，自动追加：目的 + 图表 + 分析
- 执行完成后添加统计总结

**数据库持久化：**
每个节点执行完成后，将结果保存到数据库的 `execution_result` 字段：
```json
{
  "task_type": "code_required",
  "code": "import pandas as pd\n...",
  "code_description": "计算平均分",
  "code_output": "平均分: 78.0",
  "text_response": null,
  "generated_files": ["results/chart.png"],
  "has_visualization": true,
  "visualization_purpose": "展示各组分数分布...",
  "visualization_analysis": "柱状图显示A组平均分78.5...",
  "error": null
}
```

### 2. 单任务执行流程 (TaskExecutor)

```mermaid
flowchart TD
    A[接收任务] --> B[解析所有数据文件元数据]
    B --> C[信息收集阶段]
    C --> D[LLM 判断任务类型]
    D --> E{任务类型}
    
    E -->|CODE_REQUIRED| F[生成代码]
    F --> G[Docker 执行]
    G --> H{成功?}
    H -->|是| I[返回结果]
    H -->|否| J[修复代码]
    J --> K{尝试次数 < limit?}
    K -->|是| G
    K -->|否| L[返回失败]
    
    E -->|TEXT_ONLY| M[LLM 直接回答]
    M --> I
```

**信息收集阶段 (_gather_additional_info)：**
- 在代码生成之前，先询问 LLM 是否需要额外的数据信息
- 循环收集直到 LLM 表示信息充足（最多 5 轮）
- **关键：如果任务涉及可视化，会要求提前获取将要展示的具体数值**
- 收集的信息会传递给代码生成阶段

```mermaid
flowchart TD
    A[开始信息收集] --> B[询问LLM是否需要更多信息]
    B --> C{need_more_info?}
    C -->|是| D[执行信息收集代码]
    D --> E{执行成功?}
    E -->|是| F[保存结果]
    E -->|否| G[fix_code修复]
    G --> H{修复成功?}
    H -->|是| D
    H -->|否| F
    F --> I{达到轮次上限?}
    I -->|否| B
    I -->|是| J[返回收集的信息]
    C -->|否| J
```

**任务类型判断：**
- `CODE_REQUIRED`: 需要编写代码的任务（计算、绘图、数据处理）
- `TEXT_ONLY`: 纯文本任务（解释、总结、问答）

**可视化任务处理：**
- 代码生成时会返回额外字段：
  - `has_visualization`: 是否包含可视化
  - `visualization_purpose`: 为什么画这个图，想分析什么
  - `visualization_analysis`: 图表展示什么结果，特征，计算公式等

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
        CSV[CSV/TSV/MAT 文件列表]
        Plan[计划树]
    end

    subgraph 处理
        Meta[元数据提取]
        Info[信息收集]
        LLM[LLM 代码生成]
        Docker[Docker 执行]
    end

    subgraph 输出
        DB[(数据库)]
        Files[生成的文件]
        Report[分析报告 MD]
        Result[执行结果]
    end

    CSV --> Meta
    Meta --> Info
    Info --> LLM
    Plan --> LLM
    LLM --> Docker
    Docker --> Files
    Docker --> Result
    Result --> DB
    Files --> Report
    Result --> Report
```

---

## 使用示例

### 执行整个计划（多数据文件）

```python
from app.services.interpreter.plan_execute import execute_plan

result = execute_plan(
    plan_id=1,
    data_file_paths=[
        "/path/to/data1.csv",
        "/path/to/data2.csv"
    ],
    output_dir="./results"
)

print(f"成功: {result.success}")
print(f"完成节点: {result.completed_nodes}/{result.total_nodes}")
print(f"分析报告: {result.report_path}")
```

### 执行单个任务

```python
from app.services.interpreter.task_executer import execute_task

result = execute_task(
    data_file_paths=["/path/to/data.csv"],
    task_title="绘制销售趋势图",
    task_description="按月份绘制销售额趋势折线图"
)

if result.success:
    print(f"代码输出: {result.code_output}")
    if result.has_visualization:
        print(f"可视化目的: {result.visualization_purpose}")
        print(f"可视化分析: {result.visualization_analysis}")
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
| `max_info_rounds` | `5` | 信息收集最大轮次 |

---

## 分析报告结构

每个计划执行时会自动生成 Markdown 格式的分析报告：

```markdown
# 数据分析报告

**计划ID**: 1
**计划标题**: 销售数据分析
**生成时间**: 2026-01-11 10:00:00

---

## 任务: 绘制月度销售趋势
**任务ID**: 3
**执行时间**: 2026-01-11T10:01:00

### 分析目的
展示销售额随时间的变化趋势，识别季节性模式...

### 生成的图表
![sales_trend.png](results/sales_trend.png)

### 图表分析
折线图显示2023年销售额整体呈上升趋势。
Q1平均销售额: $120,000，Q4达到峰值$180,000...
计算方法: SUM(sales) GROUP BY month

---

## 执行总结

| 指标 | 数值 |
|------|------|
| 总任务数 | 5 |
| 完成 | 5 |
| 失败 | 0 |
| 跳过 | 0 |

**完成时间**: 2026-01-11 10:05:00
```

---

## 错误处理

1. **代码生成失败**: 返回空代码，标记任务失败
2. **代码执行失败**: 自动调用 fix_code 修复，最多重试 5 次
3. **信息收集失败**: 记录错误继续下一轮或直接进入代码生成
4. **Docker 超时**: 强制终止容器，返回超时错误
5. **节点执行失败**: 记录错误，继续执行其他可执行节点
