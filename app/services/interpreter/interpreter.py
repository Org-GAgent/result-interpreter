"""
数据分析解释器完整接口

提供一站式接口：传入描述和数据路径 -> 创建计划 -> 分解任务 -> 执行

用法:
    from app.services.interpreter.interpreter import run_analysis
    
    result = run_analysis(
        description="分析销售数据趋势，生成可视化图表",
        data_paths=["data/sales.csv"]
    )
"""

import os
import logging
from typing import List, Optional
from dataclasses import dataclass
from pathlib import Path

from app.database import init_db
from app.repository.plan_repository import PlanRepository
from app.services.plans.plan_decomposer import PlanDecomposer
from .plan_execute import PlanExecutorInterpreter, PlanExecutionResult

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """分析执行完整结果"""
    plan_id: int
    success: bool
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    generated_files: List[str]
    report_path: Optional[str] = None
    error: Optional[str] = None


def run_analysis(
    description: str,
    data_paths: List[str],
    *,
    title: Optional[str] = None,
    output_dir: str = "./results",
    llm_provider: str = "qwen",
    max_depth: int = 5,
    node_budget: int = 50,
    docker_image: str = "agent-plotter",
    docker_timeout: int = 7200,
) -> AnalysisResult:
    """
    一站式数据分析接口
    
    完整流程: 创建计划 -> 分解任务 -> 执行
    
    Args:
        description: 分析任务描述（详细说明分析目标和要求）
        data_paths: 数据文件路径列表
        title: 计划标题（可选，默认使用第一个文件名）
        output_dir: 输出目录
        llm_provider: LLM提供商 (qwen/openai等)
        max_depth: 任务分解最大深度
        node_budget: 任务节点数量上限
        docker_image: Docker镜像名称
        docker_timeout: Docker执行超时(秒)
    
    Returns:
        AnalysisResult: 包含执行结果、生成文件列表等
    
    Example:
        >>> result = run_analysis(
        ...     description="分析销售数据，计算月度趋势，绘制折线图",
        ...     data_paths=["sales_2024.csv"],
        ...     max_depth=2
        ... )
        >>> print(f"成功: {result.success}, 文件: {result.generated_files}")
    """
    # 验证数据文件
    data_paths = [os.path.abspath(p) for p in data_paths]
    for path in data_paths:
        if not os.path.exists(path):
            return AnalysisResult(
                plan_id=-1,
                success=False,
                total_tasks=0,
                completed_tasks=0,
                failed_tasks=0,
                generated_files=[],
                error=f"文件不存在: {path}"
            )

    # 初始化
    init_db()
    repo = PlanRepository()
    
    # 生成标题
    if not title:
        title = Path(data_paths[0]).stem + " 数据分析"

    try:
        # Step 1: 创建计划
        logger.info(f"[1/3] 创建计划: {title}")
        plan = repo.create_plan(title=title, description=description)
        plan_id = plan.id
        logger.info(f"  计划ID: {plan_id}")

        # Step 2: 分解任务
        logger.info(f"[2/3] 分解任务 (max_depth={max_depth}, budget={node_budget})")
        decomposer = PlanDecomposer(repo=repo)
        decomp_result = decomposer.run_plan(
            plan_id, 
            max_depth=max_depth, 
            node_budget=node_budget
        )
        logger.info(f"  创建 {len(decomp_result.created_tasks)} 个任务")
        if decomp_result.stopped_reason:
            logger.info(f"  停止原因: {decomp_result.stopped_reason}")
            
        # 打印计划结构
        print_plan_tree(repo, plan_id)

        # Step 3: 执行计划
        logger.info(f"[3/3] 执行计划...")
        os.makedirs(output_dir, exist_ok=True)
        
        executor = PlanExecutorInterpreter(
            plan_id=plan_id,
            data_file_paths=data_paths,
            output_dir=output_dir,
            llm_provider=llm_provider,
            docker_image=docker_image,
            docker_timeout=docker_timeout,
            repo=repo
        )
        exec_result: PlanExecutionResult = executor.execute()

        logger.info(f"执行完成! 成功: {exec_result.success}")
        
        return AnalysisResult(
            plan_id=plan_id,
            success=exec_result.success,
            total_tasks=exec_result.total_nodes,
            completed_tasks=exec_result.completed_nodes,
            failed_tasks=exec_result.failed_nodes,
            generated_files=exec_result.all_generated_files,
            report_path=exec_result.report_path
        )

    except Exception as e:
        logger.exception(f"执行失败: {e}")
        return AnalysisResult(
            plan_id=plan_id if 'plan_id' in locals() else -1,
            success=False,
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
            generated_files=[],
            error=str(e)
        )


