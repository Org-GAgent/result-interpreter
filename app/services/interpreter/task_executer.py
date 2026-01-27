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
from .metadata import FileMetadata, LLMMetadataParser, get_metadata
from .coder import CodeGenerator, CodeTaskResponse
from .docker_interpreter import DockerCodeInterpreter, CodeExecutionResult
from .prompts.task_executer import (
    TASK_TYPE_SYSTEM_PROMPT,
    TASK_TYPE_USER_PROMPT_TEMPLATE,
    TEXT_TASK_PROMPT_TEMPLATE,
    INFO_GATHERING_SYSTEM_PROMPT,
    INFO_GATHERING_USER_PROMPT_TEMPLATE
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
    
    # 可视化相关
    has_visualization: bool = Field(default=False, description="是否包含可视化")
    visualization_purpose: Optional[str] = Field(None, description="可视化目的：为什么画这个图，想分析什么")
    visualization_analysis: Optional[str] = Field(None, description="可视化分析：图表展示什么结果，特征，计算公式等")
    
    # 文本相关（仅当 task_type == TEXT_ONLY 时有值）
    text_response: Optional[str] = Field(None, description="LLM直接回答的文本")
    
    # 信息收集相关
    gathered_info: Optional[str] = Field(None, description="信息收集阶段获取的额外数据信息")
    info_gathering_rounds: int = Field(0, description="信息收集轮次")
    
    # 通用
    error_message: Optional[str] = Field(None, description="系统级错误信息")


class TaskExecutor:
    """
    任务执行器
    
    负责协调代码生成器(CodeGenerator)和代码解释器(DockerCodeInterpreter)，
    实现任务的自动判断、代码生成、执行和错误修复的完整流程。
    
    使用示例:
        executor = TaskExecutor(data_file_paths=["/path/to/data1.csv", "/path/to/data2.csv"])
        result = executor.execute(
            task_title="计算平均值",
            task_description="计算销售额的平均值并绘制柱状图"
        )
    """

    def __init__(
        self,
        data_file_paths: List[str],
        llm_provider: str = "qwen",
        docker_image: str = "agent-plotter",
        docker_timeout: int = 60,
        output_dir: Optional[str] = None
    ):
        """
        初始化任务执行器
        
        Args:
            data_file_paths: 数据文件路径列表（支持 csv, tsv, mat 格式）
            llm_provider: LLM提供商名称（默认qwen）
            docker_image: Docker镜像名称
            docker_timeout: Docker执行超时时间（秒）
            output_dir: 输出目录，Docker生成的文件将保存在此目录
                       如果不指定，则使用数据文件所在目录
        """
        # 兼容单个文件路径的情况
        if isinstance(data_file_paths, str):
            data_file_paths = [data_file_paths]
        
        self.data_file_paths = data_file_paths
        
        # 获取数据文件所在目录
        import os
        from pathlib import Path
        data_path = Path(data_file_paths[0]).resolve()
        self.data_dir = str(data_path.parent)
        self.data_filenames = [Path(fp).name for fp in data_file_paths]  # 纯文件名列表
        
        # 设置输出目录
        if output_dir:
            self.output_dir = str(Path(output_dir).resolve())
            # 确保输出目录存在
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        else:
            self.output_dir = self.data_dir
        
        # 解析所有数据文件的元数据
        self.metadata_list: List[FileMetadata] = []
        self.metadata_parser = LLMMetadataParser(llm_client=LLMClient(provider=llm_provider))
        
        for fp in data_file_paths:
            logger.info(f"正在解析数据文件元数据: {fp}")
            # 使用新的 LLM 元数据解析器
            metadata = self.metadata_parser.parse(fp)
            self.metadata_list.append(metadata)
            
            # 从 parsed_content 获取统计信息
            parsed = metadata.parsed_content or {}
            rows = parsed.get('total_rows', 'N/A')
            cols = parsed.get('total_columns', 'N/A')
            logger.info(f"元数据解析完成: {metadata.filename} - {rows}行 x {cols}列")
        
        # 初始化LLM服务
        self.llm_client = LLMClient(provider=llm_provider)
        self.llm_service = LLMService(client=self.llm_client)
        
        # 初始化代码生成器（复用同一个LLM服务）
        self.code_generator = CodeGenerator(llm_service=self.llm_service)
        
        # 初始化Docker代码解释器
        # work_dir: output_dir，挂载到 /workspace
        #   - LLM生成的代码会保存文件到 results/ 子目录
        #   - 所以实际文件位置: /workspace/results/ -> output_dir/results/
        # data_dir: 数据目录，挂载到 /data（用于读取数据文件）
        self.docker_interpreter = DockerCodeInterpreter(
            image=docker_image,
            timeout=docker_timeout,
            work_dir=self.output_dir,  # output_dir 挂载到 /workspace
            data_dir=self.data_dir     # 数据目录挂载到 /data
        )
        
        logger.info(f"TaskExecutor 初始化: data_dir={self.data_dir}, output_dir={self.output_dir}")

    def _format_datasets_summary(self) -> str:
        """格式化所有数据集的摘要信息"""
        summaries = []
        for i, metadata in enumerate(self.metadata_list, 1):
            parsed = metadata.parsed_content or {}
            total_rows = parsed.get('total_rows', 'N/A')
            total_columns = parsed.get('total_columns', 'N/A')
            columns = parsed.get('columns', [])
            
            # 构建样例信息
            sample_info = "; ".join(
                f"{col.get('name', 'unknown')}: {col.get('sample_values', [])[:3]}"
                for col in columns[:3]
                if isinstance(col, dict)
            ) if columns else "N/A"
            
            summary = f"""### 数据集 {i}: {metadata.filename}
- 格式: {metadata.file_extension}
- 行数: {total_rows}
- 列数: {total_columns}
- 数据样例(sample size: 3*3): {sample_info}"""
            summaries.append(summary)
        return "\n\n".join(summaries)

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
        datasets_summary = self._format_datasets_summary()
        user_prompt = TASK_TYPE_USER_PROMPT_TEMPLATE.format(
            datasets_info=datasets_summary,
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

    def _gather_additional_info(
        self,
        task_title: str,
        task_description: str,
        subtask_results: str = "",
        max_rounds: int = 3,
        max_fix_attempts: int = 3
    ) -> tuple[str, int]:
        """
        信息收集阶段：循环询问LLM是否需要更多数据信息
        
        Args:
            task_title: 任务标题
            task_description: 任务描述
            subtask_results: 子任务结果（可选）
            max_rounds: 最大收集轮次，防止无限循环
            max_fix_attempts: 每轮代码执行失败时的最大修复尝试次数
            
        Returns:
            tuple[str, int]: (收集到的所有额外信息, 收集轮次)
        """
        gathered_info_list = []
        rounds = 0
        
        datasets_info = self._format_all_datasets_detail()
        
        for round_num in range(1, max_rounds + 1):
            rounds = round_num
            
            # 构建已收集信息的文本
            if gathered_info_list:
                gathered_info_text = "\n\n---\n\n".join([
                    f"### Round {i+1} Result:\n{info}" 
                    for i, info in enumerate(gathered_info_list)
                ])
            else:
                gathered_info_text = "(No additional information gathered yet)"
            
            # 构建提示词
            user_prompt = INFO_GATHERING_USER_PROMPT_TEMPLATE.format(
                task_title=task_title,
                task_description=task_description,
                subtask_results=subtask_results if subtask_results else "(No sub-task results)",
                datasets_info=datasets_info,
                gathered_info=gathered_info_text
            )
            
            full_prompt = f"{INFO_GATHERING_SYSTEM_PROMPT}\n\n{user_prompt}"
            
            logger.info(f"信息收集第 {round_num} 轮: 询问LLM是否需要更多信息...")
            
            try:
                response = self.llm_service.chat(prompt=full_prompt)
                response_text = response.strip()
                
                # 解析JSON响应
                import json
                
                # 清理可能的markdown标记
                if response_text.startswith("```"):
                    lines = response_text.splitlines()
                    if lines: lines.pop(0)
                    if lines and lines[-1].strip() == "```":
                        lines.pop()
                    response_text = "\n".join(lines).strip()
                
                # 提取JSON
                start = response_text.find("{")
                end = response_text.rfind("}")
                if start != -1 and end != -1:
                    json_str = response_text[start:end+1]
                    result = json.loads(json_str)
                    
                    need_more_info = result.get("need_more_info", False)
                    code = result.get("code", "")
                    
                    if not need_more_info:
                        logger.info(f"信息收集完成: LLM表示不需要更多信息 (共 {round_num} 轮)")
                        break
                    
                    if code and code.strip():
                        # 执行代码，失败则尝试修复
                        current_code = code
                        exec_success = False
                        
                        for fix_attempt in range(1, max_fix_attempts + 1):
                            logger.info(f"信息收集第 {round_num} 轮: 执行代码 (尝试 {fix_attempt}/{max_fix_attempts})...")
                            exec_result = self.docker_interpreter.run_python_code(current_code)
                            
                            if exec_result.status == "success":
                                info_text = f"**Code:**\n```python\n{current_code}\n```\n\n**Output:**\n```\n{exec_result.output}\n```"
                                gathered_info_list.append(info_text)
                                logger.info(f"信息收集第 {round_num} 轮: 成功获取信息")
                                exec_success = True
                                break
                            else:
                                # 执行失败，尝试修复
                                logger.warning(f"信息收集第 {round_num} 轮: 代码执行失败 (尝试 {fix_attempt}): {exec_result.error}")
                                
                                if fix_attempt < max_fix_attempts:
                                    logger.info(f"信息收集第 {round_num} 轮: 调用fix_code修复代码...")
                                    error_info = f"Exit Code: {exec_result.exit_code}\nStderr: {exec_result.error}\nStdout: {exec_result.output}"
                                    
                                    # 构建简化的任务描述用于修复
                                    fix_task_desc = f"获取数据信息以辅助完成任务: {task_title}"
                                    
                                    fix_response = self.code_generator.fix_code(
                                        metadata_list=self.metadata_list,
                                        task_title="信息收集",
                                        task_description=fix_task_desc,
                                        code=current_code,
                                        error=error_info,
                                        max_retries=5
                                    )
                                    
                                    if fix_response.code and fix_response.code.strip():
                                        current_code = fix_response.code
                                        logger.info(f"信息收集第 {round_num} 轮: 代码已修复，准备重试")
                                    else:
                                        logger.warning(f"信息收集第 {round_num} 轮: fix_code未返回有效代码")
                                        break
                        
                        if not exec_success:
                            # 所有修复尝试都失败，记录错误信息继续下一轮
                            info_text = f"**Code (Failed after {max_fix_attempts} attempts):**\n```python\n{current_code}\n```\n\n**Last Error:**\n```\n{exec_result.error}\n```"
                            gathered_info_list.append(info_text)
                            logger.warning(f"信息收集第 {round_num} 轮: 代码执行失败，已尝试 {max_fix_attempts} 次修复")
                    else:
                        logger.warning(f"信息收集第 {round_num} 轮: need_more_info=True但未提供代码")
                        break
                else:
                    logger.warning(f"信息收集第 {round_num} 轮: 无法解析LLM响应")
                    break
                    
            except Exception as e:
                logger.warning(f"信息收集第 {round_num} 轮出错: {e}")
                break
        
        # 合并所有收集到的信息
        if gathered_info_list:
            final_gathered_info = "\n\n---\n\n".join([
                f"### Gathered Information Round {i+1}:\n{info}" 
                for i, info in enumerate(gathered_info_list)
            ])
        else:
            final_gathered_info = ""
        
        return final_gathered_info, rounds

    def _execute_code_task(
        self,
        task_title: str,
        task_description: str,
        subtask_results: str = "",
        gathered_info: str = "",
        max_fix_attempts: int = 5,
        is_visualization: bool = False
    ) -> TaskExecutionResult:
        """
        执行需要代码的任务
        
        Args:
            task_title: 任务标题
            task_description: 任务描述
            subtask_results: 子任务结果
            gathered_info: 信息收集阶段获取的额外信息
            max_fix_attempts: 最大修复尝试次数，默认5次
            is_visualization: 是否为可视化任务，如果是则使用 visualization skill
        """
        # 1. 生成初始代码（包含收集到的额外信息）
        logger.info("正在生成代码...")
        
        # 构建增强的任务描述，包含子任务结果和收集的信息
        enhanced_description = task_description
        if subtask_results:
            enhanced_description += f"\n\n## Sub-task Results:\n{subtask_results}"
        if gathered_info:
            enhanced_description += f"\n\n## Additional Gathered Information:\n{gathered_info}"
        
        # 根据任务类型选择不同的生成方法
        if is_visualization:
            logger.info("使用 visualization skill 生成可视化代码...")
            code_response = self.code_generator.generate_visualization(
                metadata_list=self.metadata_list,
                task_title=task_title,
                task_description=enhanced_description
            )
        else:
            code_response = self.code_generator.generate(
                metadata_list=self.metadata_list,
                task_title=task_title,
                task_description=enhanced_description
            )
        
        if not code_response.code or not code_response.code.strip():
            return TaskExecutionResult(
                task_type=TaskType.CODE_REQUIRED,
                success=False,
                error_message="代码生成失败：LLM未返回有效代码"
            )
        
        current_code = code_response.code
        code_description = code_response.description
        # 保存可视化相关字段
        has_visualization = code_response.has_visualization
        visualization_purpose = code_response.visualization_purpose
        visualization_analysis = code_response.visualization_analysis
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
                    total_attempts=total_attempts,
                    has_visualization=has_visualization,
                    visualization_purpose=visualization_purpose,
                    visualization_analysis=visualization_analysis
                )
            
            # 执行失败，如果还有重试机会则修复代码
            logger.warning(f"代码执行失败 (尝试 {attempt}): {exec_result.error}")
            
            if attempt < max_fix_attempts:
                logger.info(f"调用fix_code修复代码...")
                error_info = f"Exit Code: {exec_result.exit_code}\nStderr: {exec_result.error}\nStdout: {exec_result.output}"
                
                # 根据任务类型选择不同的修复方法
                if is_visualization:
                    fix_response = self.code_generator.fix_visualization_code(
                        metadata_list=self.metadata_list,
                        task_title=task_title,
                        task_description=task_description,
                        code=current_code,
                        error=error_info,
                        max_retries=3
                    )
                else:
                    fix_response = self.code_generator.fix_code(
                        metadata_list=self.metadata_list,
                        task_title=task_title,
                        task_description=task_description,
                        code=current_code,
                        error=error_info,
                        max_retries=3
                    )
                
                if fix_response.code and fix_response.code.strip():
                    current_code = fix_response.code
                    code_description = fix_response.description
                    # 更新可视化字段
                    has_visualization = fix_response.has_visualization
                    visualization_purpose = fix_response.visualization_purpose
                    visualization_analysis = fix_response.visualization_analysis
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
            has_visualization=has_visualization,
            visualization_purpose=visualization_purpose,
            visualization_analysis=visualization_analysis,
            error_message=f"代码执行失败: 已尝试 {max_fix_attempts} 次仍未成功"
        )

    def _execute_text_task(
        self,
        task_title: str,
        task_description: str,
        subtask_results: str = "",
        gathered_info: str = ""
    ) -> TaskExecutionResult:
        """
        执行纯文本任务（不需要代码）
        """
        datasets_detail = self._format_all_datasets_detail()
        prompt = TEXT_TASK_PROMPT_TEMPLATE.format(
            datasets_info=datasets_detail,
            subtask_results=subtask_results if subtask_results else "(No sub-task results)",
            gathered_info=gathered_info if gathered_info else "(No additional information gathered)",
            task_title=task_title,
            task_description=task_description
        )
        
        response = self.llm_service.chat(prompt=prompt)
        return TaskExecutionResult(
            task_type=TaskType.TEXT_ONLY,
            success=True,
            text_response=response,
            gathered_info=gathered_info if gathered_info else None
        )

    def _format_all_datasets_detail(self) -> str:
        """格式化所有数据集的详细信息（包含列信息）"""
        details = []
        for i, metadata in enumerate(self.metadata_list, 1):
            cols_text = self._format_columns_for_metadata(metadata)
            parsed = metadata.parsed_content or {}
            total_rows = parsed.get('total_rows', 'N/A')
            total_columns = parsed.get('total_columns', 'N/A')
            shape = parsed.get('shape', None)
            dtype = parsed.get('dtype', None)
            
            detail = f"""### 数据集 {i}: {metadata.filename}
- 文件路径: {metadata.file_path}
- 格式: {metadata.file_extension}
- 文件大小: {metadata.file_size_bytes} bytes
- 是否二进制: {metadata.is_binary}
- 编码: {metadata.encoding or 'N/A'}"""
            
            if shape:
                detail += f"\n- Shape: {shape}"
            if dtype:
                detail += f"\n- Data Type: {dtype}"
            if total_rows != 'N/A':
                detail += f"\n- 行数: {total_rows}"
            if total_columns != 'N/A':
                detail += f"\n- 列数: {total_columns}"
            if cols_text:
                detail += f"\n- 列信息:\n{cols_text}"
            
            details.append(detail)
        return "\n\n".join(details)

    def _format_columns_for_metadata(self, metadata: FileMetadata) -> str:
        """格式化单个数据集的列信息"""
        lines = []
        parsed = metadata.parsed_content or {}
        columns = parsed.get('columns', [])
        
        for col in columns[:20]:
            if isinstance(col, dict):
                name = col.get('name', 'unknown')
                dtype = col.get('dtype', 'unknown')
                sample = col.get('sample_values', [])[:3]
            else:
                name = str(col)
                dtype = 'unknown'
                sample = []
            lines.append(f"  - {name} ({dtype}): 样例值 {sample}")
        
        if len(columns) > 20:
            lines.append(f"  ... (还有 {len(columns) - 20} 列)")
        return "\n".join(lines)

    def execute(
        self,
        task_title: str,
        task_description: str,
        subtask_results: str = "",
        force_code: Optional[bool] = None,
        skip_info_gathering: bool = False,
        is_visualization: bool = False
    ) -> TaskExecutionResult:
        """
        执行任务的主入口
        自动判断任务类型并执行相应的处理流程。
        
        Args:
            task_title: 任务标题
            task_description: 任务描述
            subtask_results: 子任务结果（用于非叶子节点）
            force_code: 强制指定任务类型（True=代码任务, False=文本任务, None=自动判断）
            skip_info_gathering: 是否跳过信息收集阶段
            is_visualization: 是否为可视化任务，如果是则使用 visualization skill 生成代码
        """
        logger.info(f"开始执行任务: {task_title}")
        
        # 1. 信息收集阶段
        gathered_info = ""
        info_rounds = 0
        if not skip_info_gathering:
            logger.info("开始信息收集阶段...")
            gathered_info, info_rounds = self._gather_additional_info(
                task_title=task_title,
                task_description=task_description,
                subtask_results=subtask_results
            )
            if gathered_info:
                logger.info(f"信息收集完成: 共 {info_rounds} 轮，获取了额外信息")
            else:
                logger.info(f"信息收集完成: 不需要额外信息")
        
        # 2. 判断任务类型
        if force_code is True:
            task_type = TaskType.CODE_REQUIRED
            logger.info("任务类型: CODE_REQUIRED (强制指定)")
        elif force_code is False:
            task_type = TaskType.TEXT_ONLY
            logger.info("任务类型: TEXT_ONLY (强制指定)")
        else:
            task_type = self._analyze_task_type(task_title, task_description)
        
        # 3. 根据任务类型执行
        if task_type == TaskType.CODE_REQUIRED:
            result = self._execute_code_task(
                task_title, 
                task_description,
                subtask_results=subtask_results,
                gathered_info=gathered_info,
                is_visualization=is_visualization
            )
        else:
            result = self._execute_text_task(
                task_title, 
                task_description,
                subtask_results=subtask_results,
                gathered_info=gathered_info
            )
        
        # 更新信息收集相关字段
        result.gathered_info = gathered_info if gathered_info else None
        result.info_gathering_rounds = info_rounds
        
        logger.info(f"任务执行完成: success={result.success}")
        return result


# ============================================================
# 便捷函数
# ============================================================

def execute_task(
    data_file_paths: List[str],
    task_title: str,
    task_description: str,
    subtask_results: str = "",
    skip_info_gathering: bool = False,
    is_visualization: bool = False,
    **kwargs
) -> TaskExecutionResult:
    """
    便捷函数：一次性执行任务
    
    Args:
        data_file_paths: 数据文件路径列表（也支持单个路径字符串）
        task_title: 任务标题
        task_description: 任务描述
        subtask_results: 子任务结果（可选）
        skip_info_gathering: 是否跳过信息收集阶段
        is_visualization: 是否为可视化任务，如果是则使用 visualization skill
        **kwargs: 传递给TaskExecutor的其他参数
        
    Returns:
        TaskExecutionResult: 任务执行结果
    """
    executor = TaskExecutor(data_file_paths=data_file_paths, **kwargs)
    return executor.execute(
        task_title=task_title, 
        task_description=task_description,
        subtask_results=subtask_results,
        skip_info_gathering=skip_info_gathering,
        is_visualization=is_visualization
    )
