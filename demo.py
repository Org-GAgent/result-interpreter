"""
Demo: CCSN
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

from app.run_app import run_app, AppConfig


if __name__ == "__main__":
    cfg=AppConfig(
        plan_title="Gene Expression Data Analysis",
        data_dir="data",
        output_dir="test_output/CCSN"
    )
    print("=" * 80)
    print("End-to-end demo - LLM task decomposition + execution")
    print("=" * 80)
    print("Flow: decompose tasks -> execute -> generate full report")
    print("=" * 80)
    print()
    output_dir = Path(cfg.output_dir)
    if output_dir.exists():
        import shutil
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    print(f"OK: output directory cleaned: {output_dir}")
    print()
    run_app(cfg)
    print()
    print("=" * 80)
    print("End-to-end demo finished")
    print("=" * 80)
