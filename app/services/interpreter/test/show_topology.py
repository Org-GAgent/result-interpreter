"""
展示计划任务的拓扑执行顺序

传入 plan_id，从数据库读取计划树，分析并展示任务执行顺序。
"""

import sys
import os
from typing import List, Dict, Set

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))

if project_root not in sys.path:
    sys.path.insert(0, project_root)
from app.database import init_db
from app.repository.plan_repository import PlanRepository
from app.services.plans.plan_decomposer import PlanDecomposer


def print_plan_tree(repo: PlanRepository, plan_id: int):
    """打印计划树结构（更清晰的树状线条 + 叶子标记）"""
    tree = repo.get_plan_tree(plan_id)

    print(f"\n{'='*60}")
    print(f"计划 #{tree.id}: {tree.title}")
    print(f"{'='*60}")
    print(f"节点数: {len(tree.nodes)}")
    print("\n任务结构:")

    def fmt_deps(node):
        if not getattr(node, "dependencies", None):
            return ""
        return f" [deps: {', '.join(map(str, node.dependencies))}]"

    def fmt_leaf(node_id):
        children = tree.adjacency.get(node_id, [])
        return " [leaf]" if not children else f" [children: {len(children)}]"

    def fmt_instruction(node, indent_prefix):
        if not getattr(node, "instruction", None):
            return
        text = node.instruction.strip()
        if not text:
            return
        # 截断显示
        short = text[:80] + ("..." if len(text) > 80 else "")
        print(f"{indent_prefix}    > {short}")

    def print_subtree(node_id, prefix="", is_last=True):
        node = tree.nodes.get(node_id)
        if not node:
            return

        connector = "└─ " if is_last else "├─ "
        line = f"{prefix}{connector}[{node.id}] {node.name}{fmt_deps(node)}{fmt_leaf(node_id)}"
        print(line)

        # instruction 的缩进：根据是否 last 决定竖线是否延续
        child_prefix = prefix + ("   " if is_last else "│  ")
        fmt_instruction(node, child_prefix)

        children = tree.adjacency.get(node_id, [])
        # 保持原先 position 排序
        children = sorted(children, key=lambda x: tree.nodes[x].position)

        for i, child_id in enumerate(children):
            last_child = (i == len(children) - 1)
            print_subtree(child_id, prefix=child_prefix, is_last=last_child)

    roots = tree.adjacency.get(None, [])
    roots = sorted(roots, key=lambda x: tree.nodes[x].position)

    for i, root_id in enumerate(roots):
        last_root = (i == len(roots) - 1)
        print_subtree(root_id, prefix="", is_last=last_root)

    print()

from collections import defaultdict, deque
from typing import List, Tuple, Set, Optional

def print_all_dependencies(
    repo: "PlanRepository",
    plan_id: int,
    include_tree_edges: bool = False,
    show_missing_nodes: bool = True,
):
    """
    打印计划中的所有依赖关系（边）。
    
    - 显式依赖：来自 node.dependencies，打印为  dep -> node
    - 可选结构边：来自 tree.adjacency（父->子），也按边打印
    
    Args:
        include_tree_edges: True 时把“父子结构”也当作依赖边输出
        show_missing_nodes: True 时若依赖引用了不存在的节点，额外提示
    """
    tree = repo.get_plan_tree(plan_id)

    # 1) 收集显式依赖边：dep -> node
    dep_edges: List[Tuple[int, int]] = []
    missing: List[Tuple[int, int]] = []

    for node_id, node in tree.nodes.items():
        deps = getattr(node, "dependencies", None) or []
        for d in deps:
            dep_edges.append((int(d), int(node_id)))
            if show_missing_nodes and int(d) not in tree.nodes:
                missing.append((int(d), int(node_id)))

    # 2) 可选：收集结构边（父->子）作为依赖边
    tree_edges: List[Tuple[Optional[int], int]] = []
    if include_tree_edges:
        for parent_id, children in tree.adjacency.items():
            if parent_id is None:
                continue
            for child_id in children:
                tree_edges.append((int(parent_id), int(child_id)))

    # 3) 打印
    print(f"\n{'='*60}")
    print(f"Plan #{tree.id}: {tree.title}")
    print(f"{'='*60}")

    print("\n[Explicit dependency edges] (dep -> node)")
    if not dep_edges:
        print("  (none)")
    else:
        for d, n in sorted(dep_edges):
            d_name = tree.nodes[d].name if d in tree.nodes else "(missing)"
            n_name = tree.nodes[n].name if n in tree.nodes else "(missing)"
            print(f"  {d:>3} -> {n:<3} | {d_name}  ==>  {n_name}")

    if include_tree_edges:
        print("\n[Tree structure edges as dependencies] (parent -> child)")
        if not tree_edges:
            print("  (none)")
        else:
            for p, c in sorted(tree_edges):
                p_name = tree.nodes[p].name if p in tree.nodes else "(missing)"
                c_name = tree.nodes[c].name if c in tree.nodes else "(missing)"
                print(f"  {p:>3} -> {c:<3} | {p_name}  ==>  {c_name}")

    # 4) 按节点打印“我依赖谁”
    print("\n[Per-node dependencies]")
    for node_id in sorted(tree.nodes):
        node = tree.nodes[node_id]
        deps = getattr(node, "dependencies", None) or []
        if deps:
            dep_list = ", ".join(str(int(x)) for x in deps)
            print(f"  [{node_id:>3}] {node.name}  depends on: {dep_list}")

    # 5) 缺失依赖提示
    if show_missing_nodes and missing:
        print("\n[Warning] Dependencies pointing to missing nodes:")
        for d, n in missing:
            n_name = tree.nodes[n].name if n in tree.nodes else "(missing)"
            print(f"  missing dep {d} referenced by node {n} ({n_name})")

    print()

