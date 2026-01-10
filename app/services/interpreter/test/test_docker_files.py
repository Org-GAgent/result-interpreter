"""
测试 Docker 解释器的文件生成能力

测试目标：
1. 验证 Docker 容器挂载是否生效
2. 验证是否能在容器内生成图表文件并保存到宿主机
"""

import sys
import os
import time

# 添加项目根目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

# 不再切换工作目录，直接在当前目录运行
# os.chdir(project_root)

from app.services.interpreter.docker_interpreter import DockerCodeInterpreter

def main():
    print("=== 测试 Docker 文件生成与持久化 ===")
    
    # 1. 准备环境
    # 使用脚本所在目录下的 results 文件夹
    results_dir = os.path.join(current_dir, "results")
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)
        print(f"创建结果目录: {results_dir}")
    else:
        print(f"结果目录已存在: {results_dir}")
        
    # 清理旧的测试文件
    test_file = os.path.join(results_dir, "test_chart.png")
    if os.path.exists(test_file):
        os.remove(test_file)
        print("清理旧的测试图表文件")

    # 2. 初始化解释器
    # 注意：需要确保 docker image 中有 matplotlib
    # 如果本地没有 agent-plotter，可以使用安装了 matplotlib 的其他镜像
    image_name = "agent-plotter" 
    print(f"初始化 Docker 解释器 (Image: {image_name})...")
    print(f"挂载工作目录: {os.getcwd()}")
    
    interpreter = DockerCodeInterpreter(
        image=image_name,
        timeout=60,
        work_dir=current_dir  # 显式传递脚本所在目录作为工作目录
    )
    
    if not interpreter.client:
        print("Docker client 未就绪")
        return

    # 3. 生成代码
    # 这段代码将在容器内的 /workspace 目录下运行
    # 所以保存到 results/test_chart.png 对应宿主机的 {cwd}/results/test_chart.png
    code = """
import matplotlib.pyplot as plt
import numpy as np
import os

print(f"当前工作目录: {os.getcwd()}")

# 1. 生成数据
x = np.linspace(0, 10, 100)
y = np.sin(x)

# 2. 绘图
plt.figure(figsize=(10, 6))
plt.plot(x, y, label='sin(x)')
plt.title('Docker Plot Test')
plt.xlabel('X')
plt.ylabel('Y')
plt.grid(True)
plt.legend()

# 3. 确保输出目录存在 (在容器内)
if not os.path.exists('results'):
    os.makedirs('results')

# 4. 保存图片
save_path = 'results/test_chart.png'
plt.savefig(save_path)
print(f"图片已保存到: {save_path}")

# 5. 关闭以释放内存
plt.close()
"""

    # 4. 执行代码
    print("\n正在执行绘图代码...")
    result = interpreter.run_python_code(code)
    
    print(f"执行状态: {result.status}")
    print(f"执行输出:\n{result.output}")
    if result.error:
        print(f"执行错误:\n{result.error}")

    # 5. 验证结果
    if result.status == "success":
        if os.path.exists(test_file):
            size = os.path.getsize(test_file)
            print(f"\n✅ 测试通过! 文件已生成: {test_file} (大小: {size} bytes)")
        else:
            print(f"\n❌ 测试失败! 代码执行成功但文件未找到: {test_file}")
    else:
        print("\n❌ 测试失败! 代码执行出错")

if __name__ == "__main__":
    main()
