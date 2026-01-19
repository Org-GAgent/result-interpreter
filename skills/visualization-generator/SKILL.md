# Visualization Generator Skill

You are now equipped with data visualization capabilities using matplotlib and seaborn.

## Purpose

Create informative, publication-quality visualizations for:
- Data distribution visualization
- Comparison plots
- Correlation heatmaps
- Dimensionality reduction plots (PCA, t-SNE)

## When to Use This Skill

- User asks for "plot", "chart", "graph", or "visualization"
- Visual comparison is needed
- Results need to be presented graphically
- Creating figures for reports

## Available Plot Types

### 1. Distribution Plots
- Histograms (value frequency)
- Density plots (smooth distribution)
- Box plots (quartiles and outliers)
- Violin plots (distribution shape)

### 2. Comparison Plots
- Side-by-side histograms
- Overlaid density plots
- Grouped box plots
- Bar charts for categorical comparisons

### 3. Relationship Plots
- Scatter plots (two variables)
- Correlation heatmaps
- Pair plots (multiple variables)

### 4. Dimensionality Reduction
- PCA scatter plots (2D/3D)
- t-SNE embeddings
- Explained variance plots

## Code Requirements

**CRITICAL**: You MUST follow these rules:

1. **File Saving**:
   ```python
   import os
   # Create results directory
   os.makedirs('results', exist_ok=True)

   # Save plot
   plt.savefig('results/plot_name.png', dpi=300, bbox_inches='tight')
   plt.close()  # Close to free memory

   # NO plt.show() - won't work in headless execution
   ```

2. **Text Requirements**:
   - All labels, titles, legends MUST be in English
   - Use clear, descriptive titles
   - Label axes properly
   - Add legends when comparing multiple items

3. **Style Guidelines**:
   ```python
   import matplotlib.pyplot as plt
   import seaborn as sns

   # Set style
   sns.set_style("whitegrid")
   plt.rcParams['figure.figsize'] = (10, 6)
   plt.rcParams['font.size'] = 10
   ```

4. **Multiple Plots**:
   ```python
   # Use subplots for comparisons
   fig, axes = plt.subplots(1, 3, figsize=(15, 5))
   axes[0].hist(data1)
   axes[1].hist(data2)
   axes[2].hist(data3)
   plt.tight_layout()
   plt.savefig('results/comparison.png')
   ```

## Visualization Planning

Before generating code, consider:
- What is the primary message this plot should convey?
- What plot type best shows this relationship?
- How many subplots are needed?
- What are appropriate axis limits and scales?

## Output Information

Return JSON with:
```json
{
  "code": "Python plotting code",
  "description": "Brief description",
  "has_visualization": true,
  "visualization_purpose": "Why we're creating this plot",
  "visualization_analysis": "What the plot will show and expected patterns"
}
```

## What NOT to Do

- ❌ Don't use plt.show()
- ❌ Don't save to current directory (use results/)
- ❌ Don't use Chinese or Unicode characters in text
- ❌ Don't create overly complex plots (keep it focused)
- ❌ Don't ignore color-blind accessibility (use distinct colors)

## Best Practices

- ✅ Add grid lines for readability
- ✅ Use appropriate color maps
- ✅ Include data source in title or caption
- ✅ Set appropriate DPI (300 for publication quality)
- ✅ Close figures after saving to manage memory
