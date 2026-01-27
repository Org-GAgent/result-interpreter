import os
import mimetypes
import chardet
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel


class FileMetadata(BaseModel):
    """
    通用文件元数据结构。
    - 通用信息：直接提取（文件名、大小、类型等）
    - 内容信息：由 LLM 生成代码分析后填充到 parsed_content
    """
    # ===== 通用信息（直接提取）=====
    filename: str                           # 文件名（不含路径）
    file_path: str                          # 完整文件路径
    file_extension: str                     # 文件扩展名（如 .csv, .mat, .npy）
    file_size_bytes: int                    # 文件大小（字节）
    mime_type: Optional[str] = None         # MIME 类型
    is_binary: bool = False                 # 是否为二进制文件
    encoding: Optional[str] = None          # 文件编码（文本文件）
    created_time: Optional[str] = None      # 创建时间（ISO 格式）
    modified_time: Optional[str] = None     # 修改时间（ISO 格式）
    
    # ===== 预览信息（用于传递给 LLM）=====
    raw_preview: Optional[str] = None       # 文件头部预览
    preview_lines: int = 0                  # 预览行数（文本文件）
    preview_bytes: int = 0                  # 预览字节数
    
    # ===== LLM 分析结果（由 LLM 生成代码解析后填充）=====
    parsed_content: Optional[dict[str, Any]] = None
    # 示例结构（根据文件类型不同而不同）：
    # CSV/表格数据:
    # {
    #     "total_rows": 1000,
    #     "total_columns": 5,
    #     "columns": [
    #         {"name": "id", "dtype": "int64", "sample_values": [1,2,3], "null_count": 0},
    #         {"name": "name", "dtype": "object", "sample_values": ["a","b"], "null_count": 2}
    #     ]
    # }
    # 
    # NumPy 数组:
    # {
    #     "shape": [100, 50],
    #     "dtype": "float64",
    #     "sample_values": [1.0, 2.0, 3.0]
    # }
    #
    # 图像文件:
    # {
    #     "width": 1920,
    #     "height": 1080,
    #     "channels": 3,
    #     "format": "PNG"
    # }


