"""
测试 metadata 模块全流程。
包括：文件元数据提取、LLM 生成解析代码、代码执行与自动修复。
"""

import os
import sys
import json
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, PROJECT_ROOT)

from app.services.interpreter.metadata import (
    FileMetadata,
    FileMetadataExtractor,
    LLMMetadataParser,
    get_metadata,
)
from app.services.interpreter.code_executor import (
    CodeExecutor,
    ExecutionResult,
    execute_code,
)


# 测试数据目录
TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), "results")


def test_file_metadata_extraction():
    """测试文件元数据提取（完整流程，包含 LLM 解析）。"""
    print("\n" + "=" * 60)
    print("测试 1: 文件元数据提取")
    print("=" * 60)
    
    # 测试 CSV 文件
    csv_file = os.path.join(TEST_DATA_DIR, "drug_trial_results.csv")
    if os.path.exists(csv_file):
        metadata = get_metadata(csv_file)
        print(f"\n文件: {metadata.filename}")
        print(f"  扩展名: {metadata.file_extension}")
        print(f"  大小: {metadata.file_size_bytes} bytes")
        print(f"  MIME: {metadata.mime_type}")
        print(f"  是否二进制: {metadata.is_binary}")
        print(f"  编码: {metadata.encoding}")
        print(f"  预览行数: {metadata.preview_lines}")
        print(f"  预览内容前 200 字符:\n{metadata.raw_preview[:200] if metadata.raw_preview else 'N/A'}...")
        
        assert metadata.file_extension == ".csv"
        assert not metadata.is_binary
        assert metadata.encoding is not None
        print(f"LLM Parsed Content: {metadata.parsed_content}")
        print("\n✅ CSV 文件元数据提取成功")
    else:
        print(f"⚠️ 测试文件不存在: {csv_file}")
    
    # 测试 NPY 文件
    npy_files = [f for f in os.listdir(os.path.join(TEST_DATA_DIR, "results")) 
                 if f.endswith('.npy')]
    if npy_files:
        npy_file = os.path.join(TEST_DATA_DIR, "results", npy_files[0])
        metadata = get_metadata(npy_file)
        print(f"\n文件: {metadata.filename}")
        print(f"  扩展名: {metadata.file_extension}")
        print(f"  大小: {metadata.file_size_bytes} bytes")
        print(f"  是否二进制: {metadata.is_binary}")
        print(f"  预览字节数: {metadata.preview_bytes}")
        
        assert metadata.file_extension == ".npy"
        assert metadata.is_binary
        print("\n✅ NPY 文件元数据提取成功")


def test_extract_code_from_markdown():
    """测试从 Markdown 提取代码。"""
    print("\n" + "=" * 60)
    print("测试 2: 从 Markdown 提取代码")
    print("=" * 60)
    
    # 正常的 markdown 代码块
    markdown_text = '''这是一些说明文字。

```python
import pandas as pd

def parse_file(file_path: str) -> dict:
    df = pd.read_csv(file_path)
    return {"rows": len(df), "columns": len(df.columns)}
```

以上是解析代码。
'''
    
    code, success = CodeExecutor.extract_code_from_markdown(markdown_text)
    print(f"提取成功: {success}")
    print(f"提取的代码:\n{code}")
    
    assert success
    assert "def parse_file" in code
    assert "import pandas" in code
    print("\n✅ Markdown 代码提取成功")
    
    # 没有代码块标记的文本
    raw_code = '''import pandas as pd

def parse_file(file_path: str) -> dict:
    df = pd.read_csv(file_path)
    return {"rows": len(df)}
'''
    
    code, success = CodeExecutor.extract_code_from_markdown(raw_code)
    print(f"\n无标记文本提取成功: {success}")
    assert not success  # 没有 ``` 标记，应该返回 False
    print("✅ 无标记文本正确处理")


