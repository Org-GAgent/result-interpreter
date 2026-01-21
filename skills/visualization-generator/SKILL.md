---
name: visualization-generator
description: "Data visualization skill using matplotlib/seaborn. Covers distribution, comparison, relationship, time series, and advanced charts (Chord, Sankey, Radar, Network, etc.). Enforces English-only text, saves to results/, no plt.show()."
---

# Visualization Generator Skill

## Supported Chart Types

| Category | Charts |
|----------|--------|
| Distribution | Histogram, KDE, Box, Violin, ECDF |
| Comparison | Bar, Grouped Bar, Stacked Bar |
| Relationship | Scatter, Heatmap, Pair Plot, Regression |
| Time Series | Line, Area, Multi-line, Decomposition |
| Statistical | Error Bars, QQ Plot, Residual Plot |
| Advanced | Chord/Circos, Sankey, Network, Radar, Dendrogram, Waterfall, Treemap |
| Circular | Circos, Arc Diagram, Chord Matrix, Polar Heatmap, Circular Barplot |

## CRITICAL Rules (MANDATORY)

```python
import os
import matplotlib.pyplot as plt

# 1. ALWAYS save to results/
os.makedirs('results', exist_ok=True)
plt.savefig('results/plot.png', dpi=300, bbox_inches='tight')
plt.close()  # ALWAYS close after save

# 2. NEVER use plt.show()

# 3. ALL text must be English
plt.title('Revenue by Category')  # ✅
# plt.title('收入分类')  # ❌ NEVER

# 4. Translate non-English data before plotting
df['category_en'] = df['category'].map({'电子': 'Electronics', '服装': 'Clothing'})
```

## Code Templates

### Basic Charts

```python
import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

os.makedirs('results', exist_ok=True)
df = pd.read_csv('data.csv')
sns.set_style("whitegrid")

# Bar Chart
plt.figure(figsize=(10, 6))
sns.barplot(data=df, x='category', y='value', palette='viridis')
plt.title('Value by Category', fontsize=14, fontweight='bold')
plt.xticks(rotation=45, ha='right')
plt.tight_layout()
plt.savefig('results/bar.png', dpi=300, bbox_inches='tight')
plt.close()

# Distribution (4-panel)
fig, axes = plt.subplots(2, 2, figsize=(12, 10))
axes[0,0].hist(df['value'], bins=30, edgecolor='black', alpha=0.7)
sns.kdeplot(data=df, x='value', ax=axes[0,1], fill=True)
sns.boxplot(data=df, y='value', ax=axes[1,0])
sns.violinplot(data=df, y='value', ax=axes[1,1])
plt.tight_layout()
plt.savefig('results/distribution.png', dpi=300)
plt.close()

# Correlation Heatmap
import numpy as np
corr = df.select_dtypes(include=[np.number]).corr()
plt.figure(figsize=(10, 8))
sns.heatmap(corr, annot=True, fmt='.2f', cmap='RdBu_r', center=0)
plt.title('Correlation Matrix')
plt.tight_layout()
plt.savefig('results/heatmap.png', dpi=300)
plt.close()

# Time Series
df['date'] = pd.to_datetime(df['date'])
plt.figure(figsize=(12, 6))
plt.plot(df['date'], df['value'], marker='o', markersize=3)
plt.title('Time Series')
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig('results/timeseries.png', dpi=300)
plt.close()
```

### Advanced Charts (matplotlib)

