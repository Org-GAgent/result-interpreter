"""
Image analysis via Qwen-VL (OpenAI-compatible API).
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Optional

from openai import OpenAI


class ImageAnalyzer:
    def __init__(
        self,
        api_key: Optional[str],
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        if not api_key:
            raise ValueError("VISION_KEY is required for image analysis")
        if not base_url:
            base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        if not model:
            model = "qwen-vl-plus"
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def analyze(self, image_path: Path, prompt: str = "Describe this image.") -> str:
        mime, _ = mimetypes.guess_type(str(image_path))
        if not mime:
            mime = "image/png"
        data = image_path.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"

        completion = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        return completion.choices[0].message.content or ""