def test_code_execution():
    """测试代码执行。"""
    print("\n" + "=" * 60)
    print("测试 3: 代码执行")
    print("=" * 60)
    
    csv_file = os.path.join(TEST_DATA_DIR, "drug_trial_results.csv")
    if not os.path.exists(csv_file):
        print(f"⚠️ 测试文件不存在: {csv_file}")
        return
    
    # 正确的代码
    correct_code = '''
import pandas as pd

def parse_file(file_path: str) -> dict:
    df = pd.read_csv(file_path)
    return {
        "total_rows": len(df),
        "total_columns": len(df.columns),
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()}
    }
'''
    
    result = CodeExecutor.execute_with_file(correct_code, csv_file)
    print(f"执行成功: {result.success}")
    if result.success:
        print(f"结果: {json.dumps(result.result, indent=2, ensure_ascii=False)}")
    else:
        print(f"错误: {result.error_message}")
    
    assert result.success
    assert "total_rows" in result.result
    print("\n✅ 正确代码执行成功")
    
    # 错误的代码
    error_code = '''
import pandas as pd

def parse_file(file_path: str) -> dict:
    df = pd.read_csv(file_path)
    return df.nonexistent_method()  # 这个方法不存在
'''
    
    result = CodeExecutor.execute_with_file(error_code, csv_file)
    print(f"\n错误代码执行成功: {result.success}")
    print(f"错误类型: {result.error_type}")
    print(f"错误信息: {result.error_message}")
    
    assert not result.success
    assert result.error_type is not None
    print("\n✅ 错误代码正确捕获异常")


def test_llm_metadata_parser():
    """测试 LLM 元数据解析器完整流程。"""
    print("\n" + "=" * 60)
    print("测试 4: LLM 元数据解析器完整流程")
    print("=" * 60)
    
    csv_file = os.path.join(TEST_DATA_DIR, "drug_trial_results.csv")
    if not os.path.exists(csv_file):
        print(f"⚠️ 测试文件不存在: {csv_file}")
        return
    
    try:
        parser = LLMMetadataParser()
        
        # 测试 prompt 构建
        metadata = get_metadata(csv_file)
        prompt = parser.build_prompt(metadata)
        print(f"构建的 Prompt 长度: {len(prompt)} 字符")
        print(f"Prompt 预览:\n{prompt[:500]}...")
        
        # 测试完整解析流程
        print("\n正在调用 LLM 解析文件...")
        result = parser.parse(csv_file, max_attempts=3)
        
        print(f"\n解析完成!")
        print(f"文件名: {result.filename}")
        print(f"parsed_content: {json.dumps(result.parsed_content, indent=2, ensure_ascii=False, default=str)}")
        
        if result.parsed_content and "error" not in result.parsed_content:
            print("\n✅ LLM 解析成功")
        else:
            print("\n⚠️ LLM 解析失败或返回错误")
            
    except ImportError as e:
        print(f"\n⚠️ LLM 客户端导入失败: {e}")
        print("跳过 LLM 相关测试")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


def test_parse_npy_file():
    """测试解析 NPY 文件。"""
    print("\n" + "=" * 60)
    print("测试 5: 解析 NPY 二进制文件")
    print("=" * 60)
    
    results_dir = os.path.join(TEST_DATA_DIR, "results")
    npy_files = [f for f in os.listdir(results_dir) if f.endswith('.npy')]
    
    if not npy_files:
        print("⚠️ 没有找到 NPY 测试文件")
        return
    
    npy_file = os.path.join(results_dir, npy_files[0])
    print(f"测试文件: {npy_files[0]}")
    
    try:
        parser = LLMMetadataParser()
        
        print("\n正在调用 LLM 解析 NPY 文件...")
        result = parser.parse(npy_file, max_attempts=3)
        
        print(f"\n解析完成!")
        print(f"文件名: {result.filename}")
        print(f"是否二进制: {result.is_binary}")
        print(f"parsed_content: {json.dumps(result.parsed_content, indent=2, ensure_ascii=False, default=str)}")
        
        if result.parsed_content and "error" not in result.parsed_content:
            print("\n✅ NPY 文件解析成功")
        else:
            print("\n⚠️ NPY 文件解析失败或返回错误")
            
    except ImportError as e:
        print(f"\n⚠️ LLM 客户端导入失败: {e}")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


