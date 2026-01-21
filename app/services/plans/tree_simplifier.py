"""
树结构简化器 - 将计划树转换为DAG

通过识别相似节点并合并，减少冗余任务，形成有向无环图(DAG)结构。
"""

import sys
import os

# 添加项目根目录到路径
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_current_dir, "../../../"))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any
from copy import deepcopy

from app.services.plans.plan_models import PlanNode, PlanTree


@dataclass
class DAGNode:
    """DAG中的节点"""
    id: int
    name: str
    instruction: Optional[str] = None
    
    # 原始节点ID列表（合并后可能包含多个）
    source_node_ids: List[int] = field(default_factory=list)
    
    # DAG结构：多个父节点，多个子节点
    parent_ids: Set[int] = field(default_factory=set)
    child_ids: Set[int] = field(default_factory=set)
    
    # 依赖关系
    dependencies: Set[int] = field(default_factory=set)
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_parent(self, parent_id: int) -> None:
        self.parent_ids.add(parent_id)
    
    def add_child(self, child_id: int) -> None:
        self.child_ids.add(child_id)
    
    def merge_from(self, other: 'DAGNode') -> None:
        """合并另一个节点的信息"""
        self.source_node_ids.extend(other.source_node_ids)
        self.parent_ids.update(other.parent_ids)
        self.child_ids.update(other.child_ids)
        self.dependencies.update(other.dependencies)


