"""
App entrypoint.
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

from app.run_app import run_app, AppConfig


if __name__ == "__main__":
    # config = AppConfig(
    #     plan_title="New Project Title",
    #     data_dir="new_data_dir",
    #     output_dir="new_output_dir"
    # )
    run_app(AppConfig())
