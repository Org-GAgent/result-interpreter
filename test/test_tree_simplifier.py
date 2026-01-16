"""
测试树结构简化器 - TreeSimplifier
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import init_db
from app.services.plans.tree_simplifier import (
    DAGNode, DAG, 
    LLMSimilarityMatcher, 
    TreeSimplifier
)


def test_llm_similarity_matcher():
    """测试 LLMSimilarityMatcher 能否正常识别相似节点"""
    print("=" * 60)
    print("测试 LLMSimilarityMatcher")
    print("=" * 60)
    
    # 创建测试节点
    nodes = [
        DAGNode(id=1, name="加载数据", instruction="从CSV文件加载数据", source_node_ids=[1]),
        DAGNode(id=2, name="加载数据", instruction="从Excel文件加载数据", source_node_ids=[2]),
        DAGNode(id=3, name="数据预处理", instruction="清洗缺失值", source_node_ids=[3]),
        DAGNode(id=4, name="配置聚类算法", instruction="使用K-Means聚类，k=5", source_node_ids=[4]),
        DAGNode(id=5, name="配置聚类算法", instruction="使用K-Means聚类，k=5", source_node_ids=[5]),
        DAGNode(id=6, name="选择并配置聚类算法", instruction="选择K-Means，设置k=5", source_node_ids=[6]),
        DAGNode(id=7, name="生成报告", instruction="输出分析结果", source_node_ids=[7]),
    ]
    
    matcher = LLMSimilarityMatcher(threshold=0.8)
    
    print("\n【测试节点列表】")
    for node in nodes:
        print(f"  [{node.id}] {node.name}: {node.instruction}")
    
    print("\n【调用 LLM 查找相似节点对】")
    similar_pairs = matcher.find_similar_pairs(nodes)
    
    if similar_pairs:
        print(f"\n找到 {len(similar_pairs)} 对相似节点:")
        for id1, id2, sim in similar_pairs:
            n1 = next((n for n in nodes if n.id == id1), None)
            n2 = next((n for n in nodes if n.id == id2), None)
            if n1 and n2:
                print(f"  [{id1}] {n1.name} <-> [{id2}] {n2.name}")
                print(f"      相似度: {sim:.2f}")
    else:
        print("  未找到相似节点对")
    
    print("\n✓ LLMSimilarityMatcher 测试完成")
    return similar_pairs


def test_merge_with_dag():
    """测试在 DAG 中合并节点"""
    print("\n" + "=" * 60)
    print("测试 DAG 节点合并")
    print("=" * 60)
    
    # 创建一个简单的 DAG
    dag = DAG(plan_id=0, title="测试计划")
    
    # 添加节点
    # 结构:  1 -> 2 -> 4
    #        1 -> 3 -> 5
    #        (2和3是并行的，可以合并如果相似)
    dag.nodes[1] = DAGNode(id=1, name="数据加载", source_node_ids=[1])
    dag.nodes[2] = DAGNode(id=2, name="配置聚类算法", instruction="K-Means k=5", 
                           source_node_ids=[2], parent_ids={1})
    dag.nodes[3] = DAGNode(id=3, name="配置聚类算法", instruction="K-Means k=5", 
                           source_node_ids=[3], parent_ids={1})
    dag.nodes[4] = DAGNode(id=4, name="执行聚类A", source_node_ids=[4], parent_ids={2})
    dag.nodes[5] = DAGNode(id=5, name="执行聚类B", source_node_ids=[5], parent_ids={3})
    
    # 设置子节点关系
    dag.nodes[1].child_ids = {2, 3}
    dag.nodes[2].child_ids = {4}
    dag.nodes[3].child_ids = {5}
    
    simplifier = TreeSimplifier()
    
    print("\n【合并前的 DAG】")
    print(dag.visualize())
    
    # 检查节点 2 和 3 是否可合并
    can, reason = simplifier.can_merge(dag, 2, 3)
    print(f"\n节点 [2] 和 [3] 可否合并: {can}")
    print(f"原因: {reason}")
    
    if can:
        # 使用 LLM 判断是否应该合并
        matcher = LLMSimilarityMatcher(threshold=0.8)
        should = matcher.should_merge(dag.nodes[2], dag.nodes[3])
        
        if should:
            print("\n【执行合并】")
            simplifier.merge_nodes(dag, 2, 3)
            print("\n【合并后的 DAG】")
            print(dag.visualize())
            print(f"\n合并映射: {dag.merge_map}")
        else:
            print("\nLLM 判定不应合并")
    
    print("\n✓ DAG 合并测试完成")


def test_with_real_plan(plan_id: int = None):
    """使用真实计划测试（如果存在）"""
    print("\n" + "=" * 60)
    print("测试真实计划的简化")
    print("=" * 60)
    
    init_db()
    
    from app.repository.plan_repository import PlanRepository
    repo = PlanRepository()
    
    print(f"\n使用计划 #{plan_id}: {plan_id}")
    
    simplifier = TreeSimplifier()
    
    # 加载并转换为 DAG
    tree = repo.get_plan_tree(plan_id)
    dag = simplifier.tree_to_dag(tree)
    
    print(f"\n原始节点数: {dag.node_count()}")
    
    # 查找相似节点
    matcher = LLMSimilarityMatcher(threshold=0.8)
    nodes = list(dag.nodes.values())
    
    print("\n【调用 LLM 查找相似节点】")
    similar_pairs = matcher.find_similar_pairs(nodes)
    
    if similar_pairs:
        print(f"\n找到 {len(similar_pairs)} 对相似节点:")
        for id1, id2, sim in similar_pairs:
            n1 = dag.nodes.get(id1)
            n2 = dag.nodes.get(id2)
            if n1 and n2:
                can, reason = simplifier.can_merge(dag, id1, id2)
                status = "✓ 可合并" if can else f"✗ {reason}"
                print(f"  [{id1}] {n1.name[:20]} <-> [{id2}] {n2.name[:20]}")
                print(f"      相似度: {sim:.2f} | {status}")
    else:
        print("  未找到相似节点对")
    
    print("\n✓ 真实计划测试完成")


if __name__ == "__main__":
    print("TreeSimplifier 测试套件")
    print("=" * 60)
    
    # 测试1: LLM相似度匹配
    test_llm_similarity_matcher()
    
    # 测试2: DAG合并
    test_merge_with_dag()
    
    # 测试3: 真实计划（可选）
    test_with_real_plan(27)
    
    print("\n" + "=" * 60)
    print("所有测试完成!")
    print("=" * 60)
