"""
任务执行器模块

该模块封装了代码生成、执行和修复的完整流程。
自动判断任务类型，对需要代码的任务进行生成和执行，对不需要代码的任务直接由LLM处理。
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field

from ...llm import LLMClient
from app.services.llm.llm_service import LLMService
from .metadata import DatasetMetadata, DataProcessor
from .coder import CodeGenerator, CodeTaskResponse
from .docker_interpreter import DockerCodeInterpreter, CodeExecutionResult
from .prompts.task_executer import (
    TASK_TYPE_SYSTEM_PROMPT,
    TASK_TYPE_USER_PROMPT_TEMPLATE,
    TEXT_TASK_PROMPT_TEMPLATE
)

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """任务类型枚举"""
    CODE_REQUIRED = "code_required"      # 需要编写代码的任务（计算、绘图、数据处理等）
    TEXT_ONLY = "text_only"              # 纯文本任务（解释、总结、问答等）
    

class TaskExecutionResult(BaseModel):
    """任务执行的最终结果"""
    task_type: TaskType = Field(..., description="任务类型")
    success: bool = Field(..., description="任务是否成功完成")
    
    # 代码相关（仅当 task_type == CODE_REQUIRED 时有值）
    final_code: Optional[str] = Field(None, description="最终执行的代码")
    code_description: Optional[str] = Field(None, description="代码功能描述")
    code_output: Optional[str] = Field(None, description="代码执行的标准输出")
    code_error: Optional[str] = Field(None, description="代码执行的错误信息")
    total_attempts: int = Field(0, description="代码执行总尝试次数")
    
    # 文本相关（仅当 task_type == TEXT_ONLY 时有值）
    text_response: Optional[str] = Field(None, description="LLM直接回答的文本")
    
    # 通用
    error_message: Optional[str] = Field(None, description="系统级错误信息")


class TaskExecutor:
    """
    任务执行器
    
    负责协调代码生成器(CodeGenerator)和代码解释器(DockerCodeInterpreter)，
    实现任务的自动判断、代码生成、执行和错误修复的完整流程。
    
    使用示例:
        executor = TaskExecutor(data_file_path="/path/to/data.csv")
        result = executor.execute(
            task_title="计算平均值",
            task_description="计算销售额的平均值并绘制柱状图"
        )
    """

    def __init__(
        self,
        data_file_path: str,
        llm_provider: str = "qwen",
        docker_image: str = "agent-plotter",
        docker_timeout: int = 60
    ):
        """
        初始化任务执行器
        
        Args:
            data_file_path: 数据文件路径（支持 csv, tsv, mat 格式）
            llm_provider: LLM提供商名称（默认qwen）
            docker_image: Docker镜像名称
            docker_timeout: Docker执行超时时间（秒）
        """
        self.data_file_path = data_file_path
        
        # 获取数据文件所在目录（用于挂载到Docker）
        import os
        from pathlib import Path
        data_path = Path(data_file_path).resolve()
        self.data_dir = str(data_path.parent)
        self.data_filename = data_path.name  # 纯文件名，用于LLM提示
        
        # 解析数据文件元数据
        logger.info(f"正在解析数据文件元数据: {data_file_path}")
        self.metadata: DatasetMetadata = DataProcessor.get_metadata(data_file_path)
        logger.info(f"元数据解析完成: {self.metadata.total_rows}行 x {self.metadata.total_columns}列")
        
        # 初始化LLM服务
        self.llm_client = LLMClient(provider=llm_provider)
        self.llm_service = LLMService(client=self.llm_client)
        
        # 初始化代码生成器（复用同一个LLM服务）
        self.code_generator = CodeGenerator(llm_service=self.llm_service)
        
        # 初始化Docker代码解释器，挂载数据文件所在目录
        self.docker_interpreter = DockerCodeInterpreter(
            image=docker_image,
            timeout=docker_timeout,
            work_dir=self.data_dir  # 挂载数据文件目录到 /workspace
        )

    def _analyze_task_type(self, task_title: str, task_description: str) -> TaskType:
        """
        使用LLM分析任务类型，判断是否需要编写代码
        
        Args:
            task_title: 任务标题
            task_description: 任务描述
            
        Returns:
            TaskType: 任务类型
        """
        # 构建用户提示词
        user_prompt = TASK_TYPE_USER_PROMPT_TEMPLATE.format(
            filename=self.metadata.filename,
            file_format=self.metadata.file_format,
            total_rows=self.metadata.total_rows,
            total_columns=self.metadata.total_columns,
            task_title=task_title,
            task_description=task_description
        )
        
        full_prompt = f"{TASK_TYPE_SYSTEM_PROMPT}\n\n{user_prompt}"
        
        try:
            response = self.llm_service.chat(prompt=full_prompt)
            response_text = response.strip()
            
            # 尝试解析JSON
            import json
            
            # 清理可能的markdown标记
            if response_text.startswith("```"):
                lines = response_text.splitlines()
                if lines: lines.pop(0)
                if lines and lines[-1].strip() == "```":
                    lines.pop()
                response_text = "\n".join(lines).strip()
            
            # 尝试找到JSON
            start = response_text.find("{")
            end = response_text.rfind("}")
            if start != -1 and end != -1:
                json_str = response_text[start:end+1]
                result = json.loads(json_str)
                task_type_str = result.get("task_type", "code_required")
                
                if task_type_str == "text_only":
                    logger.info(f"任务类型判断 (LLM): TEXT_ONLY")
                    return TaskType.TEXT_ONLY
                else:
                    logger.info(f"任务类型判断 (LLM): CODE_REQUIRED")
                    return TaskType.CODE_REQUIRED
            
        except Exception as e:
            logger.warning(f"LLM任务类型判断失败: {e}，默认使用CODE_REQUIRED")
        
        # 默认认为需要代码
        logger.info(f"任务类型判断: CODE_REQUIRED (默认)")
        return TaskType.CODE_REQUIRED

    def _execute_code_task(
        self,
        task_title: str,
        task_description: str,
        max_fix_attempts: int = 5
    ) -> TaskExecutionResult:
        """
        执行需要代码的任务
        
        Args:
            task_title: 任务标题
            task_description: 任务描述
            max_fix_attempts: 最大修复尝试次数，默认5次
        """
        # 1. 生成初始代码
        logger.info("正在生成代码...")
        code_response = self.code_generator.generate(
            metadata=self.metadata,
            task_title=task_title,
            task_description=task_description
        )
        
        if not code_response.code or not code_response.code.strip():
            return TaskExecutionResult(
                task_type=TaskType.CODE_REQUIRED,
                success=False,
                error_message="代码生成失败：LLM未返回有效代码"
            )
        
        current_code = code_response.code
        code_description = code_response.description
        total_attempts = 0
        
        # 2. 执行代码，失败则修复重试，最多 max_fix_attempts 次
        for attempt in range(1, max_fix_attempts + 1):
            total_attempts = attempt
            logger.info(f"执行代码 (尝试 {attempt}/{max_fix_attempts})...")
            
            exec_result = self.docker_interpreter.run_python_code(current_code)
            
            # 执行成功，直接返回
            if exec_result.status == "success":
                logger.info(f"代码执行成功 (第 {attempt} 次尝试)")
                return TaskExecutionResult(
                    task_type=TaskType.CODE_REQUIRED,
                    success=True,
                    final_code=current_code,
                    code_description=code_description,
                    code_output=exec_result.output,
                    code_error=exec_result.error if exec_result.error else None,
                    total_attempts=total_attempts
                )
            
            # 执行失败，如果还有重试机会则修复代码
            logger.warning(f"代码执行失败 (尝试 {attempt}): {exec_result.error}")
            
            if attempt < max_fix_attempts:
                logger.info(f"调用fix_code修复代码...")
                error_info = f"Exit Code: {exec_result.exit_code}\nStderr: {exec_result.error}\nStdout: {exec_result.output}"
                fix_response = self.code_generator.fix_code(
                    metadata=self.metadata,
                    task_title=task_title,
                    task_description=task_description,
                    code=current_code,
                    error=error_info,
                    max_retries=3
                )
                
                if fix_response.code and fix_response.code.strip():
                    current_code = fix_response.code
                    code_description = fix_response.description
                else:
                    logger.warning("fix_code未返回有效代码，使用原代码继续尝试")
        
        # 所有尝试都失败
        logger.error(f"代码执行失败，已尝试 {max_fix_attempts} 次")
        return TaskExecutionResult(
            task_type=TaskType.CODE_REQUIRED,
            success=False,
            final_code=current_code,
            code_description=code_description,
            code_output=exec_result.output,
            code_error=exec_result.error,
            total_attempts=total_attempts,
            error_message=f"代码执行失败: 已尝试 {max_fix_attempts} 次仍未成功"
        )

    def _execute_text_task(
        self,
        task_title: str,
        task_description: str
    ) -> TaskExecutionResult:
        """
        执行纯文本任务（不需要代码）
        """
        prompt = TEXT_TASK_PROMPT_TEMPLATE.format(
            filename=self.metadata.filename,
            file_format=self.metadata.file_format,
            total_rows=self.metadata.total_rows,
            total_columns=self.metadata.total_columns,
            cols_text=self._format_columns_for_prompt(),
            task_title=task_title,
            task_description=task_description
        )
        
        response = self.llm_service.chat(prompt=prompt)
        return TaskExecutionResult(
            task_type=TaskType.TEXT_ONLY,
            success=True,
            text_response=response
        )

    def _format_columns_for_prompt(self) -> str:
        """格式化列信息用于提示词"""
        lines = []
        for col in self.metadata.columns[:20]:
            lines.append(f"- {col.name} ({col.dtype}): 样例值 {col.sample_values[:3]}")
        if len(self.metadata.columns) > 20:
            lines.append(f"... (还有 {len(self.metadata.columns) - 20} 列)")
        return "\n".join(lines)

    def execute(
        self,
        task_title: str,
        task_description: str,
        force_code: Optional[bool] = None
    ) -> TaskExecutionResult:
        """
        执行任务的主入口
        自动判断任务类型并执行相应的处理流程。
        """
        logger.info(f"开始执行任务: {task_title}")
        
        # 判断任务类型
        if force_code is True:
            task_type = TaskType.CODE_REQUIRED
            logger.info("任务类型: CODE_REQUIRED (强制指定)")
        elif force_code is False:
            task_type = TaskType.TEXT_ONLY
            logger.info("任务类型: TEXT_ONLY (强制指定)")
        else:
            task_type = self._analyze_task_type(task_title, task_description)
        
        # 根据任务类型执行
        if task_type == TaskType.CODE_REQUIRED:
            result = self._execute_code_task(task_title, task_description)
        else:
            result = self._execute_text_task(task_title, task_description)
        
        logger.info(f"任务执行完成: success={result.success}")
        return result


# ============================================================
# 便捷函数
# ============================================================

def execute_task(
    data_file_path: str,
    task_title: str,
    task_description: str,
    **kwargs
) -> TaskExecutionResult:
    """
    便捷函数：一次性执行任务
    
    Args:
        data_file_path: 数据文件路径
        task_title: 任务标题
        task_description: 任务描述
        **kwargs: 传递给TaskExecutor的其他参数
        
    Returns:
        TaskExecutionResult: 任务执行结果
    """
    executor = TaskExecutor(data_file_path=data_file_path, **kwargs)
    return executor.execute(task_title=task_title, task_description=task_description)