@dataclass
class DAG:
    """有向无环图结构"""
    plan_id: int
    title: str
    description: Optional[str] = None
    
    nodes: Dict[int, DAGNode] = field(default_factory=dict)
    
    # 合并记录: 被合并节点ID -> 目标节点ID
    merge_map: Dict[int, int] = field(default_factory=dict)
    
    def node_count(self) -> int:
        return len(self.nodes)
    
    def get_roots(self) -> List[DAGNode]:
        """获取所有根节点（无父节点）"""
        return [n for n in self.nodes.values() if not n.parent_ids]
    
    def get_leaves(self) -> List[DAGNode]:
        """获取所有叶节点（无子节点）"""
        return [n for n in self.nodes.values() if not n.child_ids]
    
    def topological_sort(self, reverse: bool = False) -> List[int]:
        """
        拓扑排序，返回节点ID列表
        
        Args:
            reverse: 如果为 True，返回反向拓扑顺序（从叶子节点到根节点）
                     这适用于任务执行场景：先执行子任务，再执行父任务
        
        Returns:
            节点ID列表，按拓扑顺序排列
        """
        in_degree = {nid: len(n.parent_ids) for nid, n in self.nodes.items()}
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []
        
        while queue:
            node_id = queue.pop(0)
            result.append(node_id)
            
            for child_id in self.nodes[node_id].child_ids:
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    queue.append(child_id)
        
        if len(result) != len(self.nodes):
            raise ValueError("图中存在环，无法拓扑排序")
        
        if reverse:
            return result[::-1]
        return result
    
    def to_outline(self) -> str:
        """生成DAG结构的文本描述"""
        lines = [
            f"DAG: {self.title} (Plan #{self.plan_id})",
            f"节点数: {self.node_count()}",
            f"合并数: {len(self.merge_map)}",
            ""
        ]
        
        try:
            sorted_ids = self.topological_sort()
        except ValueError:
            sorted_ids = list(self.nodes.keys())
        
        for node_id in sorted_ids:
            node = self.nodes[node_id]
            parents = ",".join(map(str, sorted(node.parent_ids))) or "无"
            children = ",".join(map(str, sorted(node.child_ids))) or "无"
            sources = ",".join(map(str, node.source_node_ids))
            
            lines.append(f"[{node_id}] {node.name}")
            lines.append(f"    来源: {sources}")
            lines.append(f"    父节点: {parents} | 子节点: {children}")
            if node.instruction:
                instr = node.instruction[:80] + "..." if len(node.instruction) > 80 else node.instruction
                lines.append(f"    指令: {instr}")
        
        return "\n".join(lines)
    
    def visualize(self, show_instruction: bool = False) -> str:
        """
        可视化DAG结构（ASCII图形）
        
        Args:
            show_instruction: 是否显示节点指令
            
        Returns:
            ASCII格式的DAG可视化字符串
        """
        lines = []
        lines.append(f"╔{'═'*58}╗")
        lines.append(f"║ DAG: {self.title[:50]:<52}║")
        lines.append(f"║ Plan #{self.plan_id} | 节点: {self.node_count()} | 合并: {len(self.merge_map):<15}║")
        lines.append(f"╠{'═'*58}╣")
        
        # 获取根节点
        roots = [n for n in self.nodes.values() if not n.parent_ids]
        
        if not roots:
            lines.append("║ (空图)                                                   ║")
            lines.append(f"╚{'═'*58}╝")
            return "\n".join(lines)
        
        # BFS遍历并记录层级
        visited = set()
        levels: Dict[int, List[int]] = {}  # level -> [node_ids]
        node_level: Dict[int, int] = {}  # node_id -> level
        
        queue = [(r.id, 0) for r in roots]
        while queue:
            node_id, level = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)
            
            levels.setdefault(level, []).append(node_id)
            node_level[node_id] = level
            
            node = self.nodes[node_id]
            for child_id in sorted(node.child_ids):
                if child_id not in visited:
                    queue.append((child_id, level + 1))
        
        # 打印每层
        for level in sorted(levels.keys()):
            node_ids = levels[level]
            indent = "  " * level
            
            for node_id in node_ids:
                node = self.nodes[node_id]
                
                # 节点符号
                if not node.parent_ids:
                    prefix = "◉"  # 根节点
                elif not node.child_ids:
                    prefix = "◎"  # 叶节点
                else:
                    prefix = "○"  # 中间节点
                
                # 多父节点标记
                multi_parent = f" ←[{','.join(map(str, sorted(node.parent_ids)))}]" if len(node.parent_ids) > 1 else ""
                
                name = node.name[:40] + "..." if len(node.name) > 40 else node.name
                lines.append(f"║ {indent}{prefix} [{node_id}] {name}{multi_parent}")
                
                # 显示指令
                if show_instruction and node.instruction:
                    instr = node.instruction[:50] + "..." if len(node.instruction) > 50 else node.instruction
                    lines.append(f"║ {indent}   └─ {instr}")
                
                # 显示子节点连接
                if node.child_ids:
                    children_str = ",".join(map(str, sorted(node.child_ids)))
                    lines.append(f"║ {indent}   ↓ [{children_str}]")
        
        lines.append(f"╠{'═'*58}╣")
        lines.append("║ 图例: ◉根节点  ○中间节点  ◎叶节点  ←多父节点           ║")
        lines.append(f"╚{'═'*58}╝")
        
        return "\n".join(lines)
    
    def print_adjacency(self) -> str:
        """
        打印邻接表
        
        Returns:
            邻接表的文本表示
        """
        lines = [
            f"邻接表 - {self.title} (Plan #{self.plan_id})",
            f"{'─'*50}",
            "节点 → 子节点列表",
            f"{'─'*50}",
        ]
        
        for node_id in sorted(self.nodes.keys()):
            node = self.nodes[node_id]
            children = sorted(node.child_ids) if node.child_ids else []
            children_str = ", ".join(map(str, children)) if children else "(无)"
            lines.append(f"[{node_id:3}] {node.name[:30]:<30} → {children_str}")
        
        lines.append(f"{'─'*50}")
        
        # 反向邻接表
        lines.append("")
        lines.append("反向邻接表 (入边)")
        lines.append(f"{'─'*50}")
        lines.append("节点 ← 父节点列表")
        lines.append(f"{'─'*50}")
        
        for node_id in sorted(self.nodes.keys()):
            node = self.nodes[node_id]
            parents = sorted(node.parent_ids) if node.parent_ids else []
            parents_str = ", ".join(map(str, parents)) if parents else "(根节点)"
            lines.append(f"[{node_id:3}] {node.name[:30]:<30} ← {parents_str}")
        
        return "\n".join(lines)


class SimilarityMatcher(ABC):
    """相似度匹配器接口"""
    
    @abstractmethod
    def find_similar_pairs(
        self, 
        nodes: List[DAGNode]
    ) -> List[Tuple[int, int, float]]:
        """
        找出所有相似节点对
        
        Args:
            nodes: DAG节点列表
            
        Returns:
            相似节点对列表: [(node_id_1, node_id_2, similarity_score), ...]
            similarity_score 范围 [0, 1]，1表示完全相同
        """
        pass
    
    @abstractmethod
    def should_merge(
        self, 
        node1: DAGNode, 
        node2: DAGNode
    ) -> bool:
        """
        判断两个节点是否应该合并
        
        Args:
            node1: 第一个节点
            node2: 第二个节点
            
        Returns:
            是否应该合并
        """
        pass


