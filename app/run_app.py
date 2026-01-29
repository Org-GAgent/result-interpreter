"""
Core pipeline: LLM task decomposition -> analysis -> visualization -> report writing.
"""
from dataclasses import dataclass, field
from pathlib import Path
import sys
import os
from dotenv import load_dotenv

from app.database import init_db
from app.repository.plan_repository import PlanRepository
from app.services.plans.plan_decomposer import PlanDecomposer
from app.services.interpreter.plan_execute import PlanExecutorInterpreter


def _get_task_type(node) -> str:
    if node.context_meta and isinstance(node.context_meta, dict):
        return node.context_meta.get("task_type", "auto")
    return "auto"


def normalize_task_dependencies(repo: PlanRepository, plan_id: int) -> None:
    """Ensure summary/text tasks run after analysis tasks and remove invalid deps."""
    plan = repo.get_plan_tree(plan_id)
    type_map = {nid: _get_task_type(node) for nid, node in plan.nodes.items()}

    code_ids = [nid for nid, t in type_map.items() if t == "code_required"]
    data_summary_ids = [nid for nid, t in type_map.items() if t == "data_summary"]
    text_ids = [nid for nid, t in type_map.items() if t == "text_only"]

    all_ids = list(plan.nodes.keys())

    for node_id, node in plan.nodes.items():
        task_type = type_map.get(node_id, "auto")

        if task_type == "text_only":
            deps = [nid for nid in all_ids if nid != node_id and nid not in text_ids]
        elif task_type == "data_summary":
            deps = [nid for nid in code_ids if nid != node_id]
        elif task_type == "code_required":
            deps = [d for d in (node.dependencies or []) if d not in text_ids]
        else:
            deps = list(node.dependencies or [])

        if deps != list(node.dependencies or []):
            repo.update_task(plan_id, node_id, dependencies=deps)


@dataclass(frozen=True)
class AppConfig:
    plan_title: str = "Result Interpretation"
    data_dir: str = "new_data_dir"
    output_dir: str = "new_output_dir"
    llm_provider: str = "qwen"
    interpreter_type: str = "venv"
    readme_filenames: list[str] = field(
        default_factory=lambda: ["README.md", "README.txt", "README.rst", "README"]
    )
    image_max_count: int = 5


def read_readme(data_dir: Path, readme_filenames=None) -> tuple[str, Path]:
    if readme_filenames is None:
        readme_filenames = ["README.md", "README.txt", "README.rst", "README"]
    for filename in readme_filenames:
        readme_path = data_dir / filename
        if readme_path.exists():
            readme_content = readme_path.read_text(encoding="utf-8")
            print(f"OK: read {readme_path} ({len(readme_content)} chars)")
            # print(f"  First 300 chars: {readme_content[:300]}...")
            print()
            return readme_content, readme_path
    print(f"WARNING: No README found in {data_dir}; falling back to generic strategy")
    print()
    return "(No README found in data directory)", data_dir



def build_plan_description(readme_content: str, readme_path: Path, data_dir: Path) -> str:
    return f"""Generate a publication-ready Experimental Results section (in English) for the dataset in the {data_dir.as_posix()}/ directory.

## README.md Content (if available)

Source: {readme_path.as_posix()}

{readme_content}

---

## Your Task:

1. **Interpret README.md**:
   - If README.md ONLY describes the data (file formats, column meanings, data collection notes, etc.) and does not prescribe experiments, you must design an appropriate analysis plan yourself.
   - If README.md specifies experiments, metrics, or figures, those are **mandatory requirements** and must be completed exactly as specified.

2. **Design and execute the analyses**:
   - If README specifies comparison of representations -> compare all representations.
   - If README lists required figures -> generate those figures.
   - If README is descriptive-only -> propose and execute a reasonable, dataset-appropriate analysis (include visualizations).

3. **Generate appropriate visualizations** to support findings.

4. **Write a comprehensive Experimental Results section** (1000-2000 words) that:
   - Reports all required analyses from README.md (if any).
   - References the generated figures by number.
   - Provides detailed statistical reporting.
   - Stays grounded in actual computed results.

**CRITICAL**:
- README.md is the source of truth for required experiments if it includes them.
- If README.md is descriptive-only, you must design the analysis yourself, but still remain faithful to the dataset context.
"""