from collections import deque
from collections import defaultdict
from typing import Dict, List, Tuple, Set

def build_dep_graph(tree) -> Tuple[Dict[int, Set[int]], Dict[int, Set[int]]]:
    """
    基于 node.dependencies 构建执行依赖图（DAG）：
    - forward[u] = {v1, v2, ...} 表示 u -> v
    - reverse[v] = {u1, u2, ...} 表示 u -> v
    """
    forward: Dict[int, Set[int]] = defaultdict(set)
    reverse: Dict[int, Set[int]] = defaultdict(set)

    node_ids = set(tree.nodes.keys())
    for nid, node in tree.nodes.items():
        deps = getattr(node, "dependencies", None) or []
        for d in deps:
            d = int(d)
            nid = int(nid)
            # 只收集引用在图内的依赖（你也可以选择保留 missing）
            if d in node_ids and nid in node_ids:
                forward[d].add(nid)
                reverse[nid].add(d)

    # 保证所有节点都有 key
    for nid in node_ids:
        forward.setdefault(nid, set())
        reverse.setdefault(nid, set())

    return forward, reverse

def topo_layers(forward: Dict[int, Set[int]], reverse: Dict[int, Set[int]]) -> List[List[int]]:
    """
    Kahn 拓扑分层：
    返回 layers = [[layer0 nodes], [layer1 nodes], ...]
    若存在环，会在最后抛错。
    """
    indeg = {v: len(reverse[v]) for v in reverse}
    q = deque(sorted([v for v, d in indeg.items() if d == 0]))
    layers: List[List[int]] = []

    visited = 0
    current_layer = []
    next_q = deque()

    # 分层：同一轮入队的看作同一层
    while q:
        current_layer.clear()
        while q:
            v = q.popleft()
            current_layer.append(v)

        layers.append(current_layer.copy())

        for v in current_layer:
            visited += 1
            for w in forward[v]:
                indeg[w] -= 1
                if indeg[w] == 0:
                    next_q.append(w)

        q = deque(sorted(next_q))
        next_q.clear()

    if visited != len(indeg):
        # 有环或缺失节点导致无法消除入度
        raise ValueError("Dependency graph is not a DAG (cycle detected or invalid dependencies).")

    return layers


def print_dep_graph_ascii(repo, plan_id: int, show_names: bool = True, max_name_len: int = 40):
    """
    按拓扑层打印依赖图（仅 node.dependencies）。
    """
    tree = repo.get_plan_tree(plan_id)
    forward, reverse = build_dep_graph(tree)

    layers = topo_layers(forward, reverse)

    print(f"\nExecution Dependency Graph (by layers) - Plan #{tree.id}: {tree.title}")
    print("=" * 80)

    for i, layer in enumerate(layers):
        print(f"\nLayer {i} (ready together):")
        for nid in layer:
            deps = sorted(list(reverse[nid]))
            deps_str = ", ".join(map(str, deps)) if deps else "-"
            if show_names:
                name = tree.nodes[nid].name
                if len(name) > max_name_len:
                    name = name[:max_name_len] + "..."
                print(f"  [{nid:>3}] {name}    deps: {deps_str}")
            else:
                print(f"  [{nid:>3}] deps: {deps_str}")

    # 再补充一份“出边”视角，方便看谁触发谁
    print(f"\nEdges (dep -> node):")
    edges = []
    for u, vs in forward.items():
        for v in vs:
            edges.append((u, v))
    for u, v in sorted(edges):
        print(f"  {u} -> {v}")

def print_dep_edges_only(repo, plan_id: int):
    """
    只打印执行依赖边（dep -> node），
    依赖来源仅为 node.dependencies。
    """
    tree = repo.get_plan_tree(plan_id)

    print(f"\nExecution dependency edges for Plan #{tree.id}: {tree.title}")
    print("-" * 50)

    has_edge = False
    for node_id, node in sorted(tree.nodes.items()):
        deps = getattr(node, "dependencies", None) or []
        for dep in deps:
            print(f"{int(dep)} -> {int(node_id)}")
            has_edge = True

    if not has_edge:
        print("(no dependency edges)")


if __name__ == "__main__":

    # 初始化数据库
    init_db()
    repo = PlanRepository()

    plan_id = 28
    print_plan_tree(repo, plan_id=plan_id)

    print_all_dependencies(repo, plan_id=plan_id)

    print_dep_graph_ascii(repo, plan_id=plan_id)

    print_dep_edges_only(repo, plan_id=plan_id)