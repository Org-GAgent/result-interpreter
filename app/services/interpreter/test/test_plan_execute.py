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
    这是一个药物疗效对比实验。研究人员测试了3种不同的药物（Drug_A, Drug_B, Placebo）
    对患者血压降低效果的影响。实验持续4周，每周测量一次。
    
    数据字段：
    - patient_id: 患者编号
    - age: 患者年龄
    - gender: 性别 (M/F)
    - drug_group: 药物组别 (Drug_A, Drug_B, Placebo)
    - baseline_bp: 基线血压 (mmHg)
    - week1_bp: 第1周血压
    - week2_bp: 第2周血压
    - week3_bp: 第3周血压
    - week4_bp: 第4周血压 (最终血压)
    - side_effects: 副作用数量
    """
    
    results_dir = os.path.join(current_dir, "results")
    os.makedirs(results_dir, exist_ok=True)
    
    csv_path = os.path.join(results_dir, "drug_trial_results.csv")
    
    # 生成模拟数据
    random.seed(42)  # 固定随机种子以保证可重复性
    
    drugs = ["Drug_A", "Drug_B", "Placebo"]
    genders = ["M", "F"]
    
    rows = ["patient_id,age,gender,drug_group,baseline_bp,week1_bp,week2_bp,week3_bp,week4_bp,side_effects"]
    
    patient_id = 1
    for drug in drugs:
        for _ in range(20):  # 每组20个患者
            age = random.randint(35, 70)
            gender = random.choice(genders)
            baseline = random.randint(140, 180)  # 高血压患者
            
            # 根据药物组别模拟不同的降压效果
            if drug == "Drug_A":
                # Drug_A 效果最好，每周降低约5-8mmHg
                w1 = baseline - random.randint(4, 8)
                w2 = w1 - random.randint(4, 8)
                w3 = w2 - random.randint(3, 6)
                w4 = w3 - random.randint(2, 5)
                side_effects = random.randint(0, 2)
            elif drug == "Drug_B":
                # Drug_B 效果中等，每周降低约3-5mmHg
                w1 = baseline - random.randint(2, 5)
                w2 = w1 - random.randint(2, 5)
                w3 = w2 - random.randint(2, 4)
                w4 = w3 - random.randint(1, 3)
                side_effects = random.randint(0, 4)
            else:
                # Placebo 几乎无效果
                w1 = baseline - random.randint(-2, 3)
                w2 = w1 - random.randint(-2, 3)
                w3 = w2 - random.randint(-2, 2)
                w4 = w3 - random.randint(-2, 2)
                side_effects = random.randint(0, 1)
            
            rows.append(f"{patient_id},{age},{gender},{drug},{baseline},{w1},{w2},{w3},{w4},{side_effects}")
            patient_id += 1
    
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(rows))
    
    logger.info(f"实验数据已生成: {csv_path}")
    logger.info(f"共 {patient_id - 1} 条记录")
    
    return csv_path


def get_experiment_description():
    """返回实验描述"""
    return """
## 实验背景

这是一项随机对照临床试验，旨在评估两种新型降压药物（Drug_A 和 Drug_B）与安慰剂（Placebo）相比的疗效和安全性。

## 实验设计

- **受试者**: 60名高血压患者（基线收缩压 140-180 mmHg）
- **分组**: 随机分为3组，每组20人
  - Drug_A 组：接受新药A治疗
  - Drug_B 组：接受新药B治疗
  - Placebo 组：接受安慰剂
- **观察周期**: 4周
- **测量指标**: 每周测量收缩压，记录副作用

## 数据字段说明

| 字段 | 说明 |
|------|------|
| patient_id | 患者编号 |
| age | 年龄 |
| gender | 性别 (M/F) |
| drug_group | 药物组别 |
| baseline_bp | 基线血压 (mmHg) |
| week1_bp ~ week4_bp | 各周血压测量值 |
| side_effects | 副作用发生次数 |

## 分析目标

1. 分析各组患者的基线特征是否均衡
2. 比较三组药物的降压效果（血压变化趋势）
3. 评估各组的副作用情况
4. 得出哪种药物疗效最好且副作用可接受的结论
5. 生成统计图表支持上述分析
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
    print("   端到端测试: 药物临床试验数据分析")
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
#     plan_title = "药物临床试验数据分析"
#     plan_description = f"""
# {experiment_desc}

# 请根据以上实验背景和数据，制定完整的数据分析计划。
# 需要生成图表来可视化分析结果，所有图表保存到 results 文件夹下。
# """
    
    # plan = repo.create_plan(title=plan_title, description=plan_description)
    # plan_id = plan.id
    plan_id = 18
    logger.info(f"计划创建成功: ID={plan_id}")
    
    # Step 4: 使用 PlanDecomposer 分解任务
    # print("\n[Step 4] 任务分解 (调用LLM)...")
    # decomposer = PlanDecomposer(repo=repo)
    # decomp_result = decomposer.run_plan(plan_id, max_depth=5)
    
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
        data_file_path=csv_path,
        output_dir=output_dir,
        llm_provider="qwen",
        docker_image="agent-plotter",
        docker_timeout=120,
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
