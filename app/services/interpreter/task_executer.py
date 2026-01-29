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
from .venv_interpreter import VenvCodeInterpreter
from .prompts.task_executer import (
    TASK_TYPE_SYSTEM_PROMPT,
    TASK_TYPE_USER_PROMPT_TEMPLATE,
    TEXT_TASK_PROMPT_TEMPLATE,
    INFO_GATHERING_SYSTEM_PROMPT,
    INFO_GATHERING_USER_PROMPT_TEMPLATE
)
from .image_analyzer import ImageAnalyzer
from .prompts.data_summary_prompts import (
    ANALYSIS_PLANNING_SYSTEM_PROMPT,
    ANALYSIS_PLANNING_USER_PROMPT_TEMPLATE,
    DATA_SUMMARY_CODE_GENERATION_SYSTEM_PROMPT,
    DATA_SUMMARY_CODE_GENERATION_USER_PROMPT_TEMPLATE
)
from ..skills import SkillsLoader

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """任务类型枚举"""
    CODE_REQUIRED = "code_required"      # 需要编写代码的任务（计算、绘图、数据处理等）
    TEXT_ONLY = "text_only"              # 纯文本任务（解释、总结、问答等）
    DATA_SUMMARY = "data_summary"        # 数据总结任务（生成数据的文字分析总结）
    

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
        data_file_paths: Optional[List[str]] = None,
        data_dir: Optional[str] = None,
        llm_provider: str = "qwen",
        docker_image: str = "agent-plotter",
        docker_timeout: int = 60,
        output_dir: Optional[str] = None,
        interpreter_type: str = "docker",
        venv_path: Optional[str] = None
    ):
        """
        初始化任务执行器

        Args:
            data_file_paths: 数据文件路径列表（支持 csv, tsv, mat, npy 格式）
                           如果指定了 data_dir，则此参数可选
            data_dir: 数据目录路径，系统会自动发现该目录下的所有数据文件
                     优先使用此参数，如果不指定则使用 data_file_paths
            llm_provider: LLM提供商名称（默认qwen）
            docker_image: Docker镜像名称（当interpreter_type="docker"时使用）
            docker_timeout: 执行超时时间（秒）
            output_dir: 输出目录，生成的文件将保存在此目录
                       如果不指定，则使用数据目录
            interpreter_type: 代码执行器类型（"docker"或"venv"）
            venv_path: Python虚拟环境路径（当interpreter_type="venv"时使用）
        """
        import os
        from pathlib import Path

        # 如果指定了data_dir，自动发现所有数据文件
        if data_dir:
            data_dir_path = Path(data_dir).resolve()
            if not data_dir_path.exists():
                raise ValueError(f"数据目录不存在: {data_dir}")

            self.data_dir = str(data_dir_path)

            # Auto-discover all files in the data directory (no extension restriction)
            discovered_files = [p for p in data_dir_path.rglob('*') if p.is_file()]


            # Exclude common documentation files
            data_file_paths = [
                str(f) for f in discovered_files
                if not any(keyword in f.name.lower() for keyword in ['readme', 'license', 'changelog'])
            ]

            if not data_file_paths:
                logger.warning(f"在目录 {data_dir} 中未发现数据文件")
                data_file_paths = []
            else:
                logger.info(f"在目录 {data_dir} 中发现 {len(data_file_paths)} 个数据文件")
                for fp in data_file_paths:
                    logger.info(f"  - {Path(fp).name}")


        # 如果没有指定data_dir，使用传统的data_file_paths模式
        elif data_file_paths:
            # 兼容单个文件路径的情况
            if isinstance(data_file_paths, str):
                data_file_paths = [data_file_paths]

            data_path = Path(data_file_paths[0]).resolve()
            self.data_dir = str(data_path.parent)

        else:
            raise ValueError("必须指定 data_dir 或 data_file_paths 之一")

        self.data_file_paths = data_file_paths if data_file_paths else []
        self.data_filenames = [Path(fp).name for fp in self.data_file_paths]  # 纯文件名列表
        
        # 设置输出目录
        if output_dir:
            self.output_dir = str(Path(output_dir).resolve())
            # 确保输出目录存在
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        else:
            self.output_dir = self.data_dir

        # Load README.md as metadata description for text-only prompts (optional)
        self.metadata_description = ""
        try:
            readme_path = Path(self.data_dir) / "README.md"
            if readme_path.exists():
                self.metadata_description = readme_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to load README.md: {e}")
        
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
        
        
        # Analyze image files if present (vision model)
        self.image_descriptions = {}
        try:
            api_key = os.getenv("VISION_KEY")
            base_url = os.getenv("VISION_URL")
            model = os.getenv("VISION_MODEL")
            image_analyzer = ImageAnalyzer(api_key=api_key, base_url=base_url, model=model)
            image_exts = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
            max_images = int(os.getenv("IMAGE_MAX_COUNT", "5"))
            count = 0
            for fp in self.data_file_paths:
                p = Path(fp)
                if p.suffix.lower() in image_exts:
                    desc = image_analyzer.analyze(p, prompt="Describe the image in detail for data analysis context.")
                    self.image_descriptions[p.name] = desc
                    count += 1
                    if count >= max_images:
                        break
        except Exception as e:
            logger.warning(f"Image analysis skipped: {e}")

        if self.image_descriptions:
            parts = []
            for name, desc in self.image_descriptions.items():
                parts.append(f"- {name}: {desc}")
            image_section = "Image Descriptions:\\n" + "\\n".join(parts)
            if self.metadata_description:
                self.metadata_description += "\\n\\n" + image_section
            else:
                self.metadata_description = image_section

        self.skills_loader = SkillsLoader()
        available_skills_count = len(self.skills_loader._available_skills)
        if available_skills_count > 0:
            logger.info(f"发现 {available_skills_count} 个可用skills")
        else:
            logger.info("未找到skills，将使用通用分析方法")
        # 初始化LLM服务
        self.llm_client = LLMClient(provider=llm_provider)
        self.llm_service = LLMService(client=self.llm_client)

        # 初始化代码生成器（复用同一个LLM服务）
        self.code_generator = CodeGenerator(llm_service=self.llm_service)

        # 初始化代码解释器（根据类型选择）
        self.interpreter_type = interpreter_type.lower()
        if self.interpreter_type == "venv":
            logger.info(f"使用虚拟环境执行器 (venv_path={venv_path or 'system python'})")
            self.docker_interpreter = VenvCodeInterpreter(
                timeout=docker_timeout,
                work_dir=self.output_dir,
                data_dir=self.data_dir,
                venv_path=venv_path
            )
        else:
            logger.info(f"使用Docker执行器 (image={docker_image})")
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

        logger.info(f"TaskExecutor 初始化: interpreter={self.interpreter_type}, data_dir={self.data_dir}, output_dir={self.output_dir}")

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
        # 策略：前2次尝试小修复，第3次失败后让LLM重新思考整体策略
        error_history = []  # 记录所有失败历史

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

            # 执行失败，记录错误历史
            error_info = f"Exit Code: {exec_result.exit_code}\nStderr: {exec_result.error}\nStdout: {exec_result.output}"
            error_history.append({
                "attempt": attempt,
                "error": error_info,
                "code": current_code
            })
            logger.warning(f"代码执行失败 (尝试 {attempt}): {exec_result.error[:200]}...")

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
                    # 第3次及以后：让LLM重新思考整体策略
                    logger.info(f"⚠️ 前{attempt}次尝试均失败，让LLM重新思考分析策略...")

                    # 构建失败历史摘要
                    failure_summary = "\n\n".join([
                        f"### Attempt {h['attempt']}:\n**Error:**\n```\n{h['error'][:500]}\n```"
                        for h in error_history
                    ])

                    # 让LLM重新思考
                    rethink_prompt = f"""# Task Rethinking Required

**Original Task:** {task_title}

**Task Description:**
{task_description}

**Previous Attempts Failed ({len(error_history)} times):**

{failure_summary}

**Analysis:**
The previous approaches have all failed. You need to:
1. Analyze why the previous attempts failed
2. Reconsider the overall strategy
3. Generate a NEW approach that avoids the previous errors
4. Consider using different data files, different analysis methods, or simpler approaches

**Important:**
- Don't just fix syntax errors - rethink the ENTIRE approach
- Consider the error patterns - if file not found, maybe use different files
- Consider data shape mismatches - maybe the data structure is different than expected
- If encoding errors, use different output methods
- Simplify the analysis if needed

Now generate a COMPLETELY NEW code solution based on your rethinking:
"""

                    logger.info("Asking LLM to rethink the strategy with error context...")
                    rethink_response = self.code_generator.generate(
                        metadata_list=self.metadata_list,
                        task_title=f"[RETHINK] {task_title}",
                        task_description=rethink_prompt
                    )

                    if rethink_response.code and rethink_response.code.strip():
                        logger.info("✓ LLM提供了新的分析策略")
                        current_code = rethink_response.code
                        code_description = rethink_response.description
                        has_visualization = rethink_response.has_visualization
                        visualization_purpose = rethink_response.visualization_purpose
                        visualization_analysis = rethink_response.visualization_analysis
                    else:
                        logger.warning("LLM重新思考后仍未返回有效代码")
        
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
        metadata_desc = self.metadata_description if self.metadata_description else "(No README.md or metadata description file found)"

        prompt = TEXT_TASK_PROMPT_TEMPLATE.format(
            metadata_description=metadata_desc,
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

    def _execute_data_summary_task(
        self,
        task_title: str,
        task_description: str,
        subtask_results: str = "",
        gathered_info: str = "",
        max_fix_attempts: int = 5
    ) -> TaskExecutionResult:
        """
        执行数据总结任务（两阶段智能流程）

        阶段1: 分析规划 - LLM根据metadata决定应该分析什么
        阶段2: 代码生成和执行 - 根据分析策略生成针对性代码

        Args:
            task_title: 任务标题
            task_description: 任务描述
            subtask_results: 子任务结果
            gathered_info: 信息收集阶段获取的额外信息
            max_fix_attempts: 最大修复尝试次数
        """
        import json

        logger.info("=" * 60)
        logger.info("开始智能数据总结任务（两阶段流程）")
        logger.info("=" * 60)

        # 阶段1: 分析规划
        logger.info("\n阶段1: 分析规划 - LLM决定应该分析什么")
        logger.info("-" * 60)

        metadata_desc = self.metadata_description if self.metadata_description else "(No metadata description file found)"
        datasets_info = self._format_all_datasets_detail()

        # 获取可用skills列表
        available_skills_summary = self.skills_loader.get_skills_summary_for_llm()

        planning_prompt = ANALYSIS_PLANNING_USER_PROMPT_TEMPLATE.format(
            metadata_description=metadata_desc,
            datasets_info=datasets_info,
            task_description=task_description,
            subtask_results=subtask_results if subtask_results else "(No sub-task results)",
            available_skills=available_skills_summary
        )

        full_planning_prompt = f"{ANALYSIS_PLANNING_SYSTEM_PROMPT}\n\n{planning_prompt}"

        try:
            logger.info("调用LLM生成分析策略...")
            strategy_response = self.llm_service.chat(prompt=full_planning_prompt)
            strategy_text = strategy_response.strip()

            if strategy_text.startswith("```"):
                lines = strategy_text.splitlines()
                if lines: lines.pop(0)
                if lines and lines[-1].strip() == "```":
                    lines.pop()
                strategy_text = "\n".join(lines).strip()

            start = strategy_text.find("{")
            end = strategy_text.rfind("}")
            if start != -1 and end != -1:
                json_str = strategy_text[start:end+1]
                analysis_strategy = json.loads(json_str)
                logger.info(f"分析策略: {analysis_strategy.get('analysis_strategy', 'N/A')}")

                # 检查是否选择了skills
                selected_skills = analysis_strategy.get('selected_skills', [])
                if selected_skills:
                    logger.info(f"LLM选择了skills: {selected_skills}")
            else:
                logger.warning("无法解析分析策略JSON，使用默认策略")
                analysis_strategy = {
                    "analysis_strategy": "General data exploration",
                    "selected_skills": [],
                    "focus_areas": [{"aspect": "Basic statistics", "rationale": "Understand data", "key_questions": ["What are dimensions?"]}],
                    "avoid": []
                }
        except Exception as e:
            logger.error(f"分析规划阶段出错: {e}")
            analysis_strategy = {
                "analysis_strategy": "Basic exploration due to error",
                "selected_skills": [],
                "focus_areas": [{"aspect": "Data overview", "rationale": "Fallback", "key_questions": []}],
                "avoid": []
            }

        # 阶段1.5: 加载选中的skills
        skills_content = ""
        selected_skills = analysis_strategy.get('selected_skills', [])
        if selected_skills and isinstance(selected_skills, list):
            logger.info(f"\n加载选中的skills: {selected_skills}")
            skills_content = self.skills_loader.load_multiple_skills(selected_skills)
            if skills_content:
                logger.info(f"Skills内容已加载 ({len(skills_content)} 字符)")

        # 阶段2: 代码生成
        logger.info("\n阶段2: 代码生成 - 根据分析策略生成Python代码")
        logger.info("-" * 60)

        strategy_str = json.dumps(analysis_strategy, indent=2, ensure_ascii=False)

        # 构建代码生成提示词（如果有skills，附加skills内容）
        code_gen_base_prompt = DATA_SUMMARY_CODE_GENERATION_USER_PROMPT_TEMPLATE.format(
            analysis_strategy=strategy_str,
            metadata_description=metadata_desc,
            datasets_info=datasets_info,
            task_description=task_description
        )

        # 如果加载了skills，附加到提示词中
        if skills_content:
            full_code_gen_prompt = f"{DATA_SUMMARY_CODE_GENERATION_SYSTEM_PROMPT}\n\n{skills_content}\n\n---\n\n{code_gen_base_prompt}"
        else:
            full_code_gen_prompt = f"{DATA_SUMMARY_CODE_GENERATION_SYSTEM_PROMPT}\n\n{code_gen_base_prompt}"

        try:
            logger.info("调用LLM生成分析代码...")
            code_response = self.llm_service.chat(prompt=full_code_gen_prompt)
            code_text = code_response.strip()

            if code_text.startswith("```"):
                lines = code_text.splitlines()
                if lines: lines.pop(0)
                if lines and lines[-1].strip() == "```":
                    lines.pop()
                code_text = "\n".join(lines).strip()

            start = code_text.find("{")
            end = code_text.rfind("}")
            if start != -1 and end != -1:
                json_str = code_text[start:end+1]
                code_result = json.loads(json_str)
                current_code = code_result.get("code", "")
                code_description = code_result.get("description", "")

                if not current_code or not current_code.strip():
                    return TaskExecutionResult(
                        task_type=TaskType.DATA_SUMMARY,
                        success=False,
                        error_message="代码生成失败：LLM未返回有效代码"
                    )
                logger.info(f"代码生成成功: {code_description}")
            else:
                return TaskExecutionResult(
                    task_type=TaskType.DATA_SUMMARY,
                    success=False,
                    error_message="无法解析代码生成响应"
                )
        except Exception as e:
            logger.exception("代码生成阶段出错")
            return TaskExecutionResult(
                task_type=TaskType.DATA_SUMMARY,
                success=False,
                error_message=f"代码生成出错: {str(e)}"
            )

        # 阶段3: 执行代码
        logger.info("\n阶段3: 执行分析代码")
        logger.info("-" * 60)

        total_attempts = 0
        error_history = []  # 记录失败历史

        for attempt in range(1, max_fix_attempts + 1):
            total_attempts = attempt
            logger.info(f"执行代码 (尝试 {attempt}/{max_fix_attempts})...")

            exec_result = self.docker_interpreter.run_python_code(current_code)

            if exec_result.status == "success":
                logger.info(f"执行成功 (第 {attempt} 次尝试)")
                logger.info("=" * 60)
                return TaskExecutionResult(
                    task_type=TaskType.DATA_SUMMARY,
                    success=True,
                    final_code=current_code,
                    code_description=code_description,
                    code_output=exec_result.output,
                    code_error=exec_result.error if exec_result.error else None,
                    total_attempts=total_attempts,
                    text_response=exec_result.output,
                    has_visualization=False
                )

            # 记录失败历史
            error_info = f"Exit Code: {exec_result.exit_code}\nStderr: {exec_result.error}\nStdout: {exec_result.output}"
            error_history.append({
                "attempt": attempt,
                "error": error_info,
                "code": current_code
            })
            logger.warning(f"执行失败 (尝试 {attempt}): {exec_result.error[:200]}")

            if attempt < max_fix_attempts:
                # 决定修复策略
                if attempt <= 2:
                    # 前2次：小修复
                    logger.info("尝试小修复代码...")
                    fix_prompt = f"""Fix this Python code. Keep the analysis strategy.

**Strategy:** {strategy_str}
**Task:** {task_title}
**Failed Code:**
```python
{current_code}
```
**Error:**
```
{error_info}
```

Return JSON: {{"code": "fixed code", "description": "fix description"}}
"""
                    try:
                        fix_response = self.llm_service.chat(prompt=fix_prompt)
                        fix_text = fix_response.strip()
                        if fix_text.startswith("```"):
                            lines = fix_text.splitlines()
                            if lines: lines.pop(0)
                            if lines and lines[-1].strip() == "```":
                                lines.pop()
                            fix_text = "\n".join(lines).strip()
                        start = fix_text.find("{")
                        end = fix_text.rfind("}")
                        if start != -1 and end != -1:
                            fix_result = json.loads(fix_text[start:end+1])
                            fixed_code = fix_result.get("code", "")
                            if fixed_code and fixed_code.strip():
                                current_code = fixed_code
                                code_description = fix_result.get("description", code_description)
                                logger.info("代码已修复，准备重试")
                            else:
                                logger.warning("修复响应中无有效代码")
                                break
                        else:
                            logger.warning("无法解析修复响应")
                            break
                    except Exception as e:
                        logger.error(f"代码修复失败: {e}")
                        break

                else:
                    # 第3次及以后：让LLM重新思考整体策略
                    logger.info(f"⚠️ 前{attempt}次尝试均失败，让LLM重新思考数据分析策略...")

                    # 构建失败历史
                    failure_summary = "\n\n".join([
                        f"### Attempt {h['attempt']}:\n**Error:**\n```\n{h['error'][:500]}\n```"
                        for h in error_history
                    ])

                    # 让LLM重新规划策略并生成新代码
                    rethink_prompt = f"""# Data Analysis Strategy Rethinking Required

**Original Task:** {task_title}

**Task Description:**
{task_description}

**Original Analysis Strategy:**
{strategy_str}

**Previous Attempts Failed ({len(error_history)} times):**

{failure_summary}

**You need to:**
1. Analyze why the previous strategy failed
2. Design a COMPLETELY NEW analysis strategy
3. Consider different data files, different analysis methods, or simpler approaches
4. Generate new code based on the new strategy

**Available Data:**
{metadata_desc}

{datasets_info}

**Available Skills:**
{available_skills_summary}

Return JSON format:
{{
    "new_strategy": "Description of your new approach",
    "selected_skills": ["skill names if any"],
    "code": "Complete Python code",
    "description": "What this code does"
}}
"""
                    try:
                        logger.info("Asking LLM to completely rethink the data analysis strategy...")
                        rethink_response = self.llm_service.chat(prompt=rethink_prompt)
                        rethink_text = rethink_response.strip()

                        if rethink_text.startswith("```"):
                            lines = rethink_text.splitlines()
                            if lines: lines.pop(0)
                            if lines and lines[-1].strip() == "```":
                                lines.pop()
                            rethink_text = "\n".join(lines).strip()

                        start = rethink_text.find("{")
                        end = rethink_text.rfind("}")
                        if start != -1 and end != -1:
                            rethink_result = json.loads(rethink_text[start:end+1])
                            new_code = rethink_result.get("code", "")
                            if new_code and new_code.strip():
                                logger.info(f"✓ LLM提供了新策略: {rethink_result.get('new_strategy', 'N/A')}")
                                current_code = new_code
                                code_description = rethink_result.get("description", code_description)
                            else:
                                logger.warning("重新思考后仍未返回有效代码")
                                break
                        else:
                            logger.warning("无法解析重新思考响应")
                            break
                    except Exception as e:
                        logger.error(f"重新思考失败: {e}")
                        break

        logger.error(f"执行失败，已尝试 {max_fix_attempts} 次")
        logger.info("=" * 60)
        return TaskExecutionResult(
            task_type=TaskType.DATA_SUMMARY,
            success=False,
            final_code=current_code,
            code_description=code_description,
            code_output=exec_result.output,
            code_error=exec_result.error,
            total_attempts=total_attempts,
            error_message=f"执行失败: 已尝试 {max_fix_attempts} 次"
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
        force_task_type: Optional[str] = None,
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
            force_code: 强制指定任务类型（True=代码任务, False=文本任务, None=自动判断）（已弃用）
            force_task_type: 强制指定任务类型（"code_required"/"text_only"/"data_summary"）
            skip_info_gathering: 是否跳过信息收集阶段
            is_visualization: 是否为可视化任务，如果是则使用 visualization skill 生成代码
        """
        logger.info(f"开始执行任务: {task_title}")

        # 1. 信息收集阶段
        # 注意：在智能数据发现模式下，信息收集阶段默认禁用
        # 因为README.md已经提供了足够的上下文，且路径解析可能出错
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
        else:
            logger.info("信息收集阶段已跳过（在智能模式下推荐）")

        # 2. 判断任务类型
        if force_task_type:
            task_type = TaskType(force_task_type)
            logger.info(f"任务类型: {task_type.value} (强制指定)")
        elif force_code is True:
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
                gathered_info=gathered_info
            )
        elif task_type == TaskType.DATA_SUMMARY:
            result = self._execute_data_summary_task(
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