```python
import numpy as np
import matplotlib.pyplot as plt
from scipy.cluster.hierarchy import dendrogram, linkage
from scipy.spatial.distance import pdist

os.makedirs('results', exist_ok=True)

# Radar/Spider Chart
categories = ['A', 'B', 'C', 'D', 'E']
values = [85, 90, 70, 80, 75]
angles = np.linspace(0, 2*np.pi, len(categories), endpoint=False).tolist()
values_loop = values + values[:1]
angles += angles[:1]
fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
ax.plot(angles, values_loop, 'o-', linewidth=2)
ax.fill(angles, values_loop, alpha=0.25)
ax.set_xticks(angles[:-1])
ax.set_xticklabels(categories)
plt.title('Radar Chart')
plt.savefig('results/radar.png', dpi=300)
plt.close()

# Dendrogram
data = np.random.randn(10, 5)
Z = linkage(pdist(data), method='ward')
plt.figure(figsize=(10, 6))
dendrogram(Z, labels=[f'S{i}' for i in range(10)])
plt.title('Dendrogram')
plt.savefig('results/dendrogram.png', dpi=300)
plt.close()
```

### Complex Charts (plotly) - Sankey, Sunburst, Treemap, Chord

```python
import os
import plotly.graph_objects as go
import plotly.express as px

os.makedirs('results', exist_ok=True)

# Sankey Diagram (Flow/Conversion)
fig = go.Figure(go.Sankey(
    node=dict(
        pad=15, thickness=20,
        label=['Source A', 'Source B', 'Target X', 'Target Y', 'Target Z'],
        color=['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
    ),
    link=dict(
        source=[0, 0, 1, 1, 1],  # indices of source nodes
        target=[2, 3, 2, 3, 4],  # indices of target nodes
        value=[30, 20, 40, 25, 15]  # flow values
    )
))
fig.update_layout(title='Sankey Diagram', font_size=12)
fig.write_image('results/sankey.png', scale=2)

# Sunburst (Hierarchical)
data = dict(
    names=['Total', 'A', 'B', 'C', 'A1', 'A2', 'B1', 'B2', 'C1'],
    parents=['', 'Total', 'Total', 'Total', 'A', 'A', 'B', 'B', 'C'],
    values=[100, 40, 35, 25, 25, 15, 20, 15, 25]
)
fig = px.sunburst(data, names='names', parents='parents', values='values',
                  title='Sunburst Chart')
fig.write_image('results/sunburst.png', scale=2)

# Treemap
fig = px.treemap(data, names='names', parents='parents', values='values',
                 title='Treemap')
fig.write_image('results/treemap.png', scale=2)

# Parallel Coordinates (High-dimensional)
import pandas as pd
df = pd.DataFrame({
    'A': [1, 2, 3, 4, 5],
    'B': [5, 4, 3, 2, 1],
    'C': [2, 3, 4, 5, 6],
    'Group': ['X', 'X', 'Y', 'Y', 'Y']
})
fig = px.parallel_coordinates(df, dimensions=['A', 'B', 'C'],
                               color=df['Group'].map({'X': 0, 'Y': 1}),
                               title='Parallel Coordinates')
fig.write_image('results/parallel.png', scale=2)

# Chord/Circos-like (using plotly circular layout)
import numpy as np
# For true Circos, use: pip install pyCircos or mpl_chord_diagram
# Plotly approximation with circular scatter + lines
labels = ['A', 'B', 'C', 'D']
matrix = [[0, 10, 5, 3], [10, 0, 8, 2], [5, 8, 0, 6], [3, 2, 6, 0]]
n = len(labels)
theta = np.linspace(0, 2*np.pi, n, endpoint=False)
x, y = np.cos(theta), np.sin(theta)
fig = go.Figure()
# Add nodes
fig.add_trace(go.Scatter(x=x, y=y, mode='markers+text', text=labels,
                         textposition='top center', marker=dict(size=30)))
# Add edges (chords)
for i in range(n):
    for j in range(i+1, n):
        if matrix[i][j] > 0:
            fig.add_trace(go.Scatter(x=[x[i], x[j]], y=[y[i], y[j]],
                         mode='lines', line=dict(width=matrix[i][j]/2),
                         opacity=0.5, showlegend=False))
fig.update_layout(title='Chord Diagram', showlegend=False,
                  xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor='x'))
fig.write_image('results/chord.png', scale=2)

print("All complex charts saved to results/")
```

