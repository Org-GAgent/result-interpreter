"""
File metadata parsing prompts for the LLM.
"""

METADATA_PARSER_SYSTEM_PROMPT = """You are a data file parsing expert. Generate Python code to parse the file and extract metadata."""

METADATA_PARSER_USER_PROMPT = '''Please generate Python code to parse the file and extract metadata based on the information below.

## File Information
- File name: {filename}
- Extension: {file_extension}
- Size: {file_size_bytes} bytes
- MIME type: {mime_type}
- Is binary: {is_binary}
- Encoding: {encoding}

{preview_section}

## Requirements
1. Define a function `parse_file(file_path: str) -> dict`
2. Return a dict with the required metadata keys

### Tabular Data (CSV/TSV/Excel)
```python
{{
    "file_type": "tabular",
    "total_rows": 10000,
    "total_columns": 5,
    "columns": [
        {{
            "name": "id",
            "dtype": "int64",
            "sample_values": [1, 2, 3],
            "null_count": 0
        }},
        ...
    ],
    "sample_rows": [
        {{"id": 1, "name": "Alice", ...}},
        ...
    ]
}}
```

### Array Data (NPY/MAT/HDF5)
```python
{{
    "file_type": "array",
    "shape": [100, 50],
    "dtype": "float64",
    "ndim": 2,
    "size": 5000,
    "sample_values": [1.0, 2.0, 3.0],
    "min": 0.0,
    "max": 100.0,
    "mean": 50.0
}}
```

### Image Data (PNG/JPG/TIFF)
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

### JSON / Dict Data
```python
{{
    "file_type": "json",
    "keys": ["key1", "key2", ...],
    "total_keys": 50,
    "sample_data": {{...}}
}}
```

## Limits
- sample_values: at most 3 values
- sample_rows: at most 5 rows
- columns: at most 20 columns
- keys: at most 20 keys
- Keep previews short to avoid excessive output

## Output Requirements
1. Include required imports
2. Wrap code with ```python and ```
3. Output code only (no explanations)
4. Ensure code is robust with error handling
'''

CODE_FIX_PROMPT = '''The original code failed to execute. Please fix it.

Original code:
```python
{code}
```

Error:
```
{error}
```

Requirements:
1. Analyze the error and fix the code
2. Keep the function signature `parse_file(file_path: str) -> dict`
3. Output the full corrected code only (no explanations)
4. Wrap the code with ```python and ```
'''

CODE_FORMAT_FIX_PROMPT = '''Please convert the following content into clean Python code.

Original content:
{raw_content}

Requirements:
1. Extract the Python code
2. Ensure it defines `parse_file(file_path: str) -> dict`
3. Wrap the code with ```python and ```
4. Output code only (no explanations)

Example output:
```python
import pandas as pd

def parse_file(file_path: str) -> dict:
    return {{}}
```
'''


def build_code_fix_prompt(code: str, error: str) -> str:
    """Build a code-fix prompt for execution errors."""
    return CODE_FIX_PROMPT.format(code=code, error=error)


def build_code_format_fix_prompt(raw_content: str) -> str:
    """Build a prompt to normalize code formatting."""
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
    """Build a metadata parsing prompt from file details."""
    preview_section = ""
    if raw_preview:
        if is_binary:
            preview_section = (
                f"Binary head preview (first {preview_bytes} bytes):\n```\n{raw_preview}\n```"
            )
        else:
            preview_section = (
                f"Text preview (first {preview_lines} lines):\n```\n{raw_preview}\n```"
            )

    return METADATA_PARSER_USER_PROMPT.format(
        filename=filename,
        file_extension=file_extension,
        file_size_bytes=file_size_bytes,
        mime_type=mime_type or "unknown",
        is_binary=is_binary,
        encoding=encoding or "N/A",
        preview_section=preview_section,
    )