def test_parse_json_file():
    """测试解析 JSON 文件。"""
    print("\n" + "=" * 60)
    print("测试 6: 解析 JSON 文件")
    print("=" * 60)
    
    results_dir = os.path.join(TEST_DATA_DIR, "results")
    json_files = [f for f in os.listdir(results_dir) if f.endswith('.json')]
    
    if not json_files:
        print("⚠️ 没有找到 JSON 测试文件")
        return
    
    json_file = os.path.join(results_dir, json_files[0])
    print(f"测试文件: {json_files[0]}")
    
    try:
        parser = LLMMetadataParser()
        
        print("\n正在调用 LLM 解析 JSON 文件...")
        result = parser.parse(json_file, max_attempts=3)
        
        print(f"\n解析完成!")
        print(f"文件名: {result.filename}")
        print(f"编码: {result.encoding}")
        print(f"parsed_content: {json.dumps(result.parsed_content, indent=2, ensure_ascii=False, default=str)}")
        
        if result.parsed_content and "error" not in result.parsed_content:
            print("\n✅ JSON 文件解析成功")
        else:
            print("\n⚠️ JSON 文件解析失败或返回错误")
            
    except ImportError as e:
        print(f"\n⚠️ LLM 客户端导入失败: {e}")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


def test_code_fix_flow():
    """测试代码修复流程。"""
    print("\n" + "=" * 60)
    print("测试 7: 代码修复流程")
    print("=" * 60)
    
    csv_file = os.path.join(TEST_DATA_DIR, "drug_trial_results.csv")
    if not os.path.exists(csv_file):
        print(f"⚠️ 测试文件不存在: {csv_file}")
        return
    
    try:
        from app.llm import LLMClient
        llm_client = LLMClient(provider="qwen")
        
        # 故意写一个有错误的代码
        buggy_code = '''
import pandas as pd

def parse_file(file_path: str) -> dict:
    df = pd.read_csv(file_path)
    # 错误：使用了不存在的方法
    result = df.get_info()
    return {"info": result}
'''
        
        print("原始错误代码:")
        print(buggy_code)
        
        # 创建修复函数
        fix_func = CodeExecutor.create_fix_code_func(llm_client)
        
        # 使用 execute_with_retry 测试修复流程
        print("\n正在执行代码（带自动修复）...")
        result = CodeExecutor.execute_with_retry(
            code=buggy_code,
            file_path=csv_file,
            fix_code_func=fix_func,
            max_attempts=3,
        )
        
        print(f"\n最终执行成功: {result.success}")
        if result.success:
            print(f"结果: {json.dumps(result.result, indent=2, ensure_ascii=False, default=str)}")
            print("\n✅ 代码修复流程成功")
        else:
            print(f"错误: {result.error_message}")
            print("\n⚠️ 代码修复后仍然失败")
            
    except ImportError as e:
        print(f"\n⚠️ LLM 客户端导入失败: {e}")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


def run_all_tests():
    """运行所有测试。"""
    print("\n" + "#" * 60)
    print("# Metadata 模块全流程测试")
    print("#" * 60)
    
    # 基础测试（不需要 LLM）
    test_file_metadata_extraction()
    test_extract_code_from_markdown()
    test_code_execution()
    
    # LLM 相关测试
    print("\n" + "#" * 60)
    print("# 以下测试需要 LLM 连接")
    print("#" * 60)
    
    test_llm_metadata_parser()
    test_parse_npy_file()
    test_parse_json_file()
    test_code_fix_flow()
    
    print("\n" + "#" * 60)
    print("# 测试完成")
    print("#" * 60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="测试 metadata 模块")
    parser.add_argument("--test", type=str, help="指定测试 (basic, llm, fix, all)", default="all")
    args = parser.parse_args()
    
    if args.test == "basic":
        test_file_metadata_extraction()
        test_extract_code_from_markdown()
        test_code_execution()
    elif args.test == "llm":
        test_llm_metadata_parser()
        test_parse_npy_file()
        test_parse_json_file()
    elif args.test == "fix":
        test_code_fix_flow()
    else:
        run_all_tests()
