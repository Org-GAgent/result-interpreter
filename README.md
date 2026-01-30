# Result Interpretation

Core pipeline for plan decomposition, execution, visualization, and report generation.

## Quick start

### Set up environment

```bash
pip install -r requirements.txt
mv .env.example .env
```

Add your LLM API key into `.env` file.

Also, if you want to let the pipeline use image understanding, you need to add an **additional** Vision API key into `.env` file.

### Set up data directory

Add your data into one folder. The data directory should contain the following file:

- `README.md`: a markdown file that describes 


### Then use it

```python
from app.run_app import run_app, AppConfig

cfg=AppConfig(
    plan_title="your_title",
    data_dir="your_data_directory",
    output_dir="your_output_directory"
)
run_app(cfg)
```

## Test Demo

```bash
python demo.py
```
