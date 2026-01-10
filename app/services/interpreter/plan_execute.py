"""
计划执行器模块

该模块负责执行整个计划树，从可执行的叶子节点开始，
按依赖关系逐层向上执行，最终完成根任务并生成分析报告。
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, Field

from ...llm import LLMClient
from app.services.llm.llm_service import LLMService
from app.repository.plan_repository import PlanRepository
from app.services.plans.plan_models import PlanNode, PlanTree
from .task_executer import TaskExecutor, TaskExecutionResult, TaskType

logger = logging.getLogger(__name__)


class NodeExecutionStatus(str, Enum):
    """节点执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class NodeExecutionRecord:
    """单个节点的执行记录"""
    node_id: int
    node_name: str
    status: NodeExecutionStatus
    task_type: Optional[TaskType] = None
    
    # 代码执行结果
    code: Optional[str] = None
    code_output: Optional[str] = None
    code_description: Optional[str] = None
    
    # 文本响应
    text_response: Optional[str] = None
    
    # 生成的文件
    generated_files: List[str] = field(default_factory=list)
    
    # 错误信息
    error_message: Optional[str] = None
    
    # 时间戳
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class PlanExecutionResult:
    """计划执行的完整结果"""
    plan_id: int
    plan_title: str
    success: bool
    total_nodes: int
    completed_nodes: int
    failed_nodes: int
    skipped_nodes: int
    
    # 所有节点的执行记录
    node_records: Dict[int, NodeExecutionRecord] = field(default_factory=dict)
    
    # 生成的所有文件
    all_generated_files: List[str] = field(default_factory=list)
    
    # 最终报告路径
    report_path: Optional[str] = None
    
    # 执行时间
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class PlanExecutorInterpreter:
    """
    计划执行器（解释器版本）
    
    负责执行整个计划树：
    1. 分析计划树结构，确定执行顺序
    2. 从叶子节点或子节点全部完成的节点开始执行
    3. 使用 TaskExecutor 执行每个任务节点
    4. 收集执行结果和生成的文件
    5. 生成最终的分析报告
    
    使用示例:
        executor = PlanExecutorInterpreter(
            plan_id=1,
            data_file_path="/path/to/data.csv",
            output_dir="./results"
        )
        result = executor.execute()
    """

    def __init__(
        self,
        plan_id: int,
        data_file_path: str,
        output_dir: str = "./results",
        llm_provider: str = "qwen",
        docker_image: str = "agent-plotter",
        docker_timeout: int = 120,
        repo: Optional[PlanRepository] = None
    ):
        """
        初始化计划执行器
        
        Args:
            plan_id: 计划ID
            data_file_path: 数据文件路径
            output_dir: 输出目录（存放生成的文件和报告）
            llm_provider: LLM提供商
            docker_image: Docker镜像
            docker_timeout: Docker超时时间
            repo: PlanRepository实例（可选，默认创建新实例）
        """
        self.plan_id = plan_id
        self.data_file_path = data_file_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化仓库
        self.repo = repo or PlanRepository()
        
        # 加载计划树
        logger.info(f"加载计划树: plan_id={plan_id}")
        self.tree: PlanTree = self.repo.get_plan_tree(plan_id)
        logger.info(f"计划树加载完成: {self.tree.title}, 共 {len(self.tree.nodes)} 个节点")
        
        # 初始化TaskExecutor（用于执行单个任务）
        self.task_executor = TaskExecutor(
            data_file_path=data_file_path,
            llm_provider=llm_provider,
            docker_image=docker_image,
            docker_timeout=docker_timeout
        )
        
        # 初始化LLM服务（用于生成报告）
        self.llm_client = LLMClient(provider=llm_provider)
        self.llm_service = LLMService(client=self.llm_client)
        
        # 执行状态跟踪
        self._node_status: Dict[int, NodeExecutionStatus] = {}
        self._node_records: Dict[int, NodeExecutionRecord] = {}
        self._all_generated_files: List[str] = []

    def _get_children_ids(self, node_id: int) -> List[int]:
        """获取节点的所有子节点ID"""
        return self.tree.children_ids(node_id)

    def _is_leaf_node(self, node_id: int) -> bool:
        """判断是否为叶子节点"""
        return len(self._get_children_ids(node_id)) == 0

    def _all_children_completed(self, node_id: int) -> bool:
        """检查节点的所有子节点是否都已完成"""
        children = self._get_children_ids(node_id)
        if not children:
            return True
        return all(
            self._node_status.get(child_id) == NodeExecutionStatus.COMPLETED
            for child_id in children
        )

    def _all_dependencies_completed(self, node: PlanNode) -> bool:
        """检查节点的所有依赖是否都已完成"""
        if not node.dependencies:
            return True
        return all(
            self._node_status.get(dep_id) == NodeExecutionStatus.COMPLETED
            for dep_id in node.dependencies
        )

    def _can_execute_node(self, node_id: int) -> bool:
        """
        判断节点是否可以执行
        
        可执行条件：
        1. 节点状态为 PENDING
        2. 是叶子节点，或所有子节点都已完成
        3. 所有依赖都已完成
        """
        if self._node_status.get(node_id) != NodeExecutionStatus.PENDING:
            return False
        
        node = self.tree.nodes.get(node_id)
        if not node:
            return False
        
        # 检查是否为叶子或子节点全部完成
        if not self._is_leaf_node(node_id) and not self._all_children_completed(node_id):
            return False
        
        # 检查依赖
        if not self._all_dependencies_completed(node):
            return False
        
        return True

    def _get_executable_nodes(self) -> List[int]:
        """获取当前可执行的所有节点"""
        executable = []
        for node_id in self.tree.nodes:
            if self._can_execute_node(node_id):
                executable.append(node_id)
        return executable

    def _collect_children_context(self, node_id: int) -> str:
        """收集子节点的执行结果作为上下文"""
        children = self._get_children_ids(node_id)
        if not children:
            return ""
        
        context_parts = []
        for child_id in children:
            record = self._node_records.get(child_id)
            if record and record.status == NodeExecutionStatus.COMPLETED:
                child_context = f"\n### 子任务 [{child_id}] {record.node_name}\n"
                if record.code_description:
                    child_context += f"**分析内容**: {record.code_description}\n"
                if record.code_output:
                    child_context += f"**执行输出**:\n```\n{record.code_output[:2000]}\n```\n"
                if record.text_response:
                    child_context += f"**文本结果**: {record.text_response[:2000]}\n"
                if record.generated_files:
                    child_context += f"**生成文件**: {', '.join(record.generated_files)}\n"
                context_parts.append(child_context)
        
        return "\n".join(context_parts)

    def _scan_generated_files(self) -> List[str]:
        """扫描 results 目录下新生成的文件"""
        results_dir = self.output_dir / "results"
        if not results_dir.exists():
            return []
        
        files = []
        for f in results_dir.iterdir():
            if f.is_file():
                files.append(str(f))
        return files

    def _execute_single_node(self, node_id: int) -> NodeExecutionRecord:
        """执行单个节点"""
        node = self.tree.nodes[node_id]
        logger.info(f"开始执行节点 [{node_id}] {node.name}")
        
        # 更新状态为运行中
        self._node_status[node_id] = NodeExecutionStatus.RUNNING
        
        record = NodeExecutionRecord(
            node_id=node_id,
            node_name=node.name,
            status=NodeExecutionStatus.RUNNING,
            started_at=datetime.now().isoformat()
        )
        
        # 构建任务描述，包含子节点上下文
        task_description = node.instruction or node.name
        children_context = self._collect_children_context(node_id)
        if children_context:
            task_description += f"\n\n## 子任务执行结果（作为参考）:\n{children_context}"
        
        # 记录执行前的文件
        files_before = set(self._scan_generated_files())
        
        # 使用 TaskExecutor 执行任务
        result: TaskExecutionResult = self.task_executor.execute(
            task_title=node.name,
            task_description=task_description
        )
        
        # 记录执行后的文件，找出新生成的
        files_after = set(self._scan_generated_files())
        new_files = list(files_after - files_before)
        
        # 更新记录
        record.task_type = result.task_type
        record.generated_files = new_files
        self._all_generated_files.extend(new_files)
        
        if result.success:
            record.status = NodeExecutionStatus.COMPLETED
            self._node_status[node_id] = NodeExecutionStatus.COMPLETED
            
            if result.task_type == TaskType.CODE_REQUIRED:
                record.code = result.final_code
                record.code_output = result.code_output
                record.code_description = result.code_description
            else:
                record.text_response = result.text_response
            
            logger.info(f"节点 [{node_id}] 执行成功")
        else:
            record.status = NodeExecutionStatus.FAILED
            self._node_status[node_id] = NodeExecutionStatus.FAILED
            record.error_message = result.error_message or result.code_error
            logger.error(f"节点 [{node_id}] 执行失败: {record.error_message}")
        
        record.completed_at = datetime.now().isoformat()
        self._node_records[node_id] = record
        
        # 更新数据库中的节点状态
        self.repo.update_task(
            plan_id=self.plan_id,
            task_id=node_id,
            status=record.status.value,
            execution_result=json.dumps({
                "task_type": record.task_type.value if record.task_type else None,
                "code": record.code,
                "code_description": record.code_description,
                "code_output": record.code_output,
                "text_response": record.text_response,
                "generated_files": record.generated_files,
                "error": record.error_message
            }, ensure_ascii=False)
        )
        
        return record

    def execute(self) -> PlanExecutionResult:
        """
        执行计划的主入口
        
        按以下顺序执行：
        1. 初始化所有节点状态为 PENDING
        2. 循环找出可执行节点（叶子或子节点全完成）
        3. 执行节点
        4. 重复直到没有可执行节点
        5. 生成分析报告
        
        Returns:
            PlanExecutionResult: 完整的执行结果
        """
        logger.info(f"开始执行计划: {self.tree.title} (ID: {self.plan_id})")
        started_at = datetime.now().isoformat()
        
        # 初始化所有节点状态
        for node_id in self.tree.nodes:
            self._node_status[node_id] = NodeExecutionStatus.PENDING
        
        # 循环执行直到没有可执行节点
        iteration = 0
        max_iterations = len(self.tree.nodes) * 2  # 防止死循环
        
        while iteration < max_iterations:
            iteration += 1
            executable = self._get_executable_nodes()
            
            if not executable:
                logger.info("没有更多可执行的节点")
                break
            
            logger.info(f"第 {iteration} 轮执行，可执行节点: {executable}")
            
            # 按深度从深到浅排序（先执行更深层的节点）
            executable.sort(key=lambda nid: -self.tree.nodes[nid].depth)
            
            # 逐个执行（可以改成并行执行叶子节点）
            for node_id in executable:
                self._execute_single_node(node_id)
        
        # 统计结果
        completed_count = sum(1 for s in self._node_status.values() if s == NodeExecutionStatus.COMPLETED)
        failed_count = sum(1 for s in self._node_status.values() if s == NodeExecutionStatus.FAILED)
        skipped_count = sum(1 for s in self._node_status.values() if s == NodeExecutionStatus.SKIPPED)
        
        completed_at = datetime.now().isoformat()
        
        # 构建结果
        result = PlanExecutionResult(
            plan_id=self.plan_id,
            plan_title=self.tree.title,
            success=(failed_count == 0),
            total_nodes=len(self.tree.nodes),
            completed_nodes=completed_count,
            failed_nodes=failed_count,
            skipped_nodes=skipped_count,
            node_records=self._node_records,
            all_generated_files=self._all_generated_files,
            started_at=started_at,
            completed_at=completed_at
        )
        
        logger.info(f"计划执行完成: 成功={result.success}, 完成={completed_count}, 失败={failed_count}")
        
        return result


# ============================================================
# 便捷函数
# ============================================================

def execute_plan(
    plan_id: int,
    data_file_path: str,
    output_dir: str = "./results",
    **kwargs
) -> PlanExecutionResult:
    """
    便捷函数：执行整个计划
    
    Args:
        plan_id: 计划ID
        data_file_path: 数据文件路径
        output_dir: 输出目录
        **kwargs: 传递给 PlanExecutorInterpreter 的其他参数
        
    Returns:
        PlanExecutionResult: 执行结果
    """
    executor = PlanExecutorInterpreter(
        plan_id=plan_id,
        data_file_path=data_file_path,
        output_dir=output_dir,
        **kwargs
    )
    return executor.execute()
