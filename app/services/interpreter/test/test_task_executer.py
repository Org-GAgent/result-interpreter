"""
TaskExecutor 测试文件

测试任务执行器的完整流程
"""
import sys
import os
import unittest
import tempfile

# 确保项目根目录在 path 中
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

from dotenv import load_dotenv
load_dotenv()

from app.services.interpreter.task_executer import TaskExecutor, TaskType, execute_task


class TestTaskExecutor(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        """创建测试用的临时CSV文件"""
        cls.temp_dir = tempfile.mkdtemp()
        cls.test_csv_path = os.path.join(cls.temp_dir, "test_sales.csv")
        
        # 创建测试数据
        csv_content = """Date,Product,Sales,Quantity
2023-01-01,Apple,100,10
2023-01-02,Banana,150,15
2023-01-03,Apple,200,20
2023-01-04,Orange,80,8
2023-01-05,Banana,120,12
"""
        with open(cls.test_csv_path, 'w', encoding='utf-8') as f:
            f.write(csv_content)
        
        print(f"\n测试数据文件创建于: {cls.test_csv_path}")
    
    @classmethod
    def tearDownClass(cls):
        """清理临时文件"""
        import shutil
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_task_type_analysis(self):
        """测试LLM任务类型判断"""
        executor = TaskExecutor(data_file_path=self.test_csv_path)
        
        # 测试需要代码的任务
        task_type = executor._analyze_task_type(
            "计算平均销售额", 
            "计算所有产品的平均销售额"
        )
        print(f"✓ '计算平均销售额' -> {task_type.value}")
        
        # 测试可能不需要代码的任务
        task_type = executor._analyze_task_type(
            "解释数据集", 
            "请解释这个数据集包含什么信息，各列代表什么含义"
        )
        print(f"✓ '解释数据集' -> {task_type.value}")

    def test_execute_code_task(self):
        """测试代码任务执行（需要Docker环境）"""
        print("\n测试代码任务执行...")
        
        executor = TaskExecutor(data_file_path=self.test_csv_path)
        result = executor.execute(
            task_title="计算总销售额",
            task_description="读取CSV文件并计算Sales列的总和"
        )
        
        print(f"任务类型: {result.task_type}")
        print(f"执行成功: {result.success}")
        print(f"尝试次数: {result.total_attempts}")
        
        if result.success:
            print(f"代码描述: {result.code_description}")
            print(f"输出结果: {result.code_output[:200] if result.code_output else 'None'}...")
        else:
            print(f"错误信息: {result.error_message}")
            print(f"代码错误: {result.code_error}")
        
        # 注意: 此测试需要Docker环境，可能会失败
        self.assertEqual(result.task_type, TaskType.CODE_REQUIRED)

    def test_execute_text_task(self):
        """测试纯文本任务执行"""
        print("\n测试纯文本任务执行...")
        
        executor = TaskExecutor(data_file_path=self.test_csv_path)
        result = executor.execute(
            task_title="解释数据集结构",
            task_description="请解释这个数据集的结构和各列的含义，不需要代码",
            force_code=False  # 强制使用文本模式
        )
        
        print(f"任务类型: {result.task_type}")
        print(f"执行成功: {result.success}")
        
        if result.success:
            print(f"LLM回答: {result.text_response[:300] if result.text_response else 'None'}...")
        else:
            print(f"错误信息: {result.error_message}")
        
        self.assertEqual(result.task_type, TaskType.TEXT_ONLY)

    def test_convenience_function(self):
        """测试便捷函数"""
        print("\n测试便捷函数 execute_task...")
        
        result = execute_task(
            data_file_path=self.test_csv_path,
            task_title="显示数据预览",
            task_description="显示数据的前5行"
        )
        
        print(f"执行成功: {result.success}")
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
