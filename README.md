# result-interpretation-graph

Core pipeline for plan decomposition, execution, visualization, and report generation.

## Quick start

```bash
python demo.py
```

## Configuration

Edit `.env` for local development. `app/run_app.py` loads it automatically.

Key settings:
- `LLM_PROVIDER` and provider-specific keys (e.g., `QWEN_API_KEY`)
- Output directory and data directory are set in `AppConfig` inside `app/run_app.py`


## Entry points

- `demo.py`: minimal entrypoint
- `app/run_app.py`: core pipeline logic
