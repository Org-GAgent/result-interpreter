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
        self.generator = CodeGenerator()

    def test_code_generation_needed(self):
        print("\nTesting task THAT NEEDS code...")
        title = "Calculate Average Sales"
        desc = "Calculate the average sales value and plot a bar chart of sales by product."
        
        result = self.generator.generate(self.metadata, title, desc)
        
        print(f"代码描述: {result.description}")
        print(f"代码片段:\n{result.code[:150]}..." if len(result.code) > 150 else f"代码:\n{result.code}")
             
        self.assertIsNotNone(result.code)
        self.assertTrue(len(result.code) > 0)
        self.assertIn("pandas", result.code)
        self.assertIn("read_csv", result.code)
        self.assertIsNotNone(result.description)

    def test_no_code_needed(self):
        print("\n测试简单任务的代码生成...")
        title = "Show data preview"
        desc = "Show the first 5 rows of the dataset."
        
        result = self.generator.generate(self.metadata, title, desc)
        
        print(f"代码描述: {result.description}")
        self.assertIsNotNone(result.code)
        self.assertIsNotNone(result.description)

    def test_fix_code(self):
        print("\n测试代码修复功能...")
        title = "Fix Code"
        desc = "Fix the broken code."
        broken_code = "print(undefined_variable)"
        error_msg = "NameError: name 'undefined_variable' is not defined"
        
        result = self.generator.fix_code(self.metadata, title, desc, broken_code, error_msg)
        
        print(f"代码描述: {result.description}")
        print(f"修复后代码片段:\n{result.code[:100]}..." if len(result.code) > 100 else f"代码:\n{result.code}")
             
        self.assertIsNotNone(result.code)
        self.assertIsNotNone(result.description)

if __name__ == "__main__":
    unittest.main()
