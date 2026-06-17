# UAIS Modularized Repository

This repository is a modularized version of the UAIS monolith.

## Structure
- `uais_core/`: Core infrastructure, hardware probing, and configuration.
- `uais_agents/`: Orchestration, swarm logic, safety, and runtime.
- `uais_memory/`: Three-layer memory substrate.
- `uais_ml/`: Analytics, PRISM, and ML training tools.
- `uais_server/`: FastAPI application and Web UI.
- `uais_channels/`: Messaging platform adapters.
- `uais_cli/`: Command-line interface.

## How to Run

### 1. Installation
Install the required base dependencies:
```bash
pip install pydantic fastapi uvicorn httpx
```

### 2. CLI Usage
Run the CLI to probe your system or check health:
```bash
python3 -m uais_cli.main probe
python3 -m uais_cli.main doctor
```

### 3. Server Usage
Start the FastAPI server:
```bash
uvicorn uais_server.app:app --host 0.0.0.0 --port 7860
```

### 4. Running Tests
Run unit tests via pytest:
```bash
pytest tests/
```

### 5. Syntax Verification
To verify all modules are syntactically valid:
```bash
find . -name "*.py" -not -path "./uais.py" -exec python3 -m py_compile {} +
```
