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
    
    # 可视化相关
    has_visualization: bool = False
    visualization_purpose: Optional[str] = None
    visualization_analysis: Optional[str] = None
    
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
            data_file_paths=["/path/to/data1.csv", "/path/to/data2.csv"],
            output_dir="./results"
        )
        result = executor.execute()
    """

    def __init__(
        self,
        plan_id: int,
        data_file_paths: List[str],
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
            data_file_paths: 数据文件路径列表（支持多个文件）
            output_dir: 输出目录（存放生成的文件和报告）
            llm_provider: LLM提供商
            docker_image: Docker镜像
            docker_timeout: Docker超时时间
            repo: PlanRepository实例（可选，默认创建新实例）
        """
        self.plan_id = plan_id
        # 兼容单个文件路径的情况
        if isinstance(data_file_paths, str):
            data_file_paths = [data_file_paths]
        self.data_file_paths = data_file_paths
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化仓库
        self.repo = repo or PlanRepository()
        
        # 加载计划树
        logger.info(f"加载计划树: plan_id={plan_id}")
        self.tree: PlanTree = self.repo.get_plan_tree(plan_id)
        logger.info(f"计划树加载完成: {self.tree.title}, 共 {len(self.tree.nodes)} 个节点")
        
        # 初始化TaskExecutor（用于执行单个任务）
        # 传递 output_dir 以确保生成的文件保存到正确位置
        self.task_executor = TaskExecutor(
            data_file_paths=data_file_paths,
            llm_provider=llm_provider,
            docker_image=docker_image,
            docker_timeout=docker_timeout,
            output_dir=str(self.output_dir)  # Docker生成的文件将保存在此目录
        )
        
        # 初始化LLM服务（用于生成报告）
        self.llm_client = LLMClient(provider=llm_provider)
        self.llm_service = LLMService(client=self.llm_client)
        
        # 执行状态跟踪
        self._node_status: Dict[int, NodeExecutionStatus] = {}
        self._node_records: Dict[int, NodeExecutionRecord] = {}
        self._all_generated_files: List[str] = []
        
        # 分析报告路径
        self._analysis_report_path = self._init_analysis_report()

    def _init_analysis_report(self) -> Path:
        """初始化分析报告 Markdown 文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"analysis_report_plan{self.plan_id}_{timestamp}.md"
        report_path = self.output_dir / report_filename
        
        # 创建报告头部
        header = f"""# 数据分析报告

**计划ID**: {self.plan_id}
**计划标题**: {self.tree.title}
**生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

