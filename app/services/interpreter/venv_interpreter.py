import logging
import subprocess
import sys
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class CodeExecutionResult:
    """代码执行结果封装类"""
    status: str  # 'success', 'failed', 'error', 'timeout'
    output: str  # 标准输出 (stdout)
    error: str   # 标准错误 (stderr) 或 系统错误信息
    exit_code: int


class VenvCodeInterpreter:
    """使用Python虚拟环境执行代码的解释器"""

    def __init__(
        self,
        timeout: int = 60,
        work_dir: Optional[str] = None,
        data_dir: Optional[str] = None,
        venv_path: Optional[str] = None
    ):
        """
        初始化虚拟环境代码解释器
        :param timeout: 执行超时时间（秒）
        :param work_dir: 工作目录（用于输出文件）
        :param data_dir: 数据目录（用于读取数据文件）
        :param venv_path: 虚拟环境路径，如果不指定则使用系统Python
        """
        self.timeout = timeout
        self.work_dir = os.path.abspath(work_dir) if work_dir else os.getcwd()
        self.data_dir = os.path.abspath(data_dir) if data_dir else self.work_dir
        self.venv_path = venv_path

        # 确保工作目录存在
        Path(self.work_dir).mkdir(parents=True, exist_ok=True)

        # 确定Python可执行文件路径
        if venv_path:
            if sys.platform == "win32":
                self.python_executable = os.path.join(venv_path, "Scripts", "python.exe")
            else:
                self.python_executable = os.path.join(venv_path, "bin", "python")

            if not os.path.exists(self.python_executable):
                logger.warning(f"Virtual environment Python not found at {self.python_executable}, using system Python")
                self.python_executable = sys.executable
        else:
            self.python_executable = sys.executable

        logger.info(f"VenvCodeInterpreter initialized with Python: {self.python_executable}")
        logger.info(f"Work directory: {self.work_dir}")
        logger.info(f"Data directory: {self.data_dir}")

    def run_python_code(self, code: str) -> CodeExecutionResult:
        """
        在虚拟环境中运行Python代码
        :param code: Python代码字符串
        :return: CodeExecutionResult
        """
        # 创建临时文件保存代码
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.py',
                delete=False,
                encoding='utf-8'
            ) as temp_file:
                temp_file.write(code)
                temp_file_path = temp_file.name

            logger.info(f"Created temporary Python file: {temp_file_path}")

            # 准备环境变量，添加数据目录路径
            env = os.environ.copy()
            env['DATA_DIR'] = self.data_dir
            env['WORK_DIR'] = self.work_dir

            # 执行代码
            try:
                result = subprocess.run(
                    [self.python_executable, temp_file_path],
                    cwd=self.work_dir,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    env=env
                )

                stdout = result.stdout
                stderr = result.stderr
                exit_code = result.returncode

                if exit_code == 0:
                    logger.info(f"Code execution successful")
                    return CodeExecutionResult("success", stdout, stderr, exit_code)
                else:
                    logger.warning(f"Code execution failed with exit code {exit_code}")
                    return CodeExecutionResult("failed", stdout, stderr, exit_code)

            except subprocess.TimeoutExpired:
                logger.error(f"Code execution timeout after {self.timeout} seconds")
                return CodeExecutionResult(
                    status="timeout",
                    output="",
                    error=f"Execution exceeded {self.timeout} seconds limit.",
                    exit_code=-1
                )
            except Exception as e:
                logger.exception("Error during code execution")
                return CodeExecutionResult("error", "", str(e), -1)
            finally:
                # 清理临时文件
                try:
                    os.unlink(temp_file_path)
                    logger.debug(f"Deleted temporary file: {temp_file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete temporary file {temp_file_path}: {e}")

        except Exception as e:
            logger.exception("Error creating temporary file")
            return CodeExecutionResult("error", "", str(e), -1)
