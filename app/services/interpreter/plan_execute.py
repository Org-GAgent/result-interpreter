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
from app.services.plans.tree_simplifier import TreeSimplifier, DAG, DAGNode
from .task_executer import TaskExecutor, TaskExecutionResult, TaskType
from .image_analyzer import ImageAnalyzer

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
        data_file_paths: Optional[List[str]] = None,
        data_dir: Optional[str] = None,
        output_dir: str = "./results",
        llm_provider: str = "qwen",
        docker_image: str = "agent-plotter",
        docker_timeout: int = 120,
        interpreter_type: str = "docker",
        venv_path: Optional[str] = None,
        repo: Optional[PlanRepository] = None
    ):
        """
        初始化计划执行器

        Args:
            plan_id: 计划ID
            data_file_paths: 数据文件路径列表（支持多个文件）
                           如果指定了 data_dir，则此参数可选
            data_dir: 数据目录路径，系统会自动发现该目录下的所有数据文件
                     优先使用此参数，如果不指定则使用 data_file_paths
            output_dir: 输出目录（存放生成的文件和报告）
            llm_provider: LLM提供商
            docker_image: Docker镜像
            docker_timeout: 执行超时时间
            interpreter_type: 代码执行器类型（"docker"或"venv"）
            venv_path: Python虚拟环境路径（当interpreter_type="venv"时使用）
            repo: PlanRepository实例（可选，默认创建新实例）
        """
        self.plan_id = plan_id

        # 兼容单个文件路径的情况
        if data_file_paths and isinstance(data_file_paths, str):
            data_file_paths = [data_file_paths]

        self.data_file_paths = data_file_paths
        self.data_dir = data_dir
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 初始化仓库
        self.repo = repo or PlanRepository()

        # 加载计划树
        logger.info(f"加载计划树: plan_id={plan_id}")
        self.tree: PlanTree = self.repo.get_plan_tree(plan_id)
        logger.info(f"计划树加载完成: {self.tree.title}, 共 {len(self.tree.nodes)} 个节点")
        
        # 转换为 DAG 并计算拓扑顺序（反向：从叶子到根，先执行子任务）
        simplifier = TreeSimplifier()
        self.dag: DAG = simplifier.tree_to_dag(self.tree)
        try:
            # Prefer dependency-based order if dependencies exist
            dep_edges = []
            for nid, node in self.tree.nodes.items():
                for dep_id in (node.dependencies or []):
                    dep_edges.append((dep_id, nid))

            if dep_edges:
                # Kahn topological sort over dependency edges (dep -> node)
                nodes = sorted(self.tree.nodes.keys())
                indeg = {n: 0 for n in nodes}
                adj = {n: [] for n in nodes}
                for dep_id, nid in dep_edges:
                    if dep_id in indeg and nid in indeg:
                        adj[dep_id].append(nid)
                        indeg[nid] += 1

                queue = [n for n in nodes if indeg[n] == 0]
                order = []
                while queue:
                    current = queue.pop(0)
                    order.append(current)
                    for nxt in adj[current]:
                        indeg[nxt] -= 1
                        if indeg[nxt] == 0:
                            queue.append(nxt)

                if len(order) == len(nodes):
                    self._topo_order = order
                    logger.info(f"Dependency order (deps->tasks): {self._topo_order}")
                else:
                    raise ValueError("cycle in dependency graph")
            else:
                # Fall back to reverse DAG order (leaves -> root)
                self._topo_order = self.dag.topological_sort(reverse=True)
                logger.info(f"DAG topological order (leaves->root): {self._topo_order}")
        except ValueError as e:
            logger.warning(f"Topological order failed: {e}, using node id order")
            self._topo_order = sorted(self.dag.nodes.keys())

        # Initialize TaskExecutor for executing individual tasks
        self.task_executor = TaskExecutor(
            data_file_paths=data_file_paths,
            data_dir=data_dir,
            llm_provider=llm_provider,
            docker_image=docker_image,
            docker_timeout=docker_timeout,
            output_dir=str(self.output_dir),
            interpreter_type=interpreter_type,
            venv_path=venv_path,
        )

        # LLM service for report generation
        self.llm_client = LLMClient(provider=llm_provider)
        self.llm_service = LLMService(client=self.llm_client)

        # Execution tracking
        self._node_status: Dict[int, NodeExecutionStatus] = {}
        self._node_records: Dict[int, NodeExecutionRecord] = {}
        self._all_generated_files: List[str] = []

        # Analysis report path
        self._analysis_report_path = self._init_analysis_report()


    def _init_analysis_report(self) -> Path:
        """初始化分析报告 Markdown 文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"analysis_report_plan{self.plan_id}_{timestamp}.md"
        report_path = self.output_dir / report_filename

        # 创建报告头部
        header = f"""# Data Analysis Report

