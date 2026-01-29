"""
Task merge similarity prompts.
"""

MERGE_SIMILARITY_SYSTEM = """You are a task merge assistant. Your job is to determine whether two tasks are similar enough to merge.

Return only JSON with this schema:
{
  "decision": "merge" or "keep",
  "reason": "short explanation"
}
"""

MERGE_SIMILARITY_USER = """You will be given two tasks. Decide whether they are semantically similar enough to merge.

Task A:
{task_a}

Task B:
{task_b}
"""

BATCH_SIMILARITY_SYSTEM = """You are a task merge assistant. You will be given multiple tasks and need to group similar tasks.
Return only JSON.
"""

BATCH_SIMILARITY_USER = """Below are multiple tasks. Group tasks that are similar enough to merge.
Return JSON with groups as lists of task IDs.

{nodes_text}
"""
