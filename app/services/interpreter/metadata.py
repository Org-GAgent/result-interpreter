import pandas as pd
import numpy as np
import os
from typing import List, Any, Optional
from pydantic import BaseModel
import scipy.io

class ColumnMetadata(BaseModel):
    name: str
    dtype: str
    sample_values: List[Any]
    null_count: int
    unique_count: int

class DatasetMetadata(BaseModel):
    filename: str
    file_format: str
    file_size_bytes: int
    total_rows: int
    total_columns: int
    columns: List[ColumnMetadata]

class DataProcessor:
    @staticmethod
    def _process_mat_file(file_path: str) -> DatasetMetadata:
        mat = scipy.io.loadmat(file_path)

        # Filter internal keys
        data = {k: v for k, v in mat.items() if not k.startswith('__')}
        
        columns_metadata = []
        max_rows = 0
        
        for key, value in data.items():
            sample_vals = []
            null_count = 0
            unique_count = 0
            dtype_str = 'unknown'
            
            if isinstance(value, np.ndarray):
                dtype_str = str(value.dtype)
                # Sample
                flat = value.flatten()
                # Handle non-serializable types for JSON (like numpy scalars)
                sample_vals = [x.item() if isinstance(x, np.generic) else x for x in flat[:5]]
                
                # Rows estimate (using first dimension)
                rows = value.shape[0] if value.ndim > 0 else 0
                max_rows = max(max_rows, rows)
                
                # Unique/Null
                if value.size > 0:
                     if np.issubdtype(value.dtype, np.number):
                         null_count = int(np.isnan(value).sum())
                     # Limit unique count calculation for performance
                     if value.size < 10000:
                        unique_count = len(np.unique(flat))
                     else:
                        unique_count = -1 
            else:
                dtype_str = type(value).__name__
                sample_vals = [str(value)[:50]]
                max_rows = max(max_rows, 1)
                unique_count = 1

            columns_metadata.append(ColumnMetadata(
                name=key,
                dtype=dtype_str,
                sample_values=sample_vals,
                null_count=null_count,
                unique_count=unique_count
            ))

        return DatasetMetadata(
            filename=os.path.basename(file_path),
            file_format='mat',
            file_size_bytes=os.path.getsize(file_path),
            total_rows=max_rows,
            total_columns=len(columns_metadata),
            columns=columns_metadata
        )

    @staticmethod
    def get_metadata(file_path: str) -> DatasetMetadata:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext == '.mat':
            return DataProcessor._process_mat_file(file_path)

        try:
            if file_ext == '.tsv':
                df = pd.read_csv(file_path, sep='\t')
            elif file_ext == '.csv':
                df = pd.read_csv(file_path)
            else:
                raise ValueError(f"Unsupported file format: {file_ext}. Only .csv, .tsv, and .mat are supported.")
        except Exception as e:
            raise ValueError(f"Failed to read file: {e}")

        columns_metadata = []
        for col in df.columns:
            # Get a sample of non-null values
            sample_vals = df[col].dropna().head(5).tolist()
            
            columns_metadata.append(ColumnMetadata(
                name=str(col),
                dtype=str(df[col].dtype),
                sample_values=sample_vals,
                null_count=int(df[col].isnull().sum()),
                unique_count=int(df[col].nunique())
            ))

        return DatasetMetadata(
            filename=os.path.basename(file_path),
            file_format=file_ext.lstrip('.'),
            file_size_bytes=os.path.getsize(file_path),
            total_rows=len(df),
            total_columns=len(df.columns),
            columns=columns_metadata
        )
