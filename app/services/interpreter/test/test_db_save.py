"""
测试：验证任务执行结果是否正确保存到数据库

测试流程：
1. 创建一个计划并分解
2. 执行计划
3. 从数据库读取每个节点，检查 execution_result 字段
"""

import sys
import os
import json
import tempfile
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(project_root))

from app.database import init_db
from app.repository.plan_repository import PlanRepository
from app.services.interpreter.plan_execute import PlanExecutorInterpreter


def test_db_save():
    """测试执行结果是否正确保存到数据库"""
    
    # 0. 初始化数据库
    init_db()
    
    # 1. 创建临时CSV数据文件
    temp_dir = tempfile.mkdtemp()
    data_file = os.path.join(temp_dir, "test_data.csv")
    
    with open(data_file, "w", encoding="utf-8") as f:
        f.write("name,score,grade\n")
        f.write("Alice,85,A\n")
        f.write("Bob,72,B\n")
        f.write("Charlie,90,A\n")
        f.write("David,65,C\n")
    
    print(f"✓ 创建测试数据文件: {data_file}")
    
    # 2. 创建一个简单的计划
    repo = PlanRepository()
    
    plan = repo.create_plan(
        title="成绩分析计划",
        description="计算学生成绩平均分"
    )
    plan_id = plan.id
    print(f"✓ 创建计划: plan_id={plan_id}")
    
    # 添加根任务
    root_task = repo.create_task(
        plan_id=plan_id,
        parent_id=None,
        name="分析学生成绩",
        instruction="读取CSV文件，计算所有学生的平均分，并输出结果"
    )
    root_id = root_task.id
    print(f"✓ 添加根任务: task_id={root_id}")
    
    # 3. 执行计划
    print("\n开始执行计划...")
    executor = PlanExecutorInterpreter(
        plan_id=plan_id,
        data_file_paths=[data_file],
        output_dir=temp_dir,
        repo=repo
    )
    
    result = executor.execute()
    print(f"✓ 计划执行完成: success={result.success}")
    
    # 4. 从数据库读取节点，检查 execution_result
    print("\n检查数据库中的执行结果...")
    
    node = repo.get_node(plan_id, root_id)
    print(f"\n节点 [{root_id}] {node.name}")
    print(f"  状态: {node.status}")
    
    if node.execution_result:
        exec_result = json.loads(node.execution_result)
        print(f"  execution_result 字段已保存 ✓")
        print(f"  - task_type: {exec_result.get('task_type')}")
        print(f"  - code_description: {exec_result.get('code_description', 'N/A')[:100]}...")
        print(f"  - code: {len(exec_result.get('code') or '')} 字符")
        print(f"  - code_output: {exec_result.get('code_output', 'N/A')[:200] if exec_result.get('code_output') else 'N/A'}...")
        print(f"  - error: {exec_result.get('error')}")
        
        # 验证关键字段
        assert exec_result.get('task_type') is not None, "task_type 应该不为空"
        print("\n✅ 测试通过：执行结果已正确保存到数据库")
    else:
        print("  execution_result 字段为空 ✗")
        print("\n❌ 测试失败：执行结果未保存到数据库")
        return False
    
    return True


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    success = test_db_save()
    sys.exit(0 if success else 1)
