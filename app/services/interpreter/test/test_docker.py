import sys
import os

# 尝试将项目根目录添加到 path，以便可以从任何地方运行脚本
# 假设脚本位于 app/services/interpreter/test/
current_dir = os.path.dirname(os.path.abspath(__file__))
# 回溯到项目根目录: test -> interpreter -> services -> app -> root
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

# 同时也尝试添加当前工作目录（如果在根目录运行）
if os.getcwd() not in sys.path:
    sys.path.append(os.getcwd())

from app.services.interpreter.docker_interpreter import DockerCodeInterpreter

def main():
    print("=== 开始测试 DockerCodeInterpreter ===")
    
    # 1. 初始化
    print("正在初始化解释器...")
    interpreter = DockerCodeInterpreter(timeout=10)
    
    if not interpreter.client:
        print("错误: 无法连接到 Docker。请确保已安装 'docker' 库且 Docker Desktop 正在运行。")
        print("运行: pip install docker")
        return

    # 2. 准备测试代码
    test_code = """
import sys
import platform

print("Hello from Docker Container!")
print(f"Python Version: {platform.python_version()}")
print(f"Platform: {platform.platform()}")
"""
    
    # 3. 运行代码
    print("\n正在运行 Python 代码...")
    print("-" * 40)
    print(test_code.strip())
    print("-" * 40)
    
    start_time = time.time()
    result = interpreter.run_python_code(test_code)
    duration = time.time() - start_time
    
    # 4. 输出结果
    print(f"\n执行完成 (耗时 {duration:.2f}s):")
    print(f"状态: {result.status}")
    print(f"退出码: {result.exit_code}")
    
    if result.output:
        print("\n[标准输出 STDOUT]:")
        print(result.output)
    
    if result.error:
        print("\n[标准错误 STDERR]:")
        print(result.error)

    if result.status == "success":
        print("\n✅ 测试通过！")
    else:
        print("\n❌ 测试失败！")

import time

if __name__ == "__main__":
    main()
