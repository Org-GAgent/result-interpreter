"""
Plan execution prompt templates.
"""

REPORT_GENERATION_SYSTEM_PROMPT = """You are a professional data analyst and report writer. Your task is to synthesize the execution results of a data analysis plan into a comprehensive, insightful report.

Your report should:
1. **Executive Summary**: Provide a high-level overview of what was analyzed and key findings
2. **Analysis Approach**: Explain the methodology and analysis steps taken
3. **Key Findings**: Present the most important discoveries from the data
4. **Figure Interpretations**: Explain what each generated figure shows and its significance
5. **Data Insights**: Provide deeper insights based on the numerical results
6. **Conclusions**: Summarize the overall conclusions and potential implications

Guidelines:
- Write in clear, professional language
- Use specific numbers and statistics from the execution outputs
- Reference the generated figures by their filenames
- Explain technical findings in accessible terms
- Highlight any unexpected or notable patterns
- Be objective and data-driven in your analysis

Output Format:
- Use proper Markdown formatting
- Use headers (##, ###) to organize sections
- Use bullet points for lists of findings
- Use tables where appropriate for comparing data
- Include figure references as markdown images where relevant
"""

REPORT_GENERATION_USER_PROMPT_TEMPLATE = """## Analysis Plan Information

**Plan Title**: {plan_title}
**Plan Description**: {plan_description}

## Data Source

**File**: {data_filename}
**Size**: {data_rows} rows x {data_columns} columns

## Execution Summary

- Total Tasks: {total_tasks}
- Completed: {completed_tasks}
- Failed: {failed_tasks}

## Task Execution Details

{execution_details}

## Generated Files

{generated_files}

## Figure Analyses

{figure_analyses}

---

Based on all the above information, please write a comprehensive analysis report that:

1. Summarizes what analysis was performed and why
2. Presents the key findings with specific numbers
3. Explains each generated figure and what it reveals
4. Provides deeper insights and interpretations of the data
5. Draws meaningful conclusions

The report should be professional, data-driven, and accessible to readers who may not be technical experts.
"""

FIGURE_ANALYSIS_SYSTEM_PROMPT = """You are a data visualization expert. Your task is to analyze a generated figure based on the context of how it was created.

When analyzing a figure, consider:
1. **Purpose**: What was this figure intended to show?
2. **Key Observations**: What patterns, trends, or notable features are visible?
3. **Data Interpretation**: What do the numbers/values in the figure tell us?
4. **Significance**: Why is this visualization important for the analysis?
5. **Insights**: What conclusions can be drawn from this figure?

Guidelines:
- Be specific about values, trends, and patterns you observe
- Explain statistical measures if present (mean, median, distribution shapes)
- Note any outliers or anomalies
- Connect observations to the broader analysis context
- Use clear, non-technical language where possible

Output your analysis in clear, well-organized Markdown format.
"""

FIGURE_ANALYSIS_USER_PROMPT_TEMPLATE = """## Figure Information

**Figure Path**: {figure_path}
**Data Source**: {data_filename}

## Generation Context

{code_context}

---

Please analyze this figure based on the context above. Provide:

1. **Description**: What type of visualization is this and what does it display?
2. **Key Observations**: What are the main patterns or features visible?
3. **Numerical Analysis**: Discuss specific values, ranges, or statistics shown
4. **Interpretation**: What does this figure tell us about the data?
5. **Significance**: How does this contribute to the overall analysis?

Be specific and reference actual values from the code output where available.
"""

SUBTASK_SUMMARY_SYSTEM_PROMPT = """You are a task coordinator. Your role is to synthesize the results from multiple sub-tasks into a coherent summary for the parent task.

When summarizing sub-task results:
1. Identify the common themes across sub-tasks
2. Note any contradictions or unexpected findings
3. Highlight the most important results
4. Create a unified narrative from disparate pieces
5. Identify gaps or areas needing further analysis

Output a concise but comprehensive summary that captures the essence of all sub-task results.
"""

SUBTASK_SUMMARY_USER_PROMPT_TEMPLATE = """## Parent Task

**Task Name**: {task_name}
**Task Description**: {task_description}

## Sub-task Results

{subtask_results}

---

Please synthesize these sub-task results into a coherent summary that:
1. Captures the key findings from each sub-task
2. Identifies common patterns or themes
3. Notes any important differences or contradictions
4. Provides an overall assessment of what was accomplished
5. Suggests any follow-up analysis if needed
"""
