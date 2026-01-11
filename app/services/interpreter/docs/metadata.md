# Metadata 模块

该模块提供数据集元数据提取功能，用于分析和描述数据文件的结构信息。

## 概述

`metadata.py` 模块负责从各种格式的数据文件中提取元数据信息，包括：
- 文件基本信息（文件名、格式、大小）
- 数据维度（行数、列数）
- 列级详细信息（数据类型、样本值、空值统计、唯一值统计）

## 支持的文件格式

| 格式 | 扩展名 | 说明 |
|------|--------|------|
| CSV | `.csv` | 逗号分隔值文件 |
| TSV | `.tsv` | 制表符分隔值文件 |
| MAT | `.mat` | MATLAB 数据文件 |

## 数据模型

### ColumnMetadata

列级元数据模型，描述单个列的详细信息。

```python
class ColumnMetadata(BaseModel):
    name: str           # 列名
    dtype: str          # 数据类型
    sample_values: List[Any]  # 样本值（最多5个）
    null_count: int     # 空值数量
    unique_count: int   # 唯一值数量
```

**字段说明：**

| 字段 | 类型 | 描述 |
|------|------|------|
| `name` | `str` | 列名称 |
| `dtype` | `str` | 数据类型（如 `int64`, `float64`, `object` 等） |
| `sample_values` | `List[Any]` | 该列的前5个非空样本值 |
| `null_count` | `int` | 该列中空值/缺失值的数量 |
| `unique_count` | `int` | 该列中唯一值的数量（MAT文件大数据时为-1） |

### DatasetMetadata

数据集元数据模型，描述整个数据文件的信息。

```python
class DatasetMetadata(BaseModel):
    filename: str           # 文件名
    file_format: str        # 文件格式
    file_size_bytes: int    # 文件大小（字节）
    total_rows: int         # 总行数
    total_columns: int      # 总列数
    columns: List[ColumnMetadata]  # 列元数据列表
```

**字段说明：**

| 字段 | 类型 | 描述 |
|------|------|------|
| `filename` | `str` | 文件名（不含路径） |
| `file_format` | `str` | 文件格式（`csv`, `tsv`, `mat`） |
| `file_size_bytes` | `int` | 文件大小（字节） |
| `total_rows` | `int` | 数据总行数 |
| `total_columns` | `int` | 数据总列数 |
| `columns` | `List[ColumnMetadata]` | 所有列的元数据列表 |

## DataProcessor 类

数据处理器类，提供静态方法用于提取数据文件的元数据。

### 方法

#### `get_metadata(file_path: str) -> DatasetMetadata`

从指定文件路径提取元数据。

**参数：**
- `file_path` (`str`): 数据文件的完整路径

**返回：**
- `DatasetMetadata`: 数据集元数据对象

**异常：**
- `FileNotFoundError`: 文件不存在
- `ValueError`: 不支持的文件格式或文件读取失败

**示例：**

```python
from app.services.interpreter.metadata import DataProcessor

# 提取 CSV 文件元数据
metadata = DataProcessor.get_metadata("/path/to/sales_data.csv")

print(f"文件名: {metadata.filename}")
print(f"行数: {metadata.total_rows}")
print(f"列数: {metadata.total_columns}")

for col in metadata.columns:
    print(f"  - {col.name}: {col.dtype}, 空值: {col.null_count}")
```

#### `_process_mat_file(file_path: str) -> DatasetMetadata` (内部方法)

专门处理 MATLAB `.mat` 文件的内部方法。

**特殊处理：**
- 过滤 MATLAB 内部键（以 `__` 开头的键）
- 处理多维数组，使用第一维度作为行数估计
- 对大数据集（>10000元素）跳过唯一值计算以提高性能
- 将 NumPy 标量转换为 Python 原生类型以支持 JSON 序列化

## 使用示例

### 基本用法

```python
from app.services.interpreter.metadata import DataProcessor, DatasetMetadata

# 单个文件
metadata = DataProcessor.get_metadata("data/sales.csv")
print(metadata.model_dump_json(indent=2))
```

### 多数据集处理

```python
from app.services.interpreter.metadata import DataProcessor
from typing import List

file_paths = [
    "data/sales_2023.csv",
    "data/sales_2024.csv",
    "data/products.tsv"
]

metadata_list: List[DatasetMetadata] = []
for path in file_paths:
    metadata_list.append(DataProcessor.get_metadata(path))

# 打印所有数据集摘要
for meta in metadata_list:
    print(f"{meta.filename}: {meta.total_rows} 行 x {meta.total_columns} 列")
```

### 与代码生成器集成

```python
from app.services.interpreter.metadata import DataProcessor
from app.services.interpreter.coder import CodeGenerator

# 准备多个数据集的元数据
metadata_list = [
    DataProcessor.get_metadata("data/orders.csv"),
    DataProcessor.get_metadata("data/customers.csv")
]

# 传递给代码生成器
generator = CodeGenerator()
response = generator.generate(
    metadata_list=metadata_list,
    task_title="客户订单分析",
    task_description="分析各客户的订单金额分布"
)

print(response.code)
```

## 输出示例

对于一个 CSV 文件，`get_metadata` 返回的结构示例：

```json
{
  "filename": "sales_data.csv",
  "file_format": "csv",
  "file_size_bytes": 15360,
  "total_rows": 500,
  "total_columns": 4,
  "columns": [
    {
      "name": "Date",
      "dtype": "object",
      "sample_values": ["2023-01-01", "2023-01-02", "2023-01-03", "2023-01-04", "2023-01-05"],
      "null_count": 0,
      "unique_count": 365
    },
    {
      "name": "Product",
      "dtype": "object",
      "sample_values": ["Apple", "Banana", "Orange", "Grape", "Mango"],
      "null_count": 0,
      "unique_count": 5
    },
    {
      "name": "Quantity",
      "dtype": "int64",
      "sample_values": [10, 25, 15, 30, 20],
      "null_count": 0,
      "unique_count": 45
    },
    {
      "name": "Revenue",
      "dtype": "float64",
      "sample_values": [99.99, 149.50, 75.00, 200.00, 125.75],
      "null_count": 2,
      "unique_count": 150
    }
  ]
}
```

## 注意事项

1. **性能考虑**：对于大型 MAT 文件（>10000 元素），唯一值统计会被跳过（返回 -1）
2. **内存使用**：CSV/TSV 文件会被完整加载到内存中进行分析
3. **样本值数量**：每列最多返回 5 个样本值
4. **编码支持**：CSV/TSV 文件使用 pandas 默认编码（UTF-8）
