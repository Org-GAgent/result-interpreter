"""
代码执行器模块。
用于安全执行 LLM 生成的 Python 代码并返回结果。
"""

import sys
import json
import logging
import traceback
from io import StringIO
from typing import Any, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """代码执行结果。"""
    success: bool                           # 是否执行成功
    result: Optional[Any] = None            # 返回值（如果有）
    stdout: str = ""                        # 标准输出
    stderr: str = ""                        # 标准错误
    error_type: Optional[str] = None        # 错误类型
    error_message: Optional[str] = None     # 错误信息
    error_traceback: Optional[str] = None   # 错误堆栈
    
    def to_dict(self) -> dict:
        """转换为字典。"""
        return {
            "success": self.success,
            "result": self.result,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "error_traceback": self.error_traceback,
        }
    
    def to_json(self) -> str:
        """转换为 JSON 字符串。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


class CodeExecutor:
    """
    Python 代码执行器。
    安全地执行 LLM 生成的代码并捕获结果。
    """
    
    # 允许导入的模块白名单
    ALLOWED_MODULES = {
        # 数据处理
        'pandas', 'numpy', 'scipy', 'polars',
        # 文件格式
        'json', 'csv', 'xml', 'yaml', 'toml',
        'h5py', 'netCDF4', 'xarray',
        # 图像
        'PIL', 'pillow', 'imageio',
        # 压缩/归档
        'gzip', 'zipfile', 'tarfile', 'bz2', 'lzma',
        # 标准库
        'os', 'io', 'struct', 'pickle', 're', 'math',
        'collections', 'itertools', 'functools',
        'datetime', 'pathlib',
    }
    
    @classmethod
    def execute(
        cls,
        code: str,
        variables: Optional[dict[str, Any]] = None,
        function_name: Optional[str] = None,
        function_args: Optional[tuple] = None,
        function_kwargs: Optional[dict] = None,
        capture_output: bool = True,
    ) -> ExecutionResult:
        """
        执行 Python 代码。
        
        Args:
            code: 要执行的 Python 代码
            variables: 预设的变量字典，会注入到执行环境中
            function_name: 要调用的函数名（执行代码后调用）
            function_args: 函数位置参数
            function_kwargs: 函数关键字参数
            capture_output: 是否捕获 stdout/stderr
            
        Returns:
            ExecutionResult: 执行结果
        """
        # 准备执行环境
        exec_globals = {
            '__builtins__': __builtins__,
            '__name__': '__main__',
        }
        
        # 注入预设变量
        if variables:
            exec_globals.update(variables)
        
        # 捕获输出
        stdout_capture = StringIO() if capture_output else None
        stderr_capture = StringIO() if capture_output else None
        
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        
        try:
            if capture_output:
                sys.stdout = stdout_capture
                sys.stderr = stderr_capture
            
            # 编译并执行代码
            compiled = compile(code, '<llm_generated>', 'exec')
            exec(compiled, exec_globals)
            
            # 如果指定了函数名，调用该函数
            result = None
            if function_name:
                if function_name not in exec_globals:
                    raise NameError(f"函数 '{function_name}' 未在代码中定义")
                
                func = exec_globals[function_name]
                args = function_args or ()
                kwargs = function_kwargs or {}
                result = func(*args, **kwargs)
            
            # 尝试 JSON 序列化结果
            if result is not None:
                try:
                    json.dumps(result, default=str)
                except (TypeError, ValueError):
                    # 如果无法序列化，转为字符串
                    result = str(result)
            
            return ExecutionResult(
                success=True,
                result=result,
                stdout=stdout_capture.getvalue() if capture_output else "",
                stderr=stderr_capture.getvalue() if capture_output else "",
            )
            
        except Exception as e:
            return ExecutionResult(
                success=False,
                result=None,
                stdout=stdout_capture.getvalue() if capture_output else "",
                stderr=stderr_capture.getvalue() if capture_output else "",
                error_type=type(e).__name__,
                error_message=str(e),
                error_traceback=traceback.format_exc(),
            )
            
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
    
    @classmethod
    def execute_with_file(
        cls,
        code: str,
        file_path: str,
        function_name: str = "parse_file",
    ) -> ExecutionResult:
        """
        执行解析文件的代码。
        
        这是一个便捷方法，用于执行 LLM 生成的文件解析代码。
        代码应该定义一个接收文件路径的函数。
        
        Args:
            code: Python 代码（应包含 parse_file 函数）
            file_path: 要解析的文件路径
            function_name: 解析函数名，默认 "parse_file"
            
        Returns:
            ExecutionResult: 执行结果
        """
        return cls.execute(
            code=code,
            variables={"file_path": file_path},
            function_name=function_name,
            function_args=(file_path,),
        )
    
    @classmethod
    def extract_code_from_markdown(cls, text: str) -> tuple[str, bool]:
        """
        从 Markdown 文本中提取 Python 代码块。
        
        Args:
            text: 包含代码块的文本
            
        Returns:
            (code, success): 提取的代码字符串和是否成功
        """
        code = text.strip()
        
        # 处理 ```python 或 ``` 包裹的代码
        if "```" in code:
            lines = code.split("\n")
            in_code_block = False
            code_lines = []
            
            for line in lines:
                if line.strip().startswith("```"):
                    if in_code_block:
                        break  # 代码块结束
                    else:
                        in_code_block = True
                        continue
                if in_code_block:
                    code_lines.append(line)
            
            if code_lines:
                return "\n".join(code_lines), True
        
        # 没有代码块标记，返回原文并标记为未成功提取
        return code, False
    
    @classmethod
    def extract_code_with_fix(
        cls,
        text: str,
        llm_client,
        max_fix_attempts: int = 2,
    ) -> str:
        """
        从 Markdown 文本中提取代码，如果格式不正确则调用 LLM 修复。
        
        Args:
            text: LLM 返回的原始文本
            llm_client: LLM 客户端实例
            max_fix_attempts: 最大修复尝试次数
            
        Returns:
            提取的代码字符串
        """
        from .prompts.metadata_parser_prompt import build_code_format_fix_prompt
        
        current_text = text
        
        for attempt in range(max_fix_attempts + 1):
            code, success = cls.extract_code_from_markdown(current_text)
            
            if success:
                # 验证代码语法
                is_valid, error = cls.validate_code(code)
                if is_valid:
                    return code
                else:
                    logger.warning(f"代码语法验证失败: {error}")
            
            # 如果还有修复机会，调用 LLM 修复格式
            if attempt < max_fix_attempts:
                logger.info(f"尝试修复代码格式 (尝试 {attempt + 1}/{max_fix_attempts})...")
                fix_prompt = build_code_format_fix_prompt(current_text)
                try:
                    current_text = llm_client.chat(fix_prompt)
                except Exception as e:
                    logger.error(f"调用 LLM 修复格式失败: {e}")
                    break
        
        # 所有尝试都失败，返回原始提取结果
        logger.warning("代码格式修复失败，使用原始提取结果")
        return code
    
    @classmethod
    def validate_code(cls, code: str) -> tuple[bool, Optional[str]]:
        """
        验证代码语法是否正确。
        
        Args:
            code: Python 代码
            
        Returns:
            (is_valid, error_message): 是否有效，错误信息
        """
        try:
            compile(code, '<validation>', 'exec')
            return True, None
        except SyntaxError as e:
            return False, f"语法错误 (行 {e.lineno}): {e.msg}"
        except Exception as e:
            return False, str(e)
    
    @classmethod
    def execute_with_retry(
        cls,
        code: str,
        file_path: str,
        fix_code_func: Callable[[str, str], Optional[str]],
        function_name: str = "parse_file",
        max_attempts: int = 5,
    ) -> ExecutionResult:
        """
        执行代码，失败时自动调用修复函数重试。
        
        Args:
            code: 初始 Python 代码
            file_path: 要处理的文件路径
            fix_code_func: 代码修复函数，签名为 (code, error) -> fixed_code
                          - code: 当前失败的代码
                          - error: 错误信息
                          - 返回修复后的代码，返回 None 表示无法修复
            function_name: 要调用的函数名，默认 "parse_file"
            max_attempts: 最大尝试次数，默认 5
            
        Returns:
            ExecutionResult: 最终执行结果
        """
        current_code = code
        last_result = None
        
        for attempt in range(1, max_attempts + 1):
            logger.info(f"执行代码 (尝试 {attempt}/{max_attempts})...")
            
            result = cls.execute_with_file(
                code=current_code,
                file_path=file_path,
                function_name=function_name,
            )
            
            if result.success:
                logger.info(f"代码执行成功 (第 {attempt} 次尝试)")
                return result
            
            last_result = result
            logger.warning(f"代码执行失败 (尝试 {attempt}): {result.error_message}")
            
            # 如果还有重试机会，调用修复函数
            if attempt < max_attempts:
                error_info = cls._format_error_info(result)
                logger.info("调用修复函数修复代码...")
                
                try:
                    fixed_code = fix_code_func(current_code, error_info)
                    if fixed_code and fixed_code.strip():
                        current_code = fixed_code
                        logger.info("代码已修复，准备重试")
                    else:
                        logger.warning("修复函数未返回有效代码，停止重试")
                        break
                except Exception as e:
                    logger.error(f"修复函数调用失败: {e}")
                    break
        
        # 所有尝试都失败
        logger.error(f"代码执行失败，已尝试 {max_attempts} 次")
        return last_result
    
    @classmethod
    def _format_error_info(cls, result: ExecutionResult) -> str:
        """格式化错误信息，用于传递给修复函数。"""
        parts = []
        if result.error_type:
            parts.append(f"Error Type: {result.error_type}")
        if result.error_message:
            parts.append(f"Error Message: {result.error_message}")
        if result.stderr:
            parts.append(f"Stderr: {result.stderr}")
        if result.stdout:
            parts.append(f"Stdout: {result.stdout}")
        if result.error_traceback:
            parts.append(f"Traceback:\n{result.error_traceback}")
        return "\n".join(parts)
    
    @classmethod
    def fix_code_with_llm(
        cls,
        code: str,
        error: str,
        llm_client,
    ) -> str:
        """
        使用 LLM 修复出错的代码。
        
        Args:
            code: 原代码
            error: 错误信息
            llm_client: LLM 客户端实例（需要有 chat 方法）
            
        Returns:
            修复后的代码
        """
        from .prompts.metadata_parser_prompt import build_code_fix_prompt
        
        fix_prompt = build_code_fix_prompt(code, error)
        fixed_response = llm_client.chat(fix_prompt)
        
        # 从 markdown 提取代码（带自动修复）
        return cls.extract_code_with_fix(fixed_response, llm_client)
    
    @classmethod
    def create_fix_code_func(cls, llm_client) -> Callable[[str, str], str]:
        """
        创建一个绑定了 LLM 客户端的代码修复函数。
        
        Args:
            llm_client: LLM 客户端实例
            
        Returns:
            代码修复函数，签名为 (code, error) -> fixed_code
        """
        def fix_code(code: str, error: str) -> str:
            return cls.fix_code_with_llm(code, error, llm_client)
        return fix_code


def execute_code(
    code: str,
    file_path: Optional[str] = None,
    function_name: Optional[str] = None,
) -> ExecutionResult:
    """
    便捷函数：执行代码。
    
    Args:
        code: Python 代码
        file_path: 如果提供，会作为参数传给指定函数
        function_name: 要调用的函数名
        
    Returns:
        ExecutionResult: 执行结果
    """
    if file_path and function_name:
        return CodeExecutor.execute_with_file(code, file_path, function_name)
    elif function_name:
        return CodeExecutor.execute(code, function_name=function_name)
    else:
        return CodeExecutor.execute(code)


def execute_code_with_retry(
    code: str,
    file_path: str,
    fix_code_func: Callable[[str, str], Optional[str]],
    function_name: str = "parse_file",
    max_attempts: int = 5,
) -> ExecutionResult:
    """
    便捷函数：执行代码，失败时自动修复重试。
    
    Args:
        code: 初始 Python 代码
        file_path: 要处理的文件路径
        fix_code_func: 代码修复函数，签名为 (code, error) -> fixed_code
        function_name: 要调用的函数名，默认 "parse_file"
        max_attempts: 最大尝试次数，默认 5
        
    Returns:
        ExecutionResult: 最终执行结果
    """
    return CodeExecutor.execute_with_retry(
        code=code,
        file_path=file_path,
        fix_code_func=fix_code_func,
        function_name=function_name,
        max_attempts=max_attempts,
    )
