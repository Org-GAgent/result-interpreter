"""
测试文件路径是否正确传递到 Docker 容器
"""
import os
import sys
import tempfile

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from app.services.interpreter.docker_interpreter import DockerCodeInterpreter


def test_file_path_in_docker():
    """测试在 Docker 中能否正确访问挂载目录的文件"""
    
    # 创建临时目录和测试文件
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建测试数据文件
        test_file = os.path.join(tmpdir, "test_data.csv")
        with open(test_file, "w") as f:
            f.write("name,value\n")
            f.write("Alice,100\n")
            f.write("Bob,200\n")
        
        print(f"临时目录: {tmpdir}")
        print(f"测试文件: {test_file}")
        
        # 创建 DockerCodeInterpreter，挂载临时目录
        interpreter = DockerCodeInterpreter(
            image="python:3.10-slim",
            timeout=30,
            work_dir=tmpdir
        )
        
        # 测试代码：读取文件并打印内容
        code = """
import os
print("工作目录:", os.getcwd())
print("目录内容:", os.listdir('.'))

# 读取 CSV 文件
with open('test_data.csv', 'r') as f:
    content = f.read()
    print("文件内容:")
    print(content)
"""
        
        print("\n执行代码...")
        result = interpreter.run_python_code(code)
        
        print(f"\n状态: {result.status}")
        print(f"输出:\n{result.output}")
        if result.error:
            print(f"错误:\n{result.error}")
        
        assert result.status == "success", f"执行失败: {result.error}"
        assert "test_data.csv" in result.output, "文件未出现在目录列表中"
        assert "Alice" in result.output, "文件内容未正确读取"
        
        print("\n✅ 测试通过！文件路径正确挂载到 Docker 容器")


if __name__ == "__main__":
    test_file_path_in_docker()