### Circos/Chord Diagram (matplotlib)

```python
import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.path import Path
import matplotlib.patches as patches

os.makedirs('results', exist_ok=True)

# Data: connection matrix and labels
labels = ['Gene A', 'Gene B', 'Gene C', 'Gene D', 'Gene E']
matrix = np.array([
    [0, 15, 8, 3, 12],
    [15, 0, 10, 5, 2],
    [8, 10, 0, 20, 6],
    [3, 5, 20, 0, 9],
    [12, 2, 6, 9, 0]
])

n = len(labels)
colors = plt.cm.Set2(np.linspace(0, 1, n))

fig, ax = plt.subplots(figsize=(10, 10))
ax.set_aspect('equal')
ax.set_xlim(-1.5, 1.5)
ax.set_ylim(-1.5, 1.5)
ax.axis('off')

# Calculate segment angles
totals = matrix.sum(axis=1) + matrix.sum(axis=0)
gap = 0.03
total_arc = 2 * np.pi - n * gap
angles = totals / totals.sum() * total_arc

# Draw outer arcs and labels
start_angles = []
current = 0
for i in range(n):
    start_angles.append(current)
    theta1, theta2 = np.degrees(current), np.degrees(current + angles[i])
    wedge = mpatches.Wedge((0, 0), 1.0, theta1, theta2, width=0.12,
                           facecolor=colors[i], edgecolor='white', linewidth=2)
    ax.add_patch(wedge)
    # Label
    mid = current + angles[i] / 2
    ax.text(1.15 * np.cos(mid), 1.15 * np.sin(mid), labels[i],
            ha='center', va='center', fontsize=11, fontweight='bold')
    current += angles[i] + gap

# Draw chords (bezier curves)
for i in range(n):
    for j in range(i + 1, n):
        if matrix[i, j] > 0:
            a1 = start_angles[i] + angles[i] / 2
            a2 = start_angles[j] + angles[j] / 2
            r = 0.88
            x1, y1 = r * np.cos(a1), r * np.sin(a1)
            x2, y2 = r * np.cos(a2), r * np.sin(a2)
            verts = [(x1, y1), (0, 0), (x2, y2)]
            codes = [Path.MOVETO, Path.CURVE3, Path.CURVE3]
            path = Path(verts, codes)
            lw = 1 + matrix[i, j] / matrix.max() * 5
            patch = patches.PathPatch(path, facecolor='none',
                                      edgecolor=colors[i], alpha=0.6, linewidth=lw)
            ax.add_patch(patch)

ax.set_title('Circos Chord Diagram', fontsize=14, fontweight='bold', pad=20)
plt.savefig('results/circos.png', dpi=300, bbox_inches='tight')
plt.close()
print("Circos diagram saved to results/circos.png")
```

## Style Reference

```python
# Palettes
'Set2', 'viridis', 'RdBu_r', 'colorblind'

# Figure Sizes
(10, 6)   # Single plot
(12, 10)  # 2x2 subplots
(14, 6)   # Wide/timeline
(8, 8)    # Square/radar

# Standard Settings
sns.set_style("whitegrid")
plt.rcParams.update({'savefig.dpi': 300, 'font.size': 10})
```

## JSON Output Format

```json
{
  "code": "import os\nimport pandas as pd\n...",
  "description": "Brief description of visualization",
  "has_visualization": true,
  "visualization_purpose": "WHY: Goal, question answered, chart type rationale",
  "visualization_analysis": "WHAT: Chart type, patterns, key values, insights"
}
```

## Checklist

- [x] `os.makedirs('results', exist_ok=True)`
- [x] Save to `results/xxx.png`
- [x] `plt.close()` after save
- [x] NO `plt.show()`
- [x] ALL text in English
- [x] Proper labels and title
- [x] Print statistics to stdout