def run_analysis_async(
    description: str,
    data_paths: List[str],
    **kwargs
) -> int:
    """
    异步版本：仅创建和分解计划，返回plan_id供后续执行
    
    Args:
        description: 分析任务描述
        data_paths: 数据文件路径列表
        **kwargs: 传递给分解器的参数 (max_depth, node_budget等)
    
    Returns:
        int: 计划ID，可用于后续调用 execute_plan()
    """
    init_db()
    repo = PlanRepository()
    
    title = kwargs.get('title') or Path(data_paths[0]).stem + " 数据分析"
    max_depth = kwargs.get('max_depth', 3)
    node_budget = kwargs.get('node_budget', 10)

    # 创建计划
    plan = repo.create_plan(title=title, description=description)
    
    # 分解任务
    decomposer = PlanDecomposer(repo=repo)
    decomposer.run_plan(plan.id, max_depth=max_depth, node_budget=node_budget)
    
    return plan.id


def execute_plan(
    plan_id: int,
    data_paths: List[str],
    *,
    output_dir: str = "./results",
    llm_provider: str = "qwen",
    docker_image: str = "agent-plotter",
    docker_timeout: int = 300,
) -> PlanExecutionResult:
    """
    执行已存在的计划
    
    Args:
        plan_id: 计划ID
        data_paths: 数据文件路径列表
        output_dir: 输出目录
        llm_provider: LLM提供商
        docker_image: Docker镜像
        docker_timeout: 超时时间
    
    Returns:
        PlanExecutionResult: 执行结果
    """
    init_db()
    repo = PlanRepository()
    
    print_plan_tree(repo, plan_id=plan_id)

    executor = PlanExecutorInterpreter(
        plan_id=plan_id,
        data_file_paths=data_paths,
        output_dir=output_dir,
        llm_provider=llm_provider,
        docker_image=docker_image,
        docker_timeout=docker_timeout,
        repo=repo
    )
    exec_result: PlanExecutionResult = executor.execute()

    logger.info(f"执行完成! 成功: {exec_result.success}")
    
    return AnalysisResult(
        plan_id=plan_id,
        success=exec_result.success,
        total_tasks=exec_result.total_nodes,
        completed_tasks=exec_result.completed_nodes,
        failed_tasks=exec_result.failed_nodes,
        generated_files=exec_result.all_generated_files,
        report_path=exec_result.report_path
    )


def print_plan_tree(repo: PlanRepository, plan_id: int):
    """打印计划树结构"""
    tree = repo.get_plan_tree(plan_id)
    
    print(f"\n{'='*60}")
    print(f"计划 #{tree.id}: {tree.title}")
    print(f"{'='*60}")
    print(f"节点数: {len(tree.nodes)}")
    print("\n任务结构:")
    
    def print_node(node_id, indent=0):
        node = tree.nodes.get(node_id)
        if not node:
            return
        prefix = "  " * indent
        deps = f" [依赖: {','.join(map(str, node.dependencies))}]" if node.dependencies else ""
        print(f"{prefix}├─ [{node.id}] {node.name}{deps}")
        if node.instruction:
            instr = node.instruction.strip()[:60]
            if len(node.instruction.strip()) > 60:
                instr += "..."
            print(f"{prefix}│    > {instr}")
        
        children = tree.adjacency.get(node_id, [])
        for child_id in sorted(children, key=lambda x: tree.nodes[x].position):
            print_node(child_id, indent + 1)
    
    roots = tree.adjacency.get(None, [])
    for root_id in sorted(roots, key=lambda x: tree.nodes[x].position):
        print_node(root_id)
    
    print()
