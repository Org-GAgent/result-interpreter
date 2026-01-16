"""
运行数据分析脚本

使用 interpreter.run_analysis 处理 data 文件夹下的数据
"""

import sys
import os
import logging

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from app.services.interpreter.interpreter import run_analysis, execute_plan, print_plan_tree
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(current_dir, "..", "data")

DATA_FILES = [
    os.path.join(DATA_DIR, "Gene_expression_table_filtered_normalized.npy"),
    os.path.join(DATA_DIR, "Gene_expression_table_filtered_normalized_ndm.mat"),
    os.path.join(DATA_DIR, "Gene_expression_table_filtered_normalized_cndm.mat"),
    os.path.join(DATA_DIR, "sample_cluster_ref_filtered.npy")
]

DESCRIPTION = """
## 数据说明

这是基因表达数据分析任务，包含以下数据文件：

1. **Gene_expression_table_filtered_normalized.npy**
2. **Gene_expression_table_filtered_normalized_ndm.mat**
3. **Gene_expression_table_filtered_normalized_cndm.mat**
4. **sample_cluster_ref_filtered.npy**

## 文件描述
- Gene_expression_table_filtered_normalized.npy
    Gene Expression Matrix (GEM): The gene expression matrix (GEM) serves as the fundamental input data for all subsequent analyses. It is an n×p matrix, where n denotes the number of single cells and p denotes the number of genes, with each entry representing the normalized expression level of a gene in a given cell. In practice, the GEM is obtained from raw single-cell RNA sequencing count data through a standard preprocessing pipeline, including quality control to remove low-quality cells and genes, normalization to correct for sequencing depth, and optional filtering of genes with low variability. The resulting matrix captures the direct transcriptional profiles of individual cells and reflects gene activity at the expression level. In this study, the GEM is used as a baseline feature representation for clustering, providing a reference point against which network-based representations are compared.

- Gene_expression_table_filtered_normalized_ndm.mat
    Network Degree Matrix (NDM) Derived from CSN: The network degree matrix (NDM) is derived from the cell-specific network (CSN) framework, which constructs an individual gene–gene co-expression network for each single cell. In the CSN method, genes are treated as nodes, and edges are established based on statistically significant co-expression relationships inferred from the local neighborhood of a given cell in the gene expression space. This results in a binary adjacency matrix for each cell, representing the presence or absence of co-expression relationships between gene pairs. To obtain a compact and comparable feature representation across cells, each cell-specific network is summarized by computing the degree of each gene, defined as the number of genes it is connected to in that network. Aggregating these degree vectors across all cells yields the NDM, an n×p matrix in which each entry reflects the network connectivity of a gene within a specific cell. Compared to the original GEM, the NDM encodes higher-order structural information derived from gene–gene interactions rather than raw expression levels.

- Gene_expression_table_filtered_normalized_cndm.mat
    Conditional Network Degree Matrix (CNDM) Derived from CCSN: The conditional network degree matrix (CNDM) extends the CSN framework by incorporating conditional independence testing, as proposed in the conditional cell-specific network (CCSN) method. While CSN captures pairwise gene co-expression, some observed associations may arise indirectly due to the influence of other genes acting as confounding or mediating factors. CCSN addresses this issue by evaluating gene–gene relationships under the condition of one or more selected genes, thereby filtering out indirect dependencies and retaining associations that are more likely to represent direct regulatory relationships. For each cell, a conditional cell-specific network is constructed using these conditional tests, resulting in a refined adjacency matrix. As with CSN, each conditional network is summarized by computing gene degrees, and the resulting degree vectors are assembled into the CNDM, an n×p matrix. The CNDM therefore provides a network-based feature representation that emphasizes direct gene–gene interactions and offers a more causally informative characterization of cellular states.

- sample_cluster_ref_filtered.npy
    Ground-Truth Cell-Type Labels: The ground-truth cell-type labels provide external biological annotations used exclusively for evaluation purposes. These labels assign each cell to a predefined cell type or cluster based on prior biological knowledge, such as marker gene expression patterns, expert curation, or reference annotations provided with the dataset.
"""


def main():
    print("\n" + "="*60)
    print("实验数据分析")
    print("="*60)
    
    print("\n数据文件:")
    for f in DATA_FILES:
        exists = "✓" if os.path.exists(f) else "✗"
        print(f"  {exists} {os.path.basename(f)}")
    
    print("\n分析描述:")
    print(DESCRIPTION[:300] + "...")
    
    confirm = input("\n开始分析? (y/n): ").strip().lower()
    if confirm != 'y':
        print("已取消")
        return
    
    result = run_analysis(
        description=DESCRIPTION,
        data_paths=DATA_FILES,
        title="实验数据分析",
        output_dir=os.path.join(current_dir, "results"),
        max_depth=5,
        node_budget=50,
    )

    # result = execute_plan(
    #     plan_id=27,
    #     data_paths=DATA_FILES,
    #     output_dir=os.path.join(current_dir, "results"),
    #     docker_image="agent-plotter",
    #     docker_timeout=7200,
    # )
    
    print("\n" + "="*60)
    print(f"分析完成! 成功: {result.success}")
    print(f"计划ID: {result.plan_id}")
    print(f"任务: {result.completed_tasks}/{result.total_tasks} 完成")
    
    if result.error:
        print(f"错误: {result.error}")
    
    if result.generated_files:
        print(f"\n生成文件 ({len(result.generated_files)}):")
        for f in result.generated_files:
            print(f"  - {os.path.basename(f)}")
    
    if result.report_path:
        print(f"\n报告: {result.report_path}")


if __name__ == "__main__":
    main()
