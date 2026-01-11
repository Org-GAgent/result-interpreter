import json
import logging
from typing import Optional, Any, List

from pydantic import BaseModel, Field

from ...llm import get_default_client, LLMClient
from app.services.llm.llm_service import LLMService
from .metadata import DatasetMetadata
from .prompts.coder_prompt import CODER_SYSTEM_PROMPT, CODER_USER_PROMPT_TEMPLATE, CODER_FIX_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

class CodeTaskResponse(BaseModel):
    """LLM生成代码的响应结构，包含代码和描述。"""
    code: str = Field(..., description="生成的可执行Python代码")
    description: str = Field(..., description="代码描述：说明这段代码想要获取什么信息或分析什么内容")
    has_visualization: bool = Field(default=False, description="本次代码是否包含可视化（图表、绘图等）")
    visualization_purpose: Optional[str] = Field(None, description="可视化目的：为什么画这个图，想分析什么，有什么意义")
    visualization_analysis: Optional[str] = Field(None, description="可视化分析：图表展示什么结果，特征，计算公式，数据细节等")

    @classmethod
    def parse_from_llm_output(cls, text: str) -> "CodeTaskResponse":
        """Helper to robustly parse JSON from LLM output that might contain Markdown."""
        cleaned_text = text.strip()
        
        # Strip markdown code blocks if present
        if cleaned_text.startswith("```"):
            lines = cleaned_text.splitlines()
            # remove first line (```json or ```)
            if lines: lines.pop(0)
            # remove last line if it is ```
            if lines and lines[-1].strip() == "```":
                lines.pop()
            cleaned_text = "\n".join(lines).strip()
            
        try:
            return cls.model_validate_json(cleaned_text)
        except Exception as e:
            logger.error(f"Failed to parse LLM JSON: {e}. Raw text: {text}")
            # Fallback: try to find JSON substring
            try:
                start = cleaned_text.find("{")
                end = cleaned_text.rfind("}")
                if start != -1 and end != -1:
                    json_str = cleaned_text[start:end+1]
                    return cls.model_validate_json(json_str)
            except:
                pass
            
            # Final fallback: 返回空代码和错误描述
            return cls(code="", description="解析LLM输出失败")


class CodeGenerator:
    """
    Generator that takes metadata list, title, and description, 
    and returns a JSON-compatible object with code and description.
    Supports multiple datasets.
    """

    def __init__(self, llm_service: Optional[LLMService] = None):
        if llm_service:
            self.llm = llm_service
        else:
            self.llm = LLMService(client=LLMClient(provider="qwen"))

    def _format_columns_for_metadata(self, metadata: DatasetMetadata) -> str:
        """格式化单个数据集的列信息"""
        cols_summary = []
        cols = getattr(metadata, 'columns', [])
        for col in cols[:20]:  # Limit column context
            c_name = getattr(col, 'name', str(col))
            c_type = getattr(col, 'dtype', 'unknown')
            c_sample = getattr(col, 'sample_values', [])
            cols_summary.append(f"  - {c_name} ({c_type}): {c_sample}")
        
        cols_text = "\n".join(cols_summary)
        if len(cols) > 20:
            cols_text += f"\n  ... ({len(cols)-20} more columns)"
        return cols_text

    def _format_datasets(self, metadata_list: List[DatasetMetadata]) -> str:
        """格式化所有数据集的信息"""
        datasets_info = []
        for i, metadata in enumerate(metadata_list, 1):
            cols_text = self._format_columns_for_metadata(metadata)
            dataset_info = f"""### Dataset {i}: {metadata.filename}
- Format: {metadata.file_format}
- Total Rows: {metadata.total_rows}
- Total Columns: {metadata.total_columns}
- Columns:
{cols_text}"""
            datasets_info.append(dataset_info)
        return "\n\n".join(datasets_info)

    def generate(self, metadata_list: List[DatasetMetadata], task_title: str, task_description: str) -> CodeTaskResponse:
        """
        Generates Python code for the given task and data metadata.
        
        Args:
            metadata_list: 数据集元数据列表
            task_title: 任务标题
            task_description: 任务描述
        """
        # 兼容单个 metadata 的情况
        if isinstance(metadata_list, DatasetMetadata):
            metadata_list = [metadata_list]
        
        datasets_text = self._format_datasets(metadata_list)

        user_prompt = CODER_USER_PROMPT_TEMPLATE.format(
            datasets_info=datasets_text,
            task_title=task_title,
            task_description=task_description
        )
        
        # 2. Call LLM
        full_prompt = f"{CODER_SYSTEM_PROMPT}\n\n{user_prompt}"
        
        response_text = self.llm.chat(prompt=full_prompt)
        return CodeTaskResponse.parse_from_llm_output(response_text)

    def fix_code(self, metadata_list: List[DatasetMetadata], task_title: str, task_description: str, code: str, error: str, max_retries: int = 5) -> CodeTaskResponse:
        """
        尝试修复代码，最多尝试max_retries次。
        
        Args:
            metadata_list: 数据集元数据列表
            task_title: 任务标题
            task_description: 任务描述
            code: 需要修复的代码
            error: 执行错误信息
            max_retries: 最大重试次数，默认5次
            
        Returns:
            CodeTaskResponse: 修复后的代码响应
        """
        # 兼容单个 metadata 的情况
        if isinstance(metadata_list, DatasetMetadata):
            metadata_list = [metadata_list]
            
        datasets_text = self._format_datasets(metadata_list)
        current_code = code
        current_error = error
        
        for attempt in range(1, max_retries + 1):
            logger.info(f"代码修复尝试 {attempt}/{max_retries}")
            
            user_prompt = CODER_FIX_PROMPT_TEMPLATE.format(
                datasets_info=datasets_text,
                task_title=task_title,
                task_description=task_description,
                code=current_code,
                error=current_error
            )
            
            full_prompt = f"{CODER_SYSTEM_PROMPT}\n\n{user_prompt}"
            
            try:
                response_text = self.llm.chat(prompt=full_prompt)
                result = CodeTaskResponse.parse_from_llm_output(response_text)
                
                # 如果解析成功且代码不为空，返回结果
                if result.code and result.code.strip():
                    logger.info(f"代码修复成功 (尝试 {attempt}/{max_retries})")
                    return result
                    
            except Exception as e:
                logger.warning(f"代码修复尝试 {attempt} 失败: {e}")
                current_error = f"{error}\n\n修复尝试 {attempt} 失败: {e}"
        
        # 所有尝试都失败，返回原代码
        logger.error(f"代码修复失败，已尝试 {max_retries} 次")
        return CodeTaskResponse(code=code, description=f"代码修复失败: 已尝试{max_retries}次")
