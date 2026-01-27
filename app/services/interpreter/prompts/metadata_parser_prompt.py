"""
文件元数据解析提示词。
用于让 LLM 生成解析文件内容的代码。
"""

METADATA_PARSER_SYSTEM_PROMPT = """你是一个数据文件解析专家。你需要根据文件信息生成 Python 代码来解析文件并提取元数据。"""

METADATA_PARSER_USER_PROMPT = '''请根据以下文件信息，生成 Python 代码来解析该文件并提取关键元数据。

## 文件信息
- 文件名: {filename}
- 扩展名: {file_extension}
- 大小: {file_size_bytes} 字节
- MIME类型: {mime_type}
- 是否二进制: {is_binary}
- 编码: {encoding}

{preview_section}

## 要求
1. 定义一个 `parse_file(file_path: str) -> dict` 函数
2. 返回字典必须包含以下关键元数据：

### 表格数据 (CSV/TSV/Excel等)
```python
{{
    "file_type": "tabular",
    "total_rows": 10000,        # 总行数
    "total_columns": 5,         # 总列数
    "columns": [                # 列信息（最多前 20 列）
        {{
            "name": "id",
            "dtype": "int64",
            "sample_values": [1, 2, 3],  # 最多 3 个样例值
            "null_count": 0
        }},
        ...
    ],
    "sample_rows": [            # 样例行（最多前 5 行）
        {{"id": 1, "name": "Alice", ...}},
        ...
    ]
}}
```

### 数组数据 (NPY/MAT/HDF5等)
```python
{{
    "file_type": "array",
    "shape": [100, 50],         # 数组形状
    "dtype": "float64",         # 数据类型
    "ndim": 2,                  # 维度数
    "size": 5000,               # 元素总数
    "sample_values": [1.0, 2.0, 3.0],  # 最多 3 个样例值（扁平化后）
    "min": 0.0,                 # 最小值（如果是数值类型）
    "max": 100.0,               # 最大值（如果是数值类型）
    "mean": 50.0                # 平均值（如果是数值类型）
}}
```

### 图像数据 (PNG/JPG/TIFF等)
```python
{{
    "file_type": "image",
    "width": 1920,
    "height": 1080,
    "channels": 3,
    "format": "PNG",
    "mode": "RGB"
}}
```

### JSON/字典数据
```python
{{
    "file_type": "json",
    "keys": ["key1", "key2", ...],  # 顶层键（最多 20 个）
    "total_keys": 50,
    "sample_data": {{...}}          # 部分数据预览
}}
```

## 重要限制
- sample_values: 最多 3 个
- sample_rows: 最多 5 行
- columns: 最多展示前 20 列的信息
- keys: 最多展示前 20 个键
- 所有列表/数组预览都要控制长度，避免输出过大

## 输出要求
1. 包含必要的 import 语句
2. 代码必须用 ```python 和 ``` 包裹
3. 只输出代码，不要解释
4. 确保代码健壮，处理可能的异常'''


CODE_FIX_PROMPT = '''原代码执行失败，请修复。

原代码:
```python
{code}
```

错误信息:
```
{error}
```

要求：
1. 分析错误原因并修复代码
2. 保持原有函数签名 `parse_file(file_path: str) -> dict`
3. 只输出修复后的完整代码，不要解释
4. 代码必须用 ```python 和 ``` 包裹'''


CODE_FORMAT_FIX_PROMPT = '''请将以下内容转换为标准 Python 代码格式。

原始内容:
{raw_content}

要求：
1. 提取其中的 Python 代码
2. 确保代码定义了 `parse_file(file_path: str) -> dict` 函数
3. 代码必须用 ```python 和 ``` 包裹
4. 只输出代码，不要解释

输出格式示例:
```python
import pandas as pd

def parse_file(file_path: str) -> dict:
    # 你的代码
    return {{}}
```'''


def build_code_fix_prompt(code: str, error: str) -> str:
    """
    构建代码修复提示词。
    
    Args:
        code: 原代码
        error: 错误信息
        
    Returns:
        格式化后的提示词
    """
    return CODE_FIX_PROMPT.format(code=code, error=error)


def build_code_format_fix_prompt(raw_content: str) -> str:
    """
    构建代码格式修复提示词。
    
    Args:
        raw_content: LLM 返回的原始内容（可能格式不正确）
        
    Returns:
        格式化后的提示词
    """
    return CODE_FORMAT_FIX_PROMPT.format(raw_content=raw_content)


def build_metadata_parser_prompt(
    filename: str,
    file_extension: str,
    file_size_bytes: int,
    mime_type: str | None,
    is_binary: bool,
    encoding: str | None,
    raw_preview: str | None,
    preview_lines: int = 0,
    preview_bytes: int = 0,
) -> str:
    """
    构建元数据解析提示词。
    
    Args:
        filename: 文件名
        file_extension: 扩展名
        file_size_bytes: 文件大小
        mime_type: MIME 类型
        is_binary: 是否二进制
        encoding: 编码
        raw_preview: 预览内容
        preview_lines: 预览行数
        preview_bytes: 预览字节数
        
    Returns:
        格式化后的提示词
    """
    # 构建预览部分
    preview_section = ""
    if raw_preview:
        if is_binary:
            preview_section = f"文件头部 Hex 预览（前 {preview_bytes} 字节）:\n```\n{raw_preview}\n```"
        else:
            preview_section = f"文件内容预览（前 {preview_lines} 行）:\n```\n{raw_preview}\n```"
    
    return METADATA_PARSER_USER_PROMPT.format(
        filename=filename,
        file_extension=file_extension,
        file_size_bytes=file_size_bytes,
        mime_type=mime_type or "未知",
        is_binary=is_binary,
        encoding=encoding or "N/A",
        preview_section=preview_section,
    )
