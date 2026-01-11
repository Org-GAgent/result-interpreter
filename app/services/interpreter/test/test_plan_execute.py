"""
端到端测试: 从实验数据到计划执行

测试流程：
1. 创建一个模拟实验结果的CSV文件
2. 描述实验背景和数据含义
3. 使用 PlanDecomposer 创建计划并自动分解任务
4. 使用 PlanExecutorInterpreter 执行计划
"""

import sys
import os
import logging
import random

# 添加项目根目录
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from app.database import init_db
from app.repository.plan_repository import PlanRepository
from app.services.plans.plan_decomposer import PlanDecomposer
from app.services.interpreter.plan_execute import PlanExecutorInterpreter

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def create_experiment_csv():
    """
    创建模拟实验数据CSV
    
    实验背景：
    某高中对三个班级的学生进行了一次数学测验，想了解不同班级的成绩分布情况。
    
    数据字段：
    - student_id: 学生编号
    - class: 班级 (A/B/C)
    - gender: 性别 (M/F)
    - score: 测验成绩 (0-100)
    """
    
    results_dir = os.path.join(current_dir, "results")
    os.makedirs(results_dir, exist_ok=True)
    
    csv_path = os.path.join(results_dir, "math_test_scores.csv")
    
    # 生成模拟数据
    random.seed(42)
    
    classes = ["A", "B", "C"]
    genders = ["M", "F"]
    
    rows = ["student_id,class,gender,score"]
    
    student_id = 1
    for cls in classes:
        for _ in range(8):  # 每班8个学生，共24人
            gender = random.choice(genders)
            
            # 不同班级成绩分布不同
            if cls == "A":
                score = random.randint(75, 98)  # A班成绩较好
            elif cls == "B":
                score = random.randint(60, 85)  # B班成绩中等
            else:
                score = random.randint(50, 78)  # C班成绩较低
            
            rows.append(f"{student_id},{cls},{gender},{score}")
            student_id += 1
    
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(rows))
    
    logger.info(f"实验数据已生成: {csv_path}")
    logger.info(f"共 {student_id - 1} 条记录")
    
    return csv_path


def get_experiment_description():
    """返回实验描述"""
    return """
## 实验背景

某高中想了解三个班级（A、B、C班）的数学成绩分布情况，进行了一次统一测验。

## 数据说明

- **样本**: 24名学生，每班8人
- **测验**: 满分100分的数学测验

## 数据字段说明

| 字段 | 说明 |
|------|------|
| student_id | 学生编号 |
| class | 班级 (A/B/C) |
| gender | 性别 (M/F) |
| score | 测验成绩 (0-100) |

## 分析目标

1. 计算各班级的平均分、最高分、最低分
2. 比较三个班级的成绩分布（箱线图）
3. 分析性别对成绩的影响
4. 给出哪个班级成绩最好的结论
"""


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


def main():
    print("\n" + "="*60)
    print("   端到端测试: 学生数学成绩分析")
    print("="*60)
    
    # 初始化数据库
    init_db()
    repo = PlanRepository()
    
    # Step 1: 创建实验数据CSV
    print("\n[Step 1] 创建实验数据...")
    csv_path = create_experiment_csv()
    
    # Step 2: 获取实验描述
    experiment_desc = get_experiment_description()
    print("\n[Step 2] 实验描述:")
    print(experiment_desc[:500] + "...")
    
    # Step 3: 创建计划
#     print("\n[Step 3] 创建分析计划...")
#     plan_title = "学生数学成绩分析"
#     plan_description = f"""
# {experiment_desc}

# 请根据以上背景和数据，制定完整的数据分析计划。
# 需要生成图表来可视化分析结果，所有图表保存到 results 文件夹下。
# """
    
    # plan = repo.create_plan(title=plan_title, description=plan_description)
    plan_id = 25
    # logger.info(f"计划创建成功: ID={plan_id}")
    
    # Step 4: 使用 PlanDecomposer 分解任务
    # print("\n[Step 4] 任务分解 (调用LLM)...")
    # decomposer = PlanDecomposer(repo=repo)
    # decomp_result = decomposer.run_plan(plan_id, max_depth=3, node_budget=10)
    
    # if decomp_result.stopped_reason:
    #     print(f"  分解停止: {decomp_result.stopped_reason}")
    # print(f"  创建了 {len(decomp_result.created_tasks)} 个任务")
    
    # 打印计划结构
    print_plan_tree(repo, plan_id)
    
    # 确认执行
    print("="*60)
    confirm = input("是否开始执行计划? (y/n): ").strip().lower()
    if confirm != 'y':
        print("已取消执行")
        print(f"计划ID: {plan_id}, 可稍后手动执行")
        return
    
    # Step 5: 执行计划
    print("\n[Step 5] 执行计划...")
    print("="*60)
    
    output_dir = os.path.join(current_dir, "results")
    
    executor = PlanExecutorInterpreter(
        plan_id=plan_id,
        data_file_paths=[csv_path],
        output_dir=output_dir,
        llm_provider="qwen",
        docker_image="agent-plotter",
        docker_timeout=300,
        repo=repo
    )
    
    result = executor.execute()
    
    # 打印结果
    print("\n" + "="*60)
    print("   执行完成!")
    print("="*60)
    print(f"成功: {result.success}")
    print(f"总节点: {result.total_nodes}")
    print(f"完成: {result.completed_nodes}")
    print(f"失败: {result.failed_nodes}")
    print(f"跳过: {result.skipped_nodes}")
    
    if result.all_generated_files:
        print(f"\n生成的文件 ({len(result.all_generated_files)}):")
        for f in result.all_generated_files:
            print(f"  - {os.path.basename(f)}")
    
    # 打印各节点执行详情
    print("\n节点执行详情:")
    for node_id, record in sorted(result.node_records.items()):
        status_icon = "✅" if record.status.value == "completed" else "❌"
        print(f"  {status_icon} [{node_id}] {record.node_name}")
        if record.code_description:
            print(f"       描述: {record.code_description[:50]}...")
        if record.error_message:
            print(f"       错误: {record.error_message[:100]}")
    
    return result


if __name__ == "__main__":
    main()
