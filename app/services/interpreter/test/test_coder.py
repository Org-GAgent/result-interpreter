import sys
import os
import unittest

# Ensure project root is in path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

from dotenv import load_dotenv
load_dotenv() # Load env for LLM credentials

from app.services.interpreter.coder import CodeGenerator
from app.services.interpreter.metadata import DatasetMetadata, ColumnMetadata

class TestCodeGenerator(unittest.TestCase):
    def setUp(self):
        # Create a Mock Dataset Metadata
        self.metadata = DatasetMetadata(
            filename="sales_data.csv",
            file_format="csv",
            file_size_bytes=1024,
            total_rows=100,
            total_columns=3,
            columns=[
                ColumnMetadata(name="Date", dtype="object", sample_values=["2023-01-01", "2023-01-02"], null_count=0, unique_count=100),
                ColumnMetadata(name="Product", dtype="object", sample_values=["Apple", "Banana"], null_count=0, unique_count=5),
                ColumnMetadata(name="Sales", dtype="int64", sample_values=[100, 200, 150], null_count=0, unique_count=50)
            ]
        )
        # 第二个数据集用于多数据集测试
        self.metadata2 = DatasetMetadata(
            filename="inventory_data.csv",
            file_format="csv",
            file_size_bytes=2048,
            total_rows=200,
            total_columns=4,
            columns=[
                ColumnMetadata(name="ProductID", dtype="int64", sample_values=[1, 2, 3], null_count=0, unique_count=50),
                ColumnMetadata(name="ProductName", dtype="object", sample_values=["Apple", "Banana", "Orange"], null_count=0, unique_count=50),
                ColumnMetadata(name="Stock", dtype="int64", sample_values=[500, 300, 200], null_count=0, unique_count=100),
                ColumnMetadata(name="Price", dtype="float64", sample_values=[1.5, 2.0, 3.5], null_count=0, unique_count=30)
            ]
        )
        self.generator = CodeGenerator()

    def test_code_generation_needed(self):
        print("\nTesting task THAT NEEDS code...")
        title = "Calculate Average Sales"
        desc = "Calculate the average sales value and plot a bar chart of sales by product."
        
        # 使用单个数据集（列表形式）
        result = self.generator.generate([self.metadata], title, desc)
        
        print(f"代码描述: {result.description}")
        print(f"代码片段:\n{result.code[:150]}..." if len(result.code) > 150 else f"代码:\n{result.code}")
             
        self.assertIsNotNone(result.code)
        self.assertTrue(len(result.code) > 0)
        self.assertIn("pandas", result.code)
        self.assertIn("read_csv", result.code)
        self.assertIsNotNone(result.description)

    def test_multiple_datasets(self):
        print("\n测试多数据集代码生成...")
        title = "Join Sales and Inventory"
        desc = "Join sales_data.csv and inventory_data.csv by Product name to analyze sales vs stock levels."
        
        # 传入多个数据集
        result = self.generator.generate([self.metadata, self.metadata2], title, desc)
        
        print(f"代码描述: {result.description}")
        print(f"代码片段:\n{result.code[:200]}..." if len(result.code) > 200 else f"代码:\n{result.code}")
             
        self.assertIsNotNone(result.code)
        self.assertTrue(len(result.code) > 0)
        self.assertIsNotNone(result.description)

    def test_no_code_needed(self):
        print("\n测试简单任务的代码生成...")
        title = "Show data preview"
        desc = "Show the first 5 rows of the dataset."
        
        result = self.generator.generate([self.metadata], title, desc)
        
        print(f"代码描述: {result.description}")
        self.assertIsNotNone(result.code)
        self.assertIsNotNone(result.description)

    def test_fix_code(self):
        print("\n测试代码修复功能...")
        title = "Fix Code"
        desc = "Fix the broken code."
        broken_code = "print(undefined_variable)"
        error_msg = "NameError: name 'undefined_variable' is not defined"
        
        result = self.generator.fix_code([self.metadata], title, desc, broken_code, error_msg)
        
        print(f"代码描述: {result.description}")
        print(f"修复后代码片段:\n{result.code[:100]}..." if len(result.code) > 100 else f"代码:\n{result.code}")
             
        self.assertIsNotNone(result.code)
        self.assertIsNotNone(result.description)

    def test_print_full_prompt(self):
        """测试：打印完整的提示词，查看metadata格式"""
        print("\n" + "="*80)
        print("测试：打印完整提示词（包含多数据集metadata）")
        print("="*80)
        
        from app.services.interpreter.prompts.coder_prompt import CODER_SYSTEM_PROMPT, CODER_USER_PROMPT_TEMPLATE
        
        # 格式化数据集信息（复用 CodeGenerator 的方法）
        datasets_text = self.generator._format_datasets([self.metadata, self.metadata2])
        
        task_title = "Analyze Sales vs Inventory"
        task_description = "Join sales and inventory data to find products with high sales but low stock."
        
        user_prompt = CODER_USER_PROMPT_TEMPLATE.format(
            datasets_info=datasets_text,
            task_title=task_title,
            task_description=task_description
        )
        
        full_prompt = f"{CODER_SYSTEM_PROMPT}\n\n{user_prompt}"
        
        print("\n【完整提示词内容】")
        print("-"*80)
        print(full_prompt)
        print("-"*80)
        print(f"\n提示词总长度: {len(full_prompt)} 字符")
        
        # 断言确保格式正确
        self.assertIn("sales_data.csv", full_prompt)
        self.assertIn("inventory_data.csv", full_prompt)
        self.assertIn("Dataset 1", full_prompt)
        self.assertIn("Dataset 2", full_prompt)

if __name__ == "__main__":
    unittest.main()