def run_app(cfg: AppConfig) -> None:
    load_dotenv()

    # Pass image analysis config via environment variable
    if cfg.image_max_count is not None:
        os.environ["IMAGE_MAX_COUNT"] = str(cfg.image_max_count)

    # Resolve output directory early so it's available for all steps
    output_dir = Path(cfg.output_dir)

    # Initialize database
    print("Initializing database...")
    try:
        init_db()
        print("OK: database initialized\n")
    except Exception as e:
        print(f"WARNING: database init failed: {e}\n")

    # ============================================================
    # Step 1: read README.md and build analysis plan
    # ============================================================
    print("=" * 80)
    print("Step 1: read README.md and build analysis plan")
    print("=" * 80)

    data_dir = Path(cfg.data_dir)
    readme_filenames=cfg.readme_filenames
    readme_content, readme_path = read_readme(data_dir, readme_filenames)   
    plan_description = build_plan_description(readme_content, readme_path, data_dir)

    try:
        repo = PlanRepository()
        plan_tree = repo.create_plan(
            title=cfg.plan_title,
            description=plan_description,
        )
        plan_id = plan_tree.id

        print(f"OK: plan created (Plan ID={plan_id})")
        print(f"  Title: {plan_tree.title}")
        print(f"  Description: {plan_description[:120]}...")
        print()

    except Exception as e:
        print(f"ERROR: failed to create plan: {e}")
        sys.exit(1)

    # ============================================================
    # Step 2: LLM task decomposition
    # ============================================================
    print("=" * 80)
    print("Step 2: LLM task decomposition")
    print("=" * 80)
    print("Please wait while the LLM analyzes and creates sub-tasks...\n")

    try:
        decomposer = PlanDecomposer(repo=repo)
        decomp_result = decomposer.run_plan(
            plan_id=plan_id,
            max_depth=2,
        )

        print("=" * 80)
        print("Task decomposition completed")
        print("=" * 80)
        print(f"OK: tasks created: {len(decomp_result.created_tasks)}")
        print(f"OK: mode: {decomp_result.mode}")
        print()

        # Normalize dependencies so summaries run after analysis tasks
        normalize_task_dependencies(repo, plan_id)

        # Show created tasks
        if decomp_result.created_tasks:
            print("Tasks created by LLM:")
            print("-" * 80)
            for i, task in enumerate(decomp_result.created_tasks, 1):
                task_type = "auto"
                if task.context_meta and isinstance(task.context_meta, dict):
                    task_type = task.context_meta.get("task_type", "auto")

                print(f"\n{i}. [{task.id}] {task.name}")
                print(f"   Instruction: {task.instruction[:100]}...")
                print(f"   Task type: {task_type}")
                print(f"   Dependencies: {task.dependencies if task.dependencies else 'None'}")

        print()

        # Show full outline
        plan_tree = repo.get_plan_tree(plan_id)
        outline = plan_tree.to_outline(max_depth=3)
        print("=" * 80)
        print("Full plan outline")
        print("=" * 80)
        print(outline)
        print()

    except Exception as e:
        print(f"ERROR: task decomposition failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # ============================================================
    # Step 3: execute plan
    # ============================================================
    print("=" * 80)
    print("Step 3: execute analysis plan")
    print("=" * 80)
    print("Starting execution of all tasks...\n")

    try:
        plan_executor = PlanExecutorInterpreter(
            plan_id=plan_id,
            data_dir=cfg.data_dir,
            output_dir=str(output_dir),
            interpreter_type=cfg.interpreter_type,
            llm_provider=cfg.llm_provider,
        )

        print("OK: PlanExecutorInterpreter created")
        print(f"  Plan ID: {plan_id}")
        print(f"  Data directory: {cfg.data_dir} (auto-discovery mode)")
        print(f"  Output directory: {output_dir}")
        print(f"  Interpreter type: {cfg.interpreter_type}")
        print()

        print("Executing tasks...")
        print("-" * 80)

        exec_result = plan_executor.execute()

        print()
        print("=" * 80)
        print("Plan execution completed")
        print("=" * 80)
        print(f"OK: success: {exec_result.success}")
        print(f"  Total nodes: {exec_result.total_nodes}")
        print(f"  Completed nodes: {exec_result.completed_nodes}")
        print(f"  Failed nodes: {exec_result.failed_nodes}")
        print(f"  Skipped nodes: {exec_result.skipped_nodes}")

        # Show per-task status
        if exec_result.node_records:
            print()
            print("Per-task execution status:")
            print("-" * 80)
            for node_id, record in exec_result.node_records.items():
                status_icon = "OK" if record.status.value == "completed" else "FAIL"
                print(f"{status_icon} [{node_id}] {record.node_name}: {record.status.value}")
                if record.task_type:
                    print(f"     Task type: {record.task_type.value}")
                if record.has_visualization:
                    print("     Visualization generated: yes")
                if record.generated_files:
                    print(f"     Generated files: {len(record.generated_files)}")

        # Report path
        if exec_result.report_path:
            print()
            print(f"OK: report generated: {exec_result.report_path}")

        # List generated files
        print()
        print("All generated files:")
        print("-" * 80)

        for f in sorted(output_dir.glob("**/*.md")):
            size = f.stat().st_size / 1024
            rel_path = f.relative_to(output_dir)
            print(f"  OK {rel_path} ({size:.1f} KB)")

        for f in sorted(output_dir.glob("**/*.png")):
            size = f.stat().st_size / 1024
            rel_path = f.relative_to(output_dir)
            print(f"  OK {rel_path} ({size:.1f} KB)")

    except Exception as e:
        print(f"ERROR: plan execution failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    print(f"\nOutput directory: {output_dir}")