**Plan ID**: {self.plan_id}
**Plan Title**: {self.tree.title}
**Generated Time**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

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
        content_parts.append(f"\n## Task: {record.node_name}\n")
        content_parts.append(f"**Task ID**: {record.node_id}\n")
        content_parts.append(f"**Execution Time**: {record.completed_at}\n\n")

        # 添加可视化目的
        if record.visualization_purpose:
            content_parts.append("### Analysis Purpose\n\n")
            content_parts.append(f"{record.visualization_purpose}\n\n")

        # 添加图表（new_files 已经是相对路径格式 results/xxx.png）
        if image_files:
            content_parts.append("### Generated Figures\n\n")
            for img_path in image_files:
                img_name = Path(img_path).name
                # img_path 已经是相对路径 results/xxx.png，直接使用
                content_parts.append(f"![{img_name}]({img_path})\n\n")

        # 添加可视化分析
        if record.visualization_analysis:
            content_parts.append("### Figure Analysis\n\n")
            content_parts.append(f"{record.visualization_analysis}\n\n")
        
        # 添加分隔线
        content_parts.append("---\n")
        
        # 追加到报告文件
        with open(self._analysis_report_path, 'a', encoding='utf-8') as f:
            f.write(''.join(content_parts))
        
        logger.info(f"已将任务 [{record.node_id}] 的可视化分析添加到报告")

    def _append_text_to_report(self, record: NodeExecutionRecord):
        """
        将文字分析内容追加到分析报告（用于data_summary和text_only任务）

        Args:
            record: 节点执行记录
        """
        if not record.text_response or not record.text_response.strip():
            logger.info(f"任务 [{record.node_id}] 没有文字内容需要添加到报告")
            return

        # 构建报告内容
        content_parts = []
        content_parts.append(f"\n## Task: {record.node_name}\n")
        content_parts.append(f"**Task ID**: {record.node_id}\n")
        content_parts.append(f"**Task Type**: {record.task_type.value if record.task_type else 'N/A'}\n")
        content_parts.append(f"**Execution Time**: {record.completed_at}\n\n")

        # 添加文字内容
        content_parts.append("### Analysis Results\n\n")
        content_parts.append(f"{record.text_response}\n\n")

        # 添加分隔线
        content_parts.append("---\n")

        # 追加到报告文件
        with open(self._analysis_report_path, 'a', encoding='utf-8') as f:
            f.write(''.join(content_parts))

        logger.info(f"已将任务 [{record.node_id}] 的文字分析添加到报告")

    def _append_code_output_to_report(self, record: NodeExecutionRecord):
        """
        将代码执行输出添加到分析报告（用于有输出但无可视化的code_required任务）

        Args:
            record: 节点执行记录
        """
        if not record.code_output or not record.code_output.strip():
            logger.info(f"任务 [{record.node_id}] 没有代码输出需要添加到报告")
            return

        # 构建报告内容
        content_parts = []
        content_parts.append(f"\n## Task: {record.node_name}\n")
        content_parts.append(f"**Task ID**: {record.node_id}\n")
        content_parts.append(f"**Task Type**: {record.task_type.value if record.task_type else 'N/A'}\n")
        content_parts.append(f"**Execution Time**: {record.completed_at}\n\n")

        # 添加代码描述（如果有）
        if record.code_description:
            content_parts.append("### Description\n\n")
            content_parts.append(f"{record.code_description}\n\n")

        # 添加代码输出
        content_parts.append("### Execution Output\n\n")
        content_parts.append(f"```\n{record.code_output}\n```\n\n")

        # 添加分隔线
        content_parts.append("---\n")

        # 追加到报告文件
        with open(self._analysis_report_path, 'a', encoding='utf-8') as f:
            f.write(''.join(content_parts))

        logger.info(f"已将任务 [{record.node_id}] 的代码输出添加到报告")

    def _append_empty_task_to_report(self, record: NodeExecutionRecord):
        """
        为没有生成内容的任务添加占位符信息到报告

        Args:
            record: 节点执行记录
        """
        content_parts = []
        content_parts.append(f"\n## Task: {record.node_name}\n")
        content_parts.append(f"**Task ID**: {record.node_id}\n")
        content_parts.append(f"**Task Type**: {record.task_type.value if record.task_type else 'N/A'}\n")
        content_parts.append(f"**Execution Time**: {record.completed_at}\n\n")

        # 添加说明
        content_parts.append("### Status\n\n")
        content_parts.append("✅ Task completed successfully, but no output was generated for the report.\n\n")

        if record.code_output:
            content_parts.append("### Execution Output\n\n")
            content_parts.append(f"```\n{record.code_output[:500]}\n```\n\n")

        # 添加分隔线
        content_parts.append("---\n")

        # 追加到报告文件
        with open(self._analysis_report_path, 'a', encoding='utf-8') as f:
            f.write(''.join(content_parts))

        logger.info(f"已为任务 [{record.node_id}] 添加占位符信息到报告")

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
        判断节点是否可以执行
        
        可执行条件：
        1. 节点状态为 PENDING
        2. 所有子节点都已结束（COMPLETED/FAILED/SKIPPED）
        
        注意：
        - 执行顺序：叶子节点 → 根节点
        - 只检查自己的子节点，不检查其它依赖
        """
        if self._node_status.get(node_id) != NodeExecutionStatus.PENDING:
            return False
        
        dag_node = self.dag.nodes.get(node_id)
        if not dag_node:
            return False
        
        done_statuses = {NodeExecutionStatus.COMPLETED, NodeExecutionStatus.FAILED, NodeExecutionStatus.SKIPPED}
        
        # 只检查子节点是否都已结束
        for child_id in dag_node.child_ids:
            if self._node_status.get(child_id) not in done_statuses:
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
        Collect dependency and child execution results as context.

        Execution flows from leaves to root:
        - Child nodes run first, their results feed into the parent node.
        - Explicit dependencies also provide context.
        """
        tree_node = self.tree.nodes.get(node_id)
        if not tree_node:
            return ""

        dag_node = self.dag.nodes.get(node_id)
        if not dag_node:
            return ""

        context_parts: List[str] = []
        collected_ids: Set[int] = set()

        def _add_record_context(label: str, record: NodeExecutionRecord) -> str:
            block = [f"### {label} [{record.node_id}] {record.node_name}"]
            if record.code_description:
                block.append(f"**Analysis Summary**: {record.code_description}")
            if record.code_output:
                block.append(f"**Execution Output**:{record.code_output[:10000]}")
            if record.text_response:
                block.append(f"**Text Result**: {record.text_response[:10000]}")
            if record.visualization_purpose:
                block.append(f"**Visualization Purpose**: {record.visualization_purpose}")
            if record.visualization_analysis:
                block.append(f"**Visualization Analysis**: {record.visualization_analysis}")
            if record.generated_files:
                block.append(f"**Generated Files**: {', '.join(record.generated_files)}")
                image_files = [
                    f for f in record.generated_files
                    if f.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".pdf"))
                ]
                if image_files:
                    block.append("**Available Figures (for citation in papers)**:")
                    for i, img in enumerate(image_files, 1):
                        block.append(f"  - Figure {i}: {img}")
            return "".join(block)

        # Explicit dependencies first
        for dep_id in (tree_node.dependencies or []):
            if dep_id in collected_ids:
                continue
            record = self._node_records.get(dep_id)
            if record and record.status == NodeExecutionStatus.COMPLETED:
                collected_ids.add(dep_id)
                context_parts.append(_add_record_context("Dependency Task", record))

        # Child tasks
        for child_id in dag_node.child_ids:
            if child_id in collected_ids:
                continue
            record = self._node_records.get(child_id)
            if record and record.status == NodeExecutionStatus.COMPLETED:
                collected_ids.add(child_id)
                context_parts.append(_add_record_context("Child Task", record))

        return "".join(context_parts)

    def _scan_generated_files(self) -> List[str]:
        """
        扫描 output_dir 及其子目录下生成的文件
        
        扫描范围：
        1. output_dir 根目录下的文件
        2. output_dir/results 子目录下的文件
        
        Returns:
            List[str]: 文件的相对路径列表（相对于 output_dir）
        """
        files = []
        
        # 扫描 output_dir 根目录
        for f in self.output_dir.iterdir():
            if f.is_file():
                files.append(f.name)
        
        # 扫描 results 子目录
        results_dir = self.output_dir / "results"
        if results_dir.exists():
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
        
        # 检查子节点是否有失败的，如果有则警告但继续执行
        dag_node = self.dag.nodes.get(node_id)
        if dag_node:
            failed_children = [
                cid for cid in dag_node.child_ids 
                if self._node_status.get(cid) == NodeExecutionStatus.FAILED
            ]
            if failed_children:
                failed_names = [self.tree.nodes[cid].name for cid in failed_children if cid in self.tree.nodes]
                logger.warning(f"节点 [{node_id}] 有 {len(failed_children)} 个子节点执行失败: {failed_names}，继续执行当前节点")
        
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

        # 从节点metadata中读取task_type（如果有的话）
        force_task_type = None
        if node.metadata and isinstance(node.metadata, dict):
            force_task_type = node.metadata.get("task_type")

        
        # 判断是否为可视化任务：
        # 1. 如果节点 metadata 中有 is_visualization 标记则使用该值
        # 2. 否则默认为 True（因为数据分析系统通常需要可视化能力）
        is_visualization = node.metadata.get("is_visualization", True)
        
        # 使用 TaskExecutor 执行任务，依赖结果通过 subtask_results 参数传递
        result: TaskExecutionResult = self.task_executor.execute(
            task_title=node.name,
            task_description=task_description,
            subtask_results=dependency_context,  # 传递依赖结果给信息收集和任务执行阶段
            force_task_type=force_task_type,  # 传递任务类型（如果指定）
            skip_info_gathering=True,  # 在智能模式下跳过信息收集，避免路径错误
            is_visualization=is_visualization
        )
        
        # 记录执行后的文件，找出新生成的
        files_after = set(self._scan_generated_files())
        new_files = list(files_after - files_before)
        
        # 更新记录
        record.task_type = result.task_type
        record.generated_files = new_files
        vision_analysis_text = None
        # If visualization files were generated, use vision model to produce analysis text
        if new_files:
            image_files = [
                f for f in new_files
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".pdf"))
            ]
            if image_files:
                try:
                    api_key = os.getenv("VISION_KEY")
                    base_url = os.getenv("VISION_URL")
                    model = os.getenv("VISION_MODEL")
                    if api_key:
                        analyzer = ImageAnalyzer(api_key=api_key, base_url=base_url, model=model)
                        analyses = []
                        for img in image_files:
                            img_path = self.output_dir / img
                            if not img_path.exists():
                                continue
                            vision_text = analyzer.analyze(
                                img_path,
                                prompt="Analyze the chart and summarize key patterns with concrete observations.",
                            )
                            if vision_text:
                                analyses.append(f"[{img}]\\n{vision_text}")
                        if analyses:
                            vision_analysis_text = "\\n\\n".join(analyses)
                except Exception as e:
                    logger.warning(f"Vision analysis skipped: {e}")

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
                record.visualization_analysis = vision_analysis_text or result.visualization_analysis
            elif result.task_type == TaskType.DATA_SUMMARY:
                # data_summary任务可能有代码和文字输出
                record.code = result.final_code
                record.code_output = result.code_output
                record.code_description = result.code_description
                record.text_response = result.text_response
                record.has_visualization = result.has_visualization
                record.visualization_purpose = result.visualization_purpose
                record.visualization_analysis = vision_analysis_text or result.visualization_analysis
            else:
                record.text_response = result.text_response

            logger.info(f"节点 [{node_id}] 执行成功")

            # 添加内容到分析报告
            image_extensions = {'.png', '.jpg', '.jpeg', '.svg', '.pdf'}
            has_image_files = any(Path(f).suffix.lower() in image_extensions for f in new_files)

            # 检查是否有任何内容需要添加到报告
            has_content = False

            # 如果有可视化，添加可视化内容
            if record.has_visualization or has_image_files:
                logger.info(f"检测到可视化内容: has_visualization={record.has_visualization}, has_image_files={has_image_files}")
                self._append_visualization_to_report(record, new_files)
                has_content = True
            # 如果有文字响应（data_summary或text_only），添加文字内容
            elif record.text_response and record.text_response.strip():
                logger.info(f"检测到文字分析内容，添加到报告")
                self._append_text_to_report(record)
                has_content = True
            # 如果有代码输出（code_required任务），也添加到报告
            elif record.code_output and record.code_output.strip():
                logger.info(f"检测到代码执行输出，添加到报告")
                self._append_code_output_to_report(record)
                has_content = True

            # 如果什么都没有，添加一个占位符说明
            if not has_content:
                logger.warning(f"任务 [{node_id}] 完成但没有任何输出")
                self._append_empty_task_to_report(record)
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
        执行计划的主入口（DAG 拓扑顺序调度）
        
        执行流程：
        1. 根据数据库状态初始化所有节点状态
        2. 按 DAG 拓扑顺序依次执行节点
        3. 每个节点执行前检查父节点和依赖是否完成
        4. 收集上游节点和子节点的结果作为上下文
        5. 生成分析报告
        
        调度策略：
        - 按 DAG 拓扑顺序执行（parent_ids 决定顺序）
        - 同时检查显式依赖（dependencies）
        - 每个节点可获取其父节点和子节点的执行结果
        
        Returns:
            PlanExecutionResult: 完整的执行结果
        """
        logger.info(f"开始执行计划（DAG拓扑顺序）: {self.tree.title} (ID: {self.plan_id})")
        logger.info(f"拓扑顺序: {self._topo_order}")
        started_at = datetime.now().isoformat()
        
        # 根据数据库中的状态初始化所有节点状态，并加载已完成节点的执行记录
        self._initialize_node_states()
        
        # 按拓扑顺序执行
        for idx, node_id in enumerate(self._topo_order):
            if self._node_status.get(node_id) != NodeExecutionStatus.PENDING:
                status = self._node_status.get(node_id)
                logger.info(f"[{idx+1}/{len(self._topo_order)}] 节点 [{node_id}] 状态为 {status.value}，跳过")
                continue
            
            # 检查是否可以执行（父节点和依赖都已完成）
            if not self._can_execute_node(node_id):
                logger.warning(f"[{idx+1}/{len(self._topo_order)}] 节点 [{node_id}] 前置条件未满足，标记为 SKIPPED")
                self._node_status[node_id] = NodeExecutionStatus.SKIPPED
                continue
            
            logger.info(f"[{idx+1}/{len(self._topo_order)}] 执行节点 [{node_id}]")
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
## Execution Summary

| Metric | Value |
|--------|-------|
| Total Tasks | {len(self.tree.nodes)} |
| Completed | {completed} |
| Failed | {failed} |
| Skipped | {skipped} |

**Completion Time**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
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
