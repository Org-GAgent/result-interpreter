"""
Task Executor Prompt Templates
"""

# ============================================================
# Task Type Classification Prompts
# ============================================================

TASK_TYPE_SYSTEM_PROMPT = """You are a task classifier. You need to determine whether a given data analysis task requires writing Python code to complete.

Classification criteria:
- Requires code (code_required): Tasks involving data calculation, statistical analysis, data processing, plotting/visualization, data filtering, etc.
- No code needed (text_only): Pure conceptual explanations, terminology definitions, general Q&A, questions not involving specific data operations

You must return a strict JSON format with only one field:
{"task_type": "code_required"} or {"task_type": "text_only"}
"""

TASK_TYPE_USER_PROMPT_TEMPLATE = """Please determine whether the following task requires writing Python code to complete:

### Dataset Information
- Filename: {filename}
- Format: {file_format}
- Rows: {total_rows}
- Columns: {total_columns}

### Task
- Title: {task_title}
- Description: {task_description}

Please return the classification result in JSON format.
"""

# ============================================================
# Text-Only Task Prompts
# ============================================================

TEXT_TASK_PROMPT_TEMPLATE = """You are a data analysis assistant. Please answer the user's question based on the following dataset information.

### Dataset Information
- Filename: {filename}
- Format: {file_format}
- Total Rows: {total_rows}
- Total Columns: {total_columns}

### Column Information
{cols_text}

### User Question
**{task_title}**
{task_description}

Please answer the question directly without writing code.
"""