class LLMSimilarityMatcher(SimilarityMatcher):
    """基于LLM的相似度匹配器"""
    
    def __init__(self, threshold: float = 0.8):
        self.threshold = threshold
        self._llm = None
    
    @property
    def llm(self):
        if self._llm is None:
            from app.llm import LLMClient
            self._llm = LLMClient()
        return self._llm
    
    def _parse_json(self, text: str) -> Any:
        """从LLM响应中提取JSON"""
        import json
        import re
        
        # 尝试直接解析
        try:
            return json.loads(text.strip())
        except:
            pass
        
        # 提取 ```json ... ``` 块
        match = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except:
                pass
        
        # 提取第一个 {...} 或 [...]
        match = re.search(r'(\{[^{}]*\}|\[[^\[\]]*\])', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except:
                pass
        
        return None
    
    def find_similar_pairs(
        self, 
        nodes: List[DAGNode]
    ) -> List[Tuple[int, int, float]]:
        """使用LLM批量找出相似节点对"""
        if len(nodes) < 2:
            return []
        
        from app.services.plans.prompts.merge_similarity import (
            BATCH_SIMILARITY_SYSTEM,
            BATCH_SIMILARITY_USER
        )
        
        # 构建节点描述
        nodes_lines = []
        for node in nodes:
            instr = (node.instruction or "")[:100]
            nodes_lines.append(f"[{node.id}] {node.name}: {instr}")
        nodes_text = "\n".join(nodes_lines)
        
        prompt = f"{BATCH_SIMILARITY_SYSTEM}\n\n{BATCH_SIMILARITY_USER.format(nodes_text=nodes_text)}"
        
        try:
            response = self.llm.chat(prompt)
            result = self._parse_json(response)
            
            if isinstance(result, list):
                pairs = []
                for item in result:
                    if isinstance(item, dict):
                        id1 = item.get("id1")
                        id2 = item.get("id2")
                        sim = float(item.get("similarity", 0))
                        if id1 and id2 and sim >= self.threshold:
                            pairs.append((id1, id2, sim))
                return pairs
        except Exception as e:
            print(f"  ⚠ LLM相似度检测失败: {e}")
        
        return []
    
    def should_merge(
        self, 
        node1: DAGNode, 
        node2: DAGNode
    ) -> bool:
        """使用LLM判断两个节点是否应合并"""
        from app.services.plans.prompts.merge_similarity import (
            MERGE_SIMILARITY_SYSTEM,
            MERGE_SIMILARITY_USER
        )
        
        prompt = MERGE_SIMILARITY_SYSTEM + "\n\n" + MERGE_SIMILARITY_USER.format(
            id1=node1.id,
            name1=node1.name,
            instruction1=node1.instruction or "(无)",
            id2=node2.id,
            name2=node2.name,
            instruction2=node2.instruction or "(无)"
        )
        
        try:
            response = self.llm.chat(prompt)
            result = self._parse_json(response)
            
            if isinstance(result, dict):
                can_merge = result.get("can_merge", False)
                similarity = float(result.get("similarity", 0))
                reason = result.get("reason", "")
                
                if can_merge and similarity >= self.threshold:
                    print(f"  ✓ LLM判定可合并 [{node1.id}]+[{node2.id}]: {reason}")
                    return True
                else:
                    print(f"  ✗ LLM判定不合并 [{node1.id}]+[{node2.id}]: {reason}")
        except Exception as e:
            print(f"  ⚠ LLM判断失败: {e}")
        
        return False


class TreeSimplifier:
    """
    树结构简化器
    
    将PlanTree转换为DAG，通过合并相似节点减少冗余
    
    用法:
        simplifier = TreeSimplifier(matcher=MySimilarityMatcher())
        dag = simplifier.simplify(plan_tree)
    """
    
    def __init__(
        self, 
        matcher: Optional[SimilarityMatcher] = None
    ):
        """
        初始化简化器
        
        Args:
            matcher: 相似度匹配器，用于识别和判断节点是否应合并
        """
        self.matcher = matcher or LLMSimilarityMatcher()
    
    def is_reachable(self, dag: DAG, from_id: int, to_id: int) -> bool:
        """
        BFS检查从from_id是否可达to_id
        
        Args:
            dag: DAG结构
            from_id: 起始节点ID
            to_id: 目标节点ID
            
        Returns:
            是否可达
        """
        if from_id == to_id:
            return True
        
        visited = set()
        queue = [from_id]
        
        while queue:
            current = queue.pop(0)
            if current == to_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            
            node = dag.nodes.get(current)
            if node:
                queue.extend(node.child_ids - visited)
        
        return False
    
    def can_merge(
        self, 
        dag: DAG, 
        node1_id: int, 
        node2_id: int
    ) -> Tuple[bool, str]:
        """
        检查两个节点是否可以安全合并（不产生环）
        
        合并条件：
        1. 两节点都存在
        2. 不存在直接父子关系
        3. 不存在祖先-后代关系（互不可达）
        4. 不存在直接依赖关系
        
        Args:
            dag: DAG结构
            node1_id: 第一个节点ID
            node2_id: 第二个节点ID
            
        Returns:
            (可否合并, 原因)
        """
        node1 = dag.nodes.get(node1_id)
        node2 = dag.nodes.get(node2_id)
        
        if not node1 or not node2:
            return False, "节点不存在"
        
        if node1_id == node2_id:
            return False, "同一节点"
        
        # 检查1: 直接父子关系
        if node2_id in node1.child_ids or node1_id in node2.child_ids:
            return False, "存在直接父子关系（子节点）"
        
        if node2_id in node1.parent_ids or node1_id in node2.parent_ids:
            return False, "存在直接父子关系（父节点）"
        
        # 检查2: 祖先-后代关系（路径可达性）
        if self.is_reachable(dag, node1_id, node2_id):
            return False, f"[{node1_id}]是[{node2_id}]的祖先，存在路径"
        
        if self.is_reachable(dag, node2_id, node1_id):
            return False, f"[{node2_id}]是[{node1_id}]的祖先，存在路径"
        
        # 检查3: 依赖关系
        if node2_id in node1.dependencies:
            return False, f"[{node1_id}]依赖[{node2_id}]"
        
        if node1_id in node2.dependencies:
            return False, f"[{node2_id}]依赖[{node1_id}]"
        
        return True, "可以合并（互不可达的并行节点）"
    
    def find_mergeable_groups(self, dag: DAG) -> List[List[int]]:
        """
        找出所有可合并的节点组（互不可达的相似节点）
        
        Returns:
            可合并节点组列表，每组可以合并为一个节点
        """
        node_ids = list(dag.nodes.keys())
        n = len(node_ids)
        
        # 构建可达性矩阵
        reachable = {}
        for i in range(n):
            for j in range(i + 1, n):
                id1, id2 = node_ids[i], node_ids[j]
                can, _ = self.can_merge(dag, id1, id2)
                reachable[(id1, id2)] = can
                reachable[(id2, id1)] = can
        
        # 使用并查集或贪心算法找出可合并组
        # 这里使用简单的贪心：按节点名称分组，然后检查组内是否可合并
        name_groups: Dict[str, List[int]] = {}
        for node_id, node in dag.nodes.items():
            # 使用名称的简化版本作为key
            name_key = node.name.strip().lower()
            name_groups.setdefault(name_key, []).append(node_id)
        
        mergeable_groups = []
        for name, ids in name_groups.items():
            if len(ids) < 2:
                continue
            
            # 检查组内所有节点两两可合并
            group_valid = True
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    if not reachable.get((ids[i], ids[j]), False):
                        group_valid = False
                        break
                if not group_valid:
                    break
            
            if group_valid:
                mergeable_groups.append(ids)
        
        return mergeable_groups
    
    def tree_to_dag(self, tree: PlanTree) -> DAG:
        """
        将PlanTree转换为DAG（不做合并）
        
        Args:
            tree: 输入的计划树
            
        Returns:
            对应的DAG结构
        """
        dag = DAG(
            plan_id=tree.id,
            title=tree.title,
            description=tree.description
        )
        
        # 转换所有节点
        for node_id, plan_node in tree.nodes.items():
            dag_node = DAGNode(
                id=node_id,
                name=plan_node.name,
                instruction=plan_node.instruction,
                source_node_ids=[node_id],
                dependencies=set(plan_node.dependencies),
                metadata=deepcopy(plan_node.metadata)
            )
            dag.nodes[node_id] = dag_node
        
        # 根据 adjacency (边) 设置父子关系
        for parent_id, children_ids in tree.adjacency.items():
            if parent_id is None:
                # 根节点，没有父节点
                continue
            if parent_id not in dag.nodes:
                continue
            for child_id in children_ids:
                if child_id in dag.nodes:
                    dag.nodes[parent_id].child_ids.add(child_id)
                    dag.nodes[child_id].parent_ids.add(parent_id)
        
        return dag
    
    def merge_nodes(
        self, 
        dag: DAG, 
        keep_id: int, 
        remove_id: int,
        force: bool = False
    ) -> bool:
        """
        合并两个节点，保留keep_id，删除remove_id
        
        Args:
            dag: DAG结构
            keep_id: 保留的节点ID
            remove_id: 要删除的节点ID
            force: 是否跳过安全检查
            
        Returns:
            是否成功合并
        """
        if keep_id not in dag.nodes or remove_id not in dag.nodes:
            return False
        
        # 安全检查
        if not force:
            can, reason = self.can_merge(dag, keep_id, remove_id)
            if not can:
                print(f"  ⚠ 无法合并 [{keep_id}] 和 [{remove_id}]: {reason}")
                return False
        
        keep_node = dag.nodes[keep_id]
        remove_node = dag.nodes[remove_id]
        
        # 合并信息
        keep_node.merge_from(remove_node)
        
        # 移除自引用
        keep_node.parent_ids.discard(keep_id)
        keep_node.child_ids.discard(keep_id)
        keep_node.parent_ids.discard(remove_id)
        keep_node.child_ids.discard(remove_id)
        
        # 更新其他节点的引用
        for node_id, node in dag.nodes.items():
            if node_id == keep_id or node_id == remove_id:
                continue
            
            # 将指向remove_id的引用改为指向keep_id
            if remove_id in node.parent_ids:
                node.parent_ids.discard(remove_id)
                node.parent_ids.add(keep_id)
            
            if remove_id in node.child_ids:
                node.child_ids.discard(remove_id)
                node.child_ids.add(keep_id)
            
            if remove_id in node.dependencies:
                node.dependencies.discard(remove_id)
                node.dependencies.add(keep_id)
        
        # 删除节点并记录映射
        del dag.nodes[remove_id]
        dag.merge_map[remove_id] = keep_id
        
        return True
    
    def merge_group(
        self, 
        dag: DAG, 
        node_ids: List[int]
    ) -> Optional[int]:
        """
        合并一组节点为一个
        
        Args:
            dag: DAG结构
            node_ids: 要合并的节点ID列表
            
        Returns:
            合并后保留的节点ID，失败返回None
        """
        if len(node_ids) < 2:
            return node_ids[0] if node_ids else None
        
        # 检查组内所有节点两两可合并
        for i in range(len(node_ids)):
            for j in range(i + 1, len(node_ids)):
                can, reason = self.can_merge(dag, node_ids[i], node_ids[j])
                if not can:
                    print(f"  ⚠ 组内节点不可合并: [{node_ids[i]}] 和 [{node_ids[j]}]: {reason}")
                    return None
        
        # 保留ID最小的节点
        keep_id = min(node_ids)
        merged_names = []
        
        for remove_id in sorted(node_ids):
            if remove_id == keep_id:
                continue
            node_name = dag.nodes[remove_id].name if remove_id in dag.nodes else "?"
            if self.merge_nodes(dag, keep_id, remove_id):
                merged_names.append(f"[{remove_id}]{node_name[:20]}")
        
        if merged_names:
            keep_name = dag.nodes[keep_id].name
            print(f"  ✓ 合并完成: [{keep_id}]{keep_name[:20]} ← {', '.join(merged_names)}")
        
        return keep_id
    
    def simplify(
        self, 
        tree: PlanTree, 
        max_iterations: int = 100
    ) -> DAG:
        """
        简化树结构，合并相似节点，生成DAG
        
        Args:
            tree: 输入的计划树
            max_iterations: 最大迭代次数（防止无限循环）
            
        Returns:
            简化后的DAG结构
        """
        # 1. 转换为DAG
        dag = self.tree_to_dag(tree)
        
        # 2. 一次性获取所有相似对（只调用一次LLM）
        nodes = list(dag.nodes.values())
        similar_pairs = self.matcher.find_similar_pairs(nodes)
        
        if not similar_pairs:
            return dag
        
        # 按相似度降序排序
        similar_pairs.sort(key=lambda x: x[2], reverse=True)
        
        # 3. 缓存已判断的pair，避免重复调用LLM
        # key: (min_id, max_id), value: (should_merge, reason)
        pair_merge_cache: Dict[Tuple[int, int], bool] = {}
        
        # 4. 迭代合并
        for _ in range(max_iterations):
            merged = False
            
            for node_id_1, node_id_2, score in similar_pairs:
                # 检查节点是否仍存在
                if node_id_1 not in dag.nodes or node_id_2 not in dag.nodes:
                    continue
                
                # 构建缓存key（确保顺序一致）
                cache_key = (min(node_id_1, node_id_2), max(node_id_1, node_id_2))
                
                # 检查缓存
                if cache_key in pair_merge_cache:
                    if not pair_merge_cache[cache_key]:
                        # 已判断为不可合并，跳过
                        continue
                else:
                    # 未判断过，调用LLM判断
                    node1 = dag.nodes[node_id_1]
                    node2 = dag.nodes[node_id_2]
                    
                    should = self.matcher.should_merge(node1, node2)
                    pair_merge_cache[cache_key] = should
                    
                    if not should:
                        continue
                
                # 尝试合并
                keep_id = min(node_id_1, node_id_2)
                remove_id = max(node_id_1, node_id_2)
                
                if self.merge_nodes(dag, keep_id, remove_id):
                    merged = True
                    break
            
            if not merged:
                break
        
        return dag
    
    def simplify_from_db(
        self, 
        plan_id: int,
        repo = None
    ) -> DAG:
        """
        从数据库加载计划树并简化
        
        Args:
            plan_id: 计划ID
            repo: PlanRepository实例（可选）
            
        Returns:
            简化后的DAG结构
        """
        if repo is None:
            from app.repository.plan_repository import PlanRepository
            repo = PlanRepository()
        
        tree = repo.get_plan_tree(plan_id)
        return self.simplify(tree)
    
    def save_dag_to_db(
        self,
        dag: DAG,
        repo = None,
        title_suffix: str = " (Simplified)"
    ) -> int:
        """
        将DAG保存为新的计划（不修改原有数据库）
        
        Args:
            dag: 要保存的DAG结构
            repo: PlanRepository实例（可选）
            title_suffix: 新计划标题后缀
            
        Returns:
            新创建的计划ID
        """
        if repo is None:
            from app.repository.plan_repository import PlanRepository
            repo = PlanRepository()
        
        # 创建新计划
        new_title = dag.title + title_suffix
        new_description = (
            f"{dag.description or ''}\n\n"
            f"---\n"
            f"简化自 Plan #{dag.plan_id}\n"
            f"原节点数: {len(dag.merge_map) + dag.node_count()}\n"
            f"简化后节点数: {dag.node_count()}\n"
            f"合并节点数: {len(dag.merge_map)}"
        ).strip()
        
        new_plan = repo.create_plan(
            title=new_title,
            description=new_description,
            metadata={
                "source_plan_id": dag.plan_id,
                "is_simplified": True,
                "merge_map": dag.merge_map,
            }
        )
        new_plan_id = new_plan.id
        
        # 拓扑排序，确保父节点先创建
        try:
            sorted_ids = dag.topological_sort()
        except ValueError:
            # 如果有环，按ID排序
            sorted_ids = sorted(dag.nodes.keys())
        
        # 节点ID映射: 原ID -> 新ID
        id_map: Dict[int, int] = {}
        
        # 按拓扑顺序创建节点
        for node_id in sorted_ids:
            node = dag.nodes[node_id]
            
            # 确定父节点（取第一个父节点，DAG可能有多个）
            parent_id = None
            if node.parent_ids:
                # 取已创建的第一个父节点
                for pid in sorted(node.parent_ids):
                    if pid in id_map:
                        parent_id = id_map[pid]
                        break
            
            # 映射依赖关系
            mapped_deps = []
            for dep_id in node.dependencies:
                if dep_id in id_map:
                    mapped_deps.append(id_map[dep_id])
            
            # 如果有多个父节点，将额外的父节点加入依赖
            extra_parents = []
            for pid in sorted(node.parent_ids):
                if pid in id_map and id_map[pid] != parent_id:
                    extra_parents.append(id_map[pid])
            mapped_deps.extend(extra_parents)
            
            # 创建任务
            new_node = repo.create_task(
                plan_id=new_plan_id,
                name=node.name,
                instruction=node.instruction,
                parent_id=parent_id,
                dependencies=mapped_deps if mapped_deps else None,
                metadata={
                    "source_node_ids": node.source_node_ids,
                    "original_parent_ids": list(node.parent_ids),
                    "original_child_ids": list(node.child_ids),
                    **node.metadata
                }
            )
            id_map[node_id] = new_node.id
        
        return new_plan_id
    
    def simplify_and_save(
        self,
        plan_id: int,
        repo = None,
        title_suffix: str = " (Simplified)"
    ) -> Tuple[DAG, int]:
        """
        从数据库加载、简化、并保存为新计划
        
        Args:
            plan_id: 原计划ID
            repo: PlanRepository实例（可选）
            title_suffix: 新计划标题后缀
            
        Returns:
            (DAG, 新计划ID) 元组
        """
        if repo is None:
            from app.repository.plan_repository import PlanRepository
            repo = PlanRepository()
        
        # 加载并简化
        dag = self.simplify_from_db(plan_id, repo)
        
        # 保存为新计划
        new_plan_id = self.save_dag_to_db(dag, repo, title_suffix)
        
        return dag, new_plan_id
    
    def visualize_plan(
        self,
        plan_id: int,
        repo = None,
        show_dag: bool = True
    ) -> None:
        """
        可视化计划：打印原始树结构和DAG结构
        
        Args:
            plan_id: 计划ID
            repo: PlanRepository实例（可选）
            show_dag: 是否同时显示DAG结构
        """
        if repo is None:
            from app.repository.plan_repository import PlanRepository
            repo = PlanRepository()
        
        tree = repo.get_plan_tree(plan_id)
        
        # 打印原始树结构
        print("=" * 60)
        print(f"原始树结构 - Plan #{plan_id}: {tree.title}")
        print("=" * 60)
        print(f"节点数: {tree.node_count()}")
        print()
        
        # 打印邻接表
        print("邻接表 (parent -> children):")
        print("-" * 40)
        for parent_id, children in sorted(tree.adjacency.items(), key=lambda x: (x[0] is None, x[0] or 0)):
            if parent_id is None:
                parent_name = "(根)"
            else:
                parent_name = f"[{parent_id}] {tree.nodes[parent_id].name[:25]}"
            children_str = ", ".join(str(c) for c in children) if children else "(无)"
            print(f"  {parent_name} → {children_str}")
        print()
        
        # 打印树形结构
        print("树形结构:")
        print("-" * 40)
        
        def print_tree_node(node_id: int, indent: int = 0):
            node = tree.nodes.get(node_id)
            if not node:
                return
            prefix = "  " * indent + ("├─ " if indent > 0 else "")
            name = node.name[:40] + "..." if len(node.name) > 40 else node.name
            deps = f" [deps: {','.join(map(str, node.dependencies))}]" if node.dependencies else ""
            print(f"{prefix}[{node_id}] {name}{deps}")
            
            children = tree.adjacency.get(node_id, [])
            for child_id in children:
                print_tree_node(child_id, indent + 1)
        
        # 从根节点开始打印
        root_ids = tree.adjacency.get(None, [])
        for root_id in root_ids:
            print_tree_node(root_id)
        
        print()
        
        # 转换并打印DAG
        if show_dag:
            dag = self.tree_to_dag(tree)
            print("=" * 60)
            print("转换后的DAG结构")
            print("=" * 60)
            print(dag.visualize())
            print()
            print(dag.print_adjacency())
    
    def analyze_merge_candidates(
        self,
        plan_id: int,
        repo = None
    ) -> None:
        """
        分析计划中可合并的节点候选
        
        Args:
            plan_id: 计划ID
            repo: PlanRepository实例（可选）
        """
        if repo is None:
            from app.repository.plan_repository import PlanRepository
            repo = PlanRepository()
        
        tree = repo.get_plan_tree(plan_id)
        dag = self.tree_to_dag(tree)
        
        print("=" * 60)
        print(f"合并候选分析 - Plan #{plan_id}: {tree.title}")
        print("=" * 60)
        print()
        
        # 按名称相似度分组
        name_groups: Dict[str, List[int]] = {}
        for node_id, node in dag.nodes.items():
            # 简化名称作为key
            name_key = node.name.strip().lower()
            # 去掉常见前缀如"加载"、"配置"等后的内容可能更相似
            name_groups.setdefault(name_key, []).append(node_id)
        
        print("【同名节点组】")
        print("-" * 40)
        has_same_name = False
        for name, ids in sorted(name_groups.items()):
            if len(ids) >= 2:
                has_same_name = True
                print(f"  \"{name}\":")
                for node_id in ids:
                    node = dag.nodes[node_id]
                    parents = ",".join(map(str, sorted(node.parent_ids))) or "根"
                    print(f"    [{node_id}] ← 父:{parents}")
        
        if not has_same_name:
            print("  (无同名节点)")
        print()
        
        # 检查可合并性
        print("【可合并性检查】")
        print("-" * 40)
        
        all_ids = list(dag.nodes.keys())
        merge_candidates = []
        
        for i in range(len(all_ids)):
            for j in range(i + 1, len(all_ids)):
                id1, id2 = all_ids[i], all_ids[j]
                can, reason = self.can_merge(dag, id1, id2)
                
                # 只显示同名或相似名称的节点
                node1 = dag.nodes[id1]
                node2 = dag.nodes[id2]
                
                # 简单的名称相似判断
                name1_key = node1.name.strip().lower()
                name2_key = node2.name.strip().lower()
                
                if name1_key == name2_key:
                    status = "✓ 可合并" if can else f"✗ {reason}"
                    print(f"  [{id1}] {node1.name[:25]}")
                    print(f"  [{id2}] {node2.name[:25]}")
                    print(f"    → {status}")
                    print()
                    
                    if can:
                        merge_candidates.append((id1, id2))
        
        if merge_candidates:
            print("【建议合并的节点对】")
            print("-" * 40)
            for id1, id2 in merge_candidates:
                n1, n2 = dag.nodes[id1].name, dag.nodes[id2].name
                print(f"  [{id1}] + [{id2}]: {n1[:30]}")


# 便捷函数
def visualize_plan(plan_id: int) -> None:
    """便捷函数：可视化计划结构"""
    from app.database import init_db
    init_db()
    
    simplifier = TreeSimplifier()
    simplifier.visualize_plan(plan_id)


def analyze_merges(plan_id: int) -> None:
    """便捷函数：分析可合并节点"""
    from app.database import init_db
    init_db()
    
    simplifier = TreeSimplifier()
    simplifier.analyze_merge_candidates(plan_id)


def analyze_merges_llm(plan_id: int) -> None:
    """便捷函数：使用LLM分析可合并节点"""
    from app.database import init_db
    init_db()
    
    matcher = LLMSimilarityMatcher(threshold=0.8)
    simplifier = TreeSimplifier(matcher=matcher)
    
    from app.repository.plan_repository import PlanRepository
    repo = PlanRepository()
    tree = repo.get_plan_tree(plan_id)
    dag = simplifier.tree_to_dag(tree)
    
    print("=" * 60)
    print(f"LLM合并分析 - Plan #{plan_id}: {tree.title}")
    print("=" * 60)
    
    # 使用LLM找相似对
    nodes = list(dag.nodes.values())
    similar_pairs = matcher.find_similar_pairs(nodes)
    
    if not similar_pairs:
        print("  未找到可合并的节点对")
        return
    
    print(f"\n找到 {len(similar_pairs)} 对相似节点:")
    print("-" * 40)
    
    for id1, id2, sim in similar_pairs:
        n1 = dag.nodes.get(id1)
        n2 = dag.nodes.get(id2)
        if n1 and n2:
            can, reason = simplifier.can_merge(dag, id1, id2)
            status = "✓ 可合并" if can else f"✗ {reason}"
            print(f"  [{id1}] {n1.name[:25]}")
            print(f"  [{id2}] {n2.name[:25]}")
            print(f"    相似度: {sim:.2f} | {status}")
            print()


if __name__ == "__main__":
    plan_id = 27
    visualize_plan(plan_id)
    print("\n" * 2)
    analyze_merges(plan_id)