class FileMetadataExtractor:
    """
    通用文件元数据提取器。
    只提取通用文件特征信息，不解析具体内容。
    具体内容解析由 LLM 生成代码完成。
    """
    
    TEXT_PREVIEW_LINES = 20
    BINARY_PREVIEW_BYTES = 512
    ENCODING_DETECT_BYTES = 8192
    
    @classmethod
    def extract(cls, file_path: str) -> FileMetadata:
        """
        提取文件的通用元数据。
        
        Args:
            file_path: 文件的完整路径
            
        Returns:
            FileMetadata: 文件元数据（parsed_content 为空，需后续由 LLM 填充）
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        filename = os.path.basename(file_path)
        file_extension = os.path.splitext(file_path)[1].lower()
        file_size = os.path.getsize(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)
        
        stat_info = os.stat(file_path)
        created_time = datetime.fromtimestamp(stat_info.st_ctime).isoformat()
        modified_time = datetime.fromtimestamp(stat_info.st_mtime).isoformat()
        
        is_binary, encoding = cls._detect_file_type(file_path)
        
        if is_binary:
            raw_preview, preview_bytes = cls._get_binary_preview(file_path)
            preview_lines = 0
        else:
            raw_preview, preview_lines, preview_bytes = cls._get_text_preview(
                file_path, encoding
            )
        
        return FileMetadata(
            filename=filename,
            file_path=file_path,
            file_extension=file_extension,
            file_size_bytes=file_size,
            mime_type=mime_type,
            is_binary=is_binary,
            encoding=encoding,
            created_time=created_time,
            modified_time=modified_time,
            raw_preview=raw_preview,
            preview_lines=preview_lines,
            preview_bytes=preview_bytes,
            parsed_content=None,
        )
    
    @classmethod
    def _detect_file_type(cls, file_path: str) -> tuple[bool, Optional[str]]:
        """检测文件是否为二进制及编码。"""
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read(cls.ENCODING_DETECT_BYTES)
            
            if not raw_data:
                return False, 'utf-8'
            
            if b'\x00' in raw_data:
                return True, None
            
            result = chardet.detect(raw_data)
            encoding = result.get('encoding')
            confidence = result.get('confidence', 0)
            
            if encoding is None or confidence < 0.5:
                return True, None
            
            return False, encoding
            
        except Exception:
            return True, None
    
    @classmethod
    def _get_text_preview(
        cls, file_path: str, encoding: Optional[str]
    ) -> tuple[str, int, int]:
        """获取文本文件预览。"""
        try:
            encoding = encoding or 'utf-8'
            lines = []
            byte_count = 0
            
            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                for i, line in enumerate(f):
                    if i >= cls.TEXT_PREVIEW_LINES:
                        break
                    lines.append(line)
                    byte_count += len(line.encode(encoding, errors='replace'))
            
            return ''.join(lines), len(lines), byte_count
            
        except Exception as e:
            return f"[Error reading file: {e}]", 0, 0
    
    @classmethod
    def _get_binary_preview(cls, file_path: str) -> tuple[str, int]:
        """获取二进制文件 hex 预览。"""
        try:
            with open(file_path, 'rb') as f:
                raw_bytes = f.read(cls.BINARY_PREVIEW_BYTES)
            
            hex_lines = []
            for i in range(0, len(raw_bytes), 16):
                chunk = raw_bytes[i:i+16]
                hex_part = ' '.join(f'{b:02x}' for b in chunk)
                ascii_part = ''.join(
                    chr(b) if 32 <= b < 127 else '.' for b in chunk
                )
                hex_lines.append(f"{i:08x}  {hex_part:<48}  |{ascii_part}|")
            
            return '\n'.join(hex_lines), len(raw_bytes)
            
        except Exception as e:
            return f"[Error reading file: {e}]", 0


def get_metadata(file_path: str, max_attempts: int = 3) -> FileMetadata:
    """
    获取文件完整元数据（包含 LLM 解析的 parsed_content）。
    
    Args:
        file_path: 文件路径
        max_attempts: 代码执行失败时的最大重试次数
        
    Returns:
        FileMetadata: 完整的文件元数据（包含 parsed_content）
    """
    return get_metadata_parser().parse(file_path, max_attempts)


class LLMMetadataParser:
    """
    使用 LLM 解析文件元数据。
    整合完整流程：构建提示词 -> 调用 LLM -> 执行代码 -> 返回结果
    """
    
    def __init__(self, llm_client=None):
        """
        初始化解析器。
        
        Args:
            llm_client: LLMClient 实例，默认使用全局客户端
        """
        self._llm_client = llm_client
    
    @property
    def llm_client(self):
        """延迟加载 LLM 客户端，默认使用 qwen。"""
        if self._llm_client is None:
            from ...llm import LLMClient
            self._llm_client = LLMClient(provider="qwen")
        return self._llm_client
    
    def build_prompt(self, metadata: FileMetadata) -> str:
        """
        根据 FileMetadata 构建 LLM 提示词。
        
        Args:
            metadata: 文件元数据
            
        Returns:
            提示词字符串
        """
        from .prompts.metadata_parser_prompt import build_metadata_parser_prompt
        
        return build_metadata_parser_prompt(
            filename=metadata.filename,
            file_extension=metadata.file_extension,
            file_size_bytes=metadata.file_size_bytes,
            mime_type=metadata.mime_type,
            is_binary=metadata.is_binary,
            encoding=metadata.encoding,
            raw_preview=metadata.raw_preview,
            preview_lines=metadata.preview_lines,
            preview_bytes=metadata.preview_bytes,
        )
    
    def _fix_code(self, code: str, error: str) -> str:
        """
        调用 LLM 修复出错的代码。
        
        Args:
            code: 原代码
            error: 错误信息
            
        Returns:
            修复后的代码
        """
        from .code_executor import CodeExecutor
        
        return CodeExecutor.fix_code_with_llm(code, error, self.llm_client)
    
    def _execute_code(
        self, 
        metadata: FileMetadata, 
        code: str,
        max_attempts: int = 3,
    ) -> FileMetadata:
        """
        执行 LLM 生成的代码并更新 metadata（带自动修复重试）。
        
        Args:
            metadata: 文件元数据
            code: LLM 生成的 Python 代码
            max_attempts: 最大尝试次数
            
        Returns:
            更新后的 FileMetadata
        """
        from .code_executor import CodeExecutor
        
        # 从 markdown 提取代码（带格式修复）
        clean_code = CodeExecutor.extract_code_with_fix(code, self.llm_client)
        
        # 执行代码（带自动修复重试）
        result = CodeExecutor.execute_with_retry(
            code=clean_code,
            file_path=metadata.file_path,
            fix_code_func=self._fix_code,
            function_name="parse_file",
            max_attempts=max_attempts,
        )
        
        if result.success and result.result:
            metadata.parsed_content = result.result
        else:
            metadata.parsed_content = {
                "error": result.error_message,
                "error_type": result.error_type,
            }
        
        return metadata
    
    def parse(self, file_path: str, max_attempts: int = 3) -> FileMetadata:
        """
        完整解析流程（同步）：获取元数据 -> 调用 LLM -> 执行代码 -> 返回结果
        
        Args:
            file_path: 文件路径
            max_attempts: 代码执行失败时的最大重试次数
            
        Returns:
            包含 parsed_content 的完整 FileMetadata
        """
        # 1. 获取基础元数据
        metadata = FileMetadataExtractor.extract(file_path)
        
        # 2. 构建提示词
        prompt = self.build_prompt(metadata)
        
        # 3. 调用 LLM 获取解析代码
        code = self.llm_client.chat(prompt)
        
        # 4. 执行代码并更新 metadata（带自动修复重试）
        return self._execute_code(metadata, code, max_attempts)
    
    def parse_metadata(
        self, 
        metadata: FileMetadata, 
        max_attempts: int = 3,
    ) -> FileMetadata:
        """
        对已有的 FileMetadata 进行 LLM 解析（同步）。
        
        Args:
            metadata: 已提取基础信息的文件元数据
            max_attempts: 代码执行失败时的最大重试次数
            
        Returns:
            更新了 parsed_content 的 FileMetadata
        """
        prompt = self.build_prompt(metadata)
        code = self.llm_client.chat(prompt)
        return self._execute_code(metadata, code, max_attempts)


# 全局解析器实例
_metadata_parser: Optional[LLMMetadataParser] = None


def get_metadata_parser(llm_client=None) -> LLMMetadataParser:
    """
    获取全局元数据解析器实例。
    
    Args:
        llm_client: 可选的 LLMClient 实例
        
    Returns:
        LLMMetadataParser 实例
    """
    global _metadata_parser
    if _metadata_parser is None or llm_client is not None:
        _metadata_parser = LLMMetadataParser(llm_client)
    return _metadata_parser
