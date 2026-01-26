# Interpreter 模块 API 参考文档

本文档描述了 `app.services.interpreter` 模块对外提供的公共接口。

---

## 目录

- [快速开始](#快速开始)
- [核心接口](#核心接口)
  - [run_analysis](#run_analysis)
  - [run_analysis_async](#run_analysis_async)
  - [execute_plan](#execute_plan)
  - [execute_task](#execute_task)
- [数据类型](#数据类型)
  - [AnalysisResult](#analysisresult)
  - [PlanExecutionResult](#planexecutionresult)
  - [TaskExecutionResult](#taskexecutionresult)
  - [NodeExecutionRecord](#nodeexecutionrecord)
- [支持的数据格式](#支持的数据格式)
- [使用示例](#使用示例)

---

## 快速开始

```python
from app.services.interpreter.interpreter import run_analysis

# 一站式执行：自动创建计划 -> 分解任务 -> 执行
result = run_analysis(
    description="分析销售数据趋势，计算月度增长率，绘制可视化图表",
    data_paths=["data/sales.csv"]
)

print(f"执行成功: {result.success}")
print(f"生成文件: {result.generated_files}")
print(f"分析报告: {result.report_path}")
```

---

## 核心接口

### run_analysis

**一站式数据分析接口**，完整流程自动执行：实验设计 → 创建计划 → 分解任务 → 图简化 → 执行。

```python
def run_analysis(
    description: str,
    data_paths: List[str],
    *,
    title: Optional[str] = None,
    output_dir: str = "./results",
    llm_provider: str = "qwen",
    max_depth: int = 5,
    node_budget: int = 50,
    docker_image: str = "agent-plotter",
    docker_timeout: int = 7200,
) -> AnalysisResult
```

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `description` | `str` | ✅ | - | 分析任务描述，详细说明分析目标和要求 |
| `data_paths` | `List[str]` | ✅ | - | 数据文件路径列表 |
| `title` | `str` | ❌ | 自动生成 | 计划标题，默认使用第一个文件名 |
| `output_dir` | `str` | ❌ | `"./results"` | 输出目录，存放生成的文件和报告 |
| `llm_provider` | `str` | ❌ | `"qwen"` | LLM 提供商 (`qwen`/`openai` 等) |
| `max_depth` | `int` | ❌ | `5` | 任务分解最大深度 |
| `node_budget` | `int` | ❌ | `50` | 任务节点数量上限 |
| `docker_image` | `str` | ❌ | `"agent-plotter"` | Docker 镜像名称 |
| `docker_timeout` | `int` | ❌ | `7200` | Docker 执行超时时间（秒） |

**返回值：** `AnalysisResult`

**示例：**

```python
from app.services.interpreter.interpreter import run_analysis

result = run_analysis(
    description="""
    对用户行为数据进行分析：
    1. 统计每日活跃用户数
    2. 分析用户留存率
    3. 绘制用户增长趋势图
    """,
    data_paths=["data/user_events.csv", "data/users.csv"],
    max_depth=3,
    node_budget=20
)

if result.success:
    print(f"分析报告已生成: {result.report_path}")
else:
    print(f"执行失败: {result.error}")
```

---

### run_analysis_async

**异步版本**：仅创建和分解计划，返回 `plan_id` 供后续执行。适用于需要分离计划创建和执行的场景。

```python
def run_analysis_async(
    description: str,
    data_paths: List[str],
    **kwargs
) -> int
```

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `description` | `str` | ✅ | 分析任务描述 |
| `data_paths` | `List[str]` | ✅ | 数据文件路径列表 |
| `title` | `str` | ❌ | 计划标题 |
| `max_depth` | `int` | ❌ | 任务分解最大深度（默认 3） |
| `node_budget` | `int` | ❌ | 任务节点数量上限（默认 10） |

**返回值：** `int` - 计划 ID，可用于后续调用 `execute_plan()`

**示例：**

```python
from app.services.interpreter.interpreter import run_analysis_async, execute_plan

# Step 1: 创建计划（不执行）
plan_id = run_analysis_async(
    description="分析销售数据",
    data_paths=["data/sales.csv"],
    max_depth=2
)
print(f"计划已创建: {plan_id}")

# Step 2: 稍后执行
result = execute_plan(
    plan_id=plan_id,
    data_paths=["data/sales.csv"]
)
```

---

### execute_plan

**执行已存在的计划**。适用于恢复执行、重新执行失败的计划等场景。

```python
def execute_plan(
    plan_id: int,
    data_paths: List[str],
    *,
    output_dir: str = "./results",
    llm_provider: str = "qwen",
    docker_image: str = "agent-plotter",
    docker_timeout: int = 300,
) -> AnalysisResult
```

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `plan_id` | `int` | ✅ | - | 计划 ID |
| `data_paths` | `List[str]` | ✅ | - | 数据文件路径列表 |
| `output_dir` | `str` | ❌ | `"./results"` | 输出目录 |
| `llm_provider` | `str` | ❌ | `"qwen"` | LLM 提供商 |
| `docker_image` | `str` | ❌ | `"agent-plotter"` | Docker 镜像名称 |
| `docker_timeout` | `int` | ❌ | `300` | Docker 超时时间（秒） |

**返回值：** `AnalysisResult`

**示例：**

```python
from app.services.interpreter.interpreter import execute_plan

# 重新执行计划 ID 为 5 的计划
result = execute_plan(
    plan_id=5,
    data_paths=["data/sales.csv"],
    output_dir="./results/rerun"
)
```

---

### execute_task

**便捷函数：执行单个任务**。适用于不需要完整计划分解的简单任务。

```python
def execute_task(
    data_file_paths: List[str],
    task_title: str,
    task_description: str,
    subtask_results: str = "",
    skip_info_gathering: bool = False,
    is_visualization: bool = False,
    **kwargs
) -> TaskExecutionResult
```

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `data_file_paths` | `List[str]` | ✅ | - | 数据文件路径列表 |
| `task_title` | `str` | ✅ | - | 任务标题 |
| `task_description` | `str` | ✅ | - | 任务描述 |
| `subtask_results` | `str` | ❌ | `""` | 子任务结果（上下文） |
| `skip_info_gathering` | `bool` | ❌ | `False` | 是否跳过信息收集阶段 |
| `is_visualization` | `bool` | ❌ | `False` | 是否为可视化任务 |
| `llm_provider` | `str` | ❌ | `"qwen"` | LLM 提供商 |
| `docker_image` | `str` | ❌ | `"agent-plotter"` | Docker 镜像名称 |
| `docker_timeout` | `int` | ❌ | `60` | Docker 超时时间（秒） |
| `output_dir` | `str` | ❌ | 数据目录 | 输出目录 |

**返回值：** `TaskExecutionResult`

**示例：**

```python
from app.services.interpreter.task_executer import execute_task

# 执行一个简单的计算任务
result = execute_task(
    data_file_paths=["data/sales.csv"],
    task_title="计算平均销售额",
    task_description="计算所有产品的平均销售额，按月份分组统计"
)

print(f"执行成功: {result.success}")
print(f"代码输出: {result.code_output}")

# 执行可视化任务
viz_result = execute_task(
    data_file_paths=["data/sales.csv"],
    task_title="绘制销售趋势图",
    task_description="绘制月度销售趋势折线图",
    is_visualization=True
)
```

---

## 数据类型

### AnalysisResult

分析执行的完整结果。

```python
@dataclass
class AnalysisResult:
    plan_id: int                    # 计划 ID
    success: bool                   # 是否成功
    total_tasks: int                # 总任务数
    completed_tasks: int            # 已完成任务数
    failed_tasks: int               # 失败任务数
    generated_files: List[str]      # 生成的文件列表
    report_path: Optional[str]      # 分析报告路径
    error: Optional[str]            # 错误信息（失败时）
```

---

### PlanExecutionResult

计划执行的完整结果（底层类型）。

```python
@dataclass
class PlanExecutionResult:
    plan_id: int                                    # 计划 ID
    plan_title: str                                 # 计划标题
    success: bool                                   # 是否成功
    total_nodes: int                                # 总节点数
    completed_nodes: int                            # 已完成节点数
    failed_nodes: int                               # 失败节点数
    skipped_nodes: int                              # 跳过节点数
    node_records: Dict[int, NodeExecutionRecord]    # 节点执行记录
    all_generated_files: List[str]                  # 所有生成的文件
    report_path: Optional[str]                      # 报告路径
    started_at: Optional[str]                       # 开始时间
    completed_at: Optional[str]                     # 完成时间
```

---

### TaskExecutionResult

单个任务的执行结果。

```python
class TaskExecutionResult(BaseModel):
    task_type: TaskType             # 任务类型: CODE_REQUIRED / TEXT_ONLY
    success: bool                   # 是否成功
    
    # 代码相关（仅 CODE_REQUIRED 任务）
    final_code: Optional[str]       # 最终执行的代码
    code_description: Optional[str] # 代码功能描述
    code_output: Optional[str]      # 代码执行的标准输出
    code_error: Optional[str]       # 代码执行的错误信息
    total_attempts: int             # 代码执行总尝试次数
    
    # 可视化相关
    has_visualization: bool         # 是否包含可视化
    visualization_purpose: Optional[str]    # 可视化目的
    visualization_analysis: Optional[str]   # 可视化分析
    
    # 文本相关（仅 TEXT_ONLY 任务）
    text_response: Optional[str]    # LLM 直接回答的文本
    
    # 信息收集相关
    gathered_info: Optional[str]    # 收集的额外数据信息
    info_gathering_rounds: int      # 信息收集轮次
    
    # 通用
    error_message: Optional[str]    # 系统级错误信息
```

---

### NodeExecutionRecord

单个节点的执行记录。

```python
@dataclass
class NodeExecutionRecord:
    node_id: int                            # 节点 ID
    node_name: str                          # 节点名称
    status: NodeExecutionStatus             # 执行状态
    task_type: Optional[TaskType]           # 任务类型
    
    # 代码执行结果
    code: Optional[str]                     # 执行的代码
    code_output: Optional[str]              # 代码输出
    code_description: Optional[str]         # 代码描述
    
    # 可视化相关
    has_visualization: bool                 # 是否包含可视化
    visualization_purpose: Optional[str]    # 可视化目的
    visualization_analysis: Optional[str]   # 可视化分析
    
    # 文本响应
    text_response: Optional[str]            # 文本响应
    
    # 生成的文件
    generated_files: List[str]              # 生成的文件列表
    
    # 错误信息
    error_message: Optional[str]            # 错误信息
    
    # 时间戳
    started_at: Optional[str]               # 开始时间
    completed_at: Optional[str]             # 完成时间
```

**NodeExecutionStatus 枚举：**

| 值 | 说明 |
|----|------|
| `PENDING` | 待执行 |
| `RUNNING` | 执行中 |
| `COMPLETED` | 已完成 |
| `FAILED` | 执行失败 |
| `SKIPPED` | 已跳过（依赖失败） |

---

## 支持的数据格式

| 格式 | 扩展名 | 说明 |
|------|--------|------|
| CSV | `.csv` | 逗号分隔值文件 |
| TSV | `.tsv` | 制表符分隔值文件 |
| MAT | `.mat` | MATLAB 数据文件 |
| NPY | `.npy` | NumPy 二进制文件 |

---

## 使用示例

### 示例 1：完整数据分析流程

```python
from app.services.interpreter.interpreter import run_analysis

result = run_analysis(
    description="""
    请对电商销售数据进行全面分析：
    
    1. 数据概览
       - 统计总订单数、总销售额
       - 计算平均客单价
    
    2. 时间维度分析
       - 分析月度销售趋势
       - 识别销售高峰期
    
    3. 产品分析
       - 统计各品类销售占比
       - 找出 Top 10 热销商品
    
    4. 可视化
       - 绘制销售趋势折线图
       - 绘制品类占比饼图
    """,
    data_paths=["data/orders.csv", "data/products.csv"],
    output_dir="./analysis_results",
    max_depth=3,
    node_budget=30
)

print(f"分析完成: {result.success}")
print(f"总任务: {result.total_tasks}, 完成: {result.completed_tasks}")
print(f"生成文件: {result.generated_files}")
print(f"查看报告: {result.report_path}")
```

### 示例 2：分步执行

```python
from app.services.interpreter.interpreter import run_analysis_async, execute_plan

# 第一步：创建计划
plan_id = run_analysis_async(
    description="分析用户数据",
    data_paths=["data/users.csv"],
    max_depth=2
)
print(f"计划已创建: Plan #{plan_id}")

# 可以在这里暂停，稍后继续...

# 第二步：执行计划
result = execute_plan(
    plan_id=plan_id,
    data_paths=["data/users.csv"],
    output_dir="./user_analysis"
)
```

### 示例 3：执行单个任务

```python
from app.services.interpreter.task_executer import execute_task

# 简单计算任务
result = execute_task(
    data_file_paths=["data/metrics.csv"],
    task_title="计算关键指标",
    task_description="计算 DAU、MAU、留存率等关键指标",
    skip_info_gathering=True  # 跳过信息收集，加快执行
)

if result.success:
    print(result.code_output)
else:
    print(f"失败: {result.error_message}")
```

### 示例 4：可视化任务

```python
from app.services.interpreter.task_executer import execute_task

result = execute_task(
    data_file_paths=["data/time_series.csv"],
    task_title="时间序列可视化",
    task_description="""
    绘制时间序列分析图表：
    - 原始数据折线图
    - 移动平均趋势线
    - 季节性分解图
    """,
    is_visualization=True,  # 使用可视化 skill
    output_dir="./charts"
)

if result.has_visualization:
    print(f"可视化目的: {result.visualization_purpose}")
    print(f"分析结论: {result.visualization_analysis}")
```

---

## 执行流程

```
┌─────────────────────────────────────────────────────────────────┐
│                      run_analysis()                              │
├─────────────────────────────────────────────────────────────────┤
│  1. 验证数据文件                                                  │
│  2. 实验设计 (LLM 设计分析方向)                                    │
│  3. 创建计划 (PlanRepository)                                     │
│  4. 分解任务 (PlanDecomposer) → 生成任务树                         │
│  5. 图简化 (TreeSimplifier) → 合并相似节点，生成 DAG               │
│  6. 执行计划 (PlanExecutorInterpreter)                            │
│     └─ 按拓扑顺序执行：叶子节点 → 根节点                            │
│         └─ 每个节点使用 TaskExecutor 执行                          │
│             ├─ 信息收集阶段                                       │
│             ├─ 任务类型判断                                       │
│             ├─ 代码生成/文本生成                                   │
│             └─ Docker 执行 + 错误修复                             │
│  7. 生成分析报告                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 注意事项

1. **Docker 环境**：代码执行依赖 Docker，确保 Docker 已安装且 daemon 正在运行。

2. **Docker 镜像**：默认使用 `agent-plotter` 镜像，需提前构建或拉取。

3. **LLM 配置**：确保已配置相应的 LLM API Key（环境变量或配置文件）。

4. **文件路径**：数据文件路径支持相对路径和绝对路径，建议使用绝对路径。

5. **输出目录**：
   - 代码生成的文件保存在 `output_dir/results/` 目录下
   - 分析报告保存在 `output_dir/` 目录下

6. **超时设置**：
   - `docker_timeout` 是单次代码执行的超时时间
   - 复杂分析建议增大此值（默认 7200 秒）

7. **任务分解控制**：
   - `max_depth` 控制任务树深度
   - `node_budget` 控制总节点数量
   - 较大的值会生成更细粒度的任务，但执行时间更长