"""
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(header)
        
        logger.info(f"分析报告已创建: {report_path}")
        return report_path

    def _append_visualization_to_report(self, record: NodeExecutionRecord, new_files: List[str]):
        """
        将可视化分析内容追加到分析报告
        
        Args:
            record: 节点执行记录
            new_files: 新生成的文件列表
        """
        # 筛选出图片文件
        image_extensions = {'.png', '.jpg', '.jpeg', '.svg', '.pdf'}
        image_files = [f for f in new_files if Path(f).suffix.lower() in image_extensions]
        
        # 放宽条件：只要有图片文件、可视化目的、或可视化分析，就添加到报告
        if not image_files and not record.visualization_purpose and not record.visualization_analysis:
            logger.info(f"任务 [{record.node_id}] 没有可视化内容需要添加到报告")
            return
        
        # 构建报告内容
        content_parts = []
        content_parts.append(f"\n## 任务: {record.node_name}\n")
        content_parts.append(f"**任务ID**: {record.node_id}\n")
        content_parts.append(f"**执行时间**: {record.completed_at}\n\n")
        
        # 添加可视化目的
        if record.visualization_purpose:
            content_parts.append("### 分析目的\n\n")
            content_parts.append(f"{record.visualization_purpose}\n\n")
        
        # 添加图表（new_files 已经是相对路径格式 results/xxx.png）
        if image_files:
            content_parts.append("### 生成的图表\n\n")
            for img_path in image_files:
                img_name = Path(img_path).name
                # img_path 已经是相对路径 results/xxx.png，直接使用
                content_parts.append(f"![{img_name}]({img_path})\n\n")
        
        # 添加可视化分析
        if record.visualization_analysis:
            content_parts.append("### 图表分析\n\n")
            content_parts.append(f"{record.visualization_analysis}\n\n")
        
        # 添加分隔线
        content_parts.append("---\n")
        
        # 追加到报告文件
        with open(self._analysis_report_path, 'a', encoding='utf-8') as f:
            f.write(''.join(content_parts))
        
        logger.info(f"已将任务 [{record.node_id}] 的可视化分析添加到报告")

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

    def _all_children_done(self, node_id: int) -> bool:
        """
        检查节点的所有子节点是否都已结束（不管成功还是失败）
        
        "结束"状态包括: COMPLETED, FAILED, SKIPPED
        这允许父节点在某些子节点失败后仍然可以执行
        """
        children = self._get_children_ids(node_id)
        if not children:
            return True
        done_statuses = {NodeExecutionStatus.COMPLETED, NodeExecutionStatus.FAILED, NodeExecutionStatus.SKIPPED}
        return all(
            self._node_status.get(child_id) in done_statuses
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

    def _all_dependencies_done(self, node: PlanNode) -> bool:
        """
        检查节点的所有依赖是否都已结束（不管成功还是失败）
        """
        if not node.dependencies:
            return True
        done_statuses = {NodeExecutionStatus.COMPLETED, NodeExecutionStatus.FAILED, NodeExecutionStatus.SKIPPED}
        return all(
            self._node_status.get(dep_id) in done_statuses
            for dep_id in node.dependencies
        )

    def _can_execute_node(self, node_id: int) -> bool:
        """
        判断节点是否可以执行（纯 DAG 调度）
        
        可执行条件：
        1. 节点状态为 PENDING
        2. 所有依赖（dependencies）都已结束（COMPLETED/FAILED/SKIPPED）
        
        注意：
        - 不再要求子节点先完成，执行顺序完全由 dependencies 决定
        - 父子关系仅用于组织结构，不影响执行顺序
        - 即使依赖失败，当前节点仍会尝试执行
        """
        if self._node_status.get(node_id) != NodeExecutionStatus.PENDING:
            return False
        
        node = self.tree.nodes.get(node_id)
        if not node:
            return False
        
        # 纯 DAG 调度：只检查依赖是否都已结束
        if not self._all_dependencies_done(node):
            return False
        
        return True

    def _get_executable_nodes(self) -> List[int]:
        """获取当前可执行的所有节点（DAG 调度）"""
        executable = []
        for node_id in self.tree.nodes:
            if self._can_execute_node(node_id):
                executable.append(node_id)
        
        # 如果没有可执行节点，输出诊断信息
        if not executable:
            pending_nodes = [nid for nid, s in self._node_status.items() if s == NodeExecutionStatus.PENDING]
            if pending_nodes:
                logger.warning(f"[DAG调度] 存在 {len(pending_nodes)} 个 PENDING 节点但无法执行，诊断信息:")
                for nid in pending_nodes[:10]:  # 显示前10个
                    node = self.tree.nodes.get(nid)
                    if node:
                        deps = node.dependencies or []
                        deps_status = {dep: self._node_status.get(dep).value if self._node_status.get(dep) else "unknown" for dep in deps}
                        pending_deps = [dep for dep in deps if self._node_status.get(dep) == NodeExecutionStatus.PENDING]
                        logger.warning(
                            f"  节点 [{nid}] {node.name}: "
                            f"deps={deps}, deps_status={deps_status}, pending_deps={pending_deps}"
                        )
        
        return executable

    def _collect_dependency_context(self, node_id: int) -> str:
        """
        收集依赖节点的执行结果作为上下文（DAG 调度）
        
        同时收集：
        1. 显式依赖（dependencies）的执行结果
        2. 子节点（children）的执行结果（如果有的话）
        """
        node = self.tree.nodes.get(node_id)
        if not node:
            return ""
        
        context_parts = []
        collected_ids = set()
        
        # 1. 收集显式依赖的结果
        for dep_id in (node.dependencies or []):
            if dep_id in collected_ids:
                continue
            record = self._node_records.get(dep_id)
            if record and record.status == NodeExecutionStatus.COMPLETED:
                collected_ids.add(dep_id)
                dep_context = f"\n### 依赖任务 [{dep_id}] {record.node_name}\n"
                if record.code_description:
                    dep_context += f"**分析内容**: {record.code_description}\n"
                if record.code_output:
                    dep_context += f"**执行输出**:\n```\n{record.code_output[:2000]}\n```\n"
                if record.text_response:
                    dep_context += f"**文本结果**: {record.text_response[:2000]}\n"
                if record.generated_files:
                    dep_context += f"**生成文件**: {', '.join(record.generated_files)}\n"
                context_parts.append(dep_context)
        
        # 2. 收集子节点的结果（如果有且已完成）
        children = self._get_children_ids(node_id)
        for child_id in children:
            if child_id in collected_ids:
                continue
            record = self._node_records.get(child_id)
            if record and record.status == NodeExecutionStatus.COMPLETED:
                collected_ids.add(child_id)
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
        """
        扫描 results 目录下新生成的文件
        
        Returns:
            List[str]: 文件的相对路径列表（相对于 output_dir）
        """
        results_dir = self.output_dir / "results"
        if not results_dir.exists():
            return []
        
        files = []
        for f in results_dir.iterdir():
            if f.is_file():
                # 返回相对路径，格式为 results/filename.ext
                relative_path = f"results/{f.name}"
                files.append(relative_path)
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
        
        # 构建任务描述
        task_description = node.instruction or node.name
        
        # 收集依赖节点和子节点的执行结果作为上下文（DAG 调度）
        dependency_context = self._collect_dependency_context(node_id)
        
        # 记录执行前的文件
        files_before = set(self._scan_generated_files())
        
        # 使用 TaskExecutor 执行任务，依赖结果通过 subtask_results 参数传递
        result: TaskExecutionResult = self.task_executor.execute(
            task_title=node.name,
            task_description=task_description,
            subtask_results=dependency_context  # 传递依赖结果给信息收集和任务执行阶段
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
                # 保存可视化相关字段
                record.has_visualization = result.has_visualization
                record.visualization_purpose = result.visualization_purpose
                record.visualization_analysis = result.visualization_analysis
            else:
                record.text_response = result.text_response
            
            logger.info(f"节点 [{node_id}] 执行成功")
            
            # 如果有可视化或者生成了图片文件，更新分析报告
            # 条件放宽：有可视化标记，或者有新生成的图片文件
            image_extensions = {'.png', '.jpg', '.jpeg', '.svg', '.pdf'}
            has_image_files = any(Path(f).suffix.lower() in image_extensions for f in new_files)
            
            if record.has_visualization or has_image_files:
                logger.info(f"检测到可视化内容: has_visualization={record.has_visualization}, has_image_files={has_image_files}")
                self._append_visualization_to_report(record, new_files)
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
                "has_visualization": record.has_visualization,
                "visualization_purpose": record.visualization_purpose,
                "visualization_analysis": record.visualization_analysis,
                "error": record.error_message
            }, ensure_ascii=False)
        )
        
        return record

    def _map_db_status_to_execution_status(self, db_status: str) -> NodeExecutionStatus:
        """
        将数据库中的状态字符串映射到 NodeExecutionStatus 枚举
        
        Args:
            db_status: 数据库中存储的状态字符串
            
        Returns:
            NodeExecutionStatus: 对应的执行状态枚举
            
        注意：
            - "running" 状态被映射为 PENDING，因为这表示上次执行被中断，需要重新执行
            - 未知状态默认映射为 PENDING
        """
        status_lower = db_status.lower() if db_status else "pending"
        
        # "running" 表示上次执行被中断，应重新执行，所以映射为 PENDING
        if status_lower == "running":
            logger.info(f"数据库状态 'running' 映射为 PENDING（上次执行被中断）")
            return NodeExecutionStatus.PENDING
        
        status_mapping = {
            "pending": NodeExecutionStatus.PENDING,
            "completed": NodeExecutionStatus.COMPLETED,
            "failed": NodeExecutionStatus.FAILED,
            "skipped": NodeExecutionStatus.SKIPPED,
        }
        return status_mapping.get(status_lower, NodeExecutionStatus.PENDING)

    def _load_node_record_from_db(self, node: PlanNode) -> Optional[NodeExecutionRecord]:
        """
        从数据库中的 execution_result 字段加载节点执行记录
        
        Args:
            node: 计划节点
            
        Returns:
            NodeExecutionRecord 或 None（如果没有执行结果）
        """
        if not node.execution_result:
            return None
        
        try:
            exec_data = json.loads(node.execution_result)
            
            # 解析 task_type
            task_type = None
            if exec_data.get("task_type"):
                try:
                    task_type = TaskType(exec_data["task_type"])
                except ValueError:
                    pass
            
            record = NodeExecutionRecord(
                node_id=node.id,
                node_name=node.name,
                status=self._map_db_status_to_execution_status(node.status),
                task_type=task_type,
                code=exec_data.get("code"),
                code_output=exec_data.get("code_output"),
                code_description=exec_data.get("code_description"),
                has_visualization=exec_data.get("has_visualization", False),
                visualization_purpose=exec_data.get("visualization_purpose"),
                visualization_analysis=exec_data.get("visualization_analysis"),
                text_response=exec_data.get("text_response"),
                generated_files=exec_data.get("generated_files", []),
                error_message=exec_data.get("error"),
            )
            return record
        except Exception as e:
            logger.warning(f"加载节点 [{node.id}] 的执行记录失败: {e}")
            return None

    def _initialize_node_states(self):
        """
        根据数据库状态初始化所有节点状态，并加载已完成节点的执行记录
        """
        pending_count = 0
        completed_count = 0
        failed_count = 0
        other_count = 0
        
        for node_id, node in self.tree.nodes.items():
            status = self._map_db_status_to_execution_status(node.status)
            self._node_status[node_id] = status
            
            # 统计各状态数量
            if status == NodeExecutionStatus.PENDING:
                pending_count += 1
            elif status == NodeExecutionStatus.COMPLETED:
                completed_count += 1
                # 对于已完成的节点，加载其执行记录以便父节点可以收集上下文
                record = self._load_node_record_from_db(node)
                if record:
                    self._node_records[node_id] = record
                    logger.debug(f"节点 [{node_id}] 已从数据库加载执行记录")
            elif status == NodeExecutionStatus.FAILED:
                failed_count += 1
            else:
                other_count += 1
            
            logger.debug(f"节点 [{node_id}] {node.name}: 初始状态 = {status.value}")
        
        logger.info(f"节点状态初始化完成: pending={pending_count}, completed={completed_count}, failed={failed_count}, other={other_count}")

    def execute(self) -> PlanExecutionResult:
        """
        执行计划的主入口（DAG 调度）
        
        执行流程：
        1. 根据数据库状态初始化所有节点状态
        2. 循环找出可执行节点（所有依赖都已完成的节点）
        3. 执行节点
        4. 重复直到没有可执行节点
        5. 生成分析报告
        
        调度策略：
        - 纯 DAG 调度：只根据 dependencies 决定执行顺序
        - 父子关系仅用于组织结构，不影响执行顺序
        - 无依赖的节点可以并行执行
        
        Returns:
            PlanExecutionResult: 完整的执行结果
        """
        logger.info(f"开始执行计划（DAG调度）: {self.tree.title} (ID: {self.plan_id})")
        started_at = datetime.now().isoformat()
        
        # 根据数据库中的状态初始化所有节点状态，并加载已完成节点的执行记录
        self._initialize_node_states()
        
        # 循环执行直到没有可执行节点
        iteration = 0
        max_iterations = len(self.tree.nodes) * 2  # 防止死循环
        
        while iteration < max_iterations:
            iteration += 1
            executable = self._get_executable_nodes()
            
            if not executable:
                logger.info("[DAG调度] 没有更多可执行的节点")
                break
            
            logger.info(f"[DAG调度] 第 {iteration} 轮执行，可执行节点: {executable}")
            
            # DAG 调度：按节点 ID 排序保证稳定性（无依赖的节点按 ID 顺序执行）
            executable.sort(key=lambda nid: nid)
            
            # 逐个执行（可以改成并行执行无依赖关系的节点）
            for node_id in executable:
                self._execute_single_node(node_id)
        
        # 统计结果
        completed_count = sum(1 for s in self._node_status.values() if s == NodeExecutionStatus.COMPLETED)
        failed_count = sum(1 for s in self._node_status.values() if s == NodeExecutionStatus.FAILED)
        skipped_count = sum(1 for s in self._node_status.values() if s == NodeExecutionStatus.SKIPPED)
        
        completed_at = datetime.now().isoformat()
        
        # 完成分析报告（添加总结部分）
        self._finalize_analysis_report(completed_count, failed_count, skipped_count)
        
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
            report_path=str(self._analysis_report_path),
            started_at=started_at,
            completed_at=completed_at
        )
        
        logger.info(f"计划执行完成: 成功={result.success}, 完成={completed_count}, 失败={failed_count}")
        logger.info(f"分析报告已保存: {self._analysis_report_path}")
        
        return result

    def _finalize_analysis_report(self, completed: int, failed: int, skipped: int):
        """完成分析报告，添加执行总结"""
        summary = f"""
## 执行总结

| 指标 | 数值 |
|------|------|
| 总任务数 | {len(self.tree.nodes)} |
| 完成 | {completed} |
| 失败 | {failed} |
| 跳过 | {skipped} |

**完成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
        with open(self._analysis_report_path, 'a', encoding='utf-8') as f:
            f.write(summary)


# ============================================================
# 便捷函数
# ============================================================

def execute_plan(
    plan_id: int,
    data_file_paths: List[str],
    output_dir: str = "./results",
    **kwargs
) -> PlanExecutionResult:
    """
        plan_id: 计划ID
        data_file_paths: 数据文件路径列表（也支持单个路径字符串）
        output_dir: 输出目录
        **kwargs: 传递给 PlanExecutorInterpreter 的其他参数
    """
    executor = PlanExecutorInterpreter(
        plan_id=plan_id,
        data_file_paths=data_file_paths,
        output_dir=output_dir,
        **kwargs
    )
    return executor.execute()
