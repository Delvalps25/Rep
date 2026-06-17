# Essence — Autonomous Intelligence Nexus

Modularized implementation of the Essence architecture.

## Structure
- `essence/core/`: Runtime and Infrastructure.
- `essence/swarm/`: Orchestration and Specialist Agents.
- `essence/memory/`: 6-tier Memory Substrate.
- `essence/analytics/`: Analytical Core (PRISM).
- `essence/safety/`: Safety and Governance.
- `essence/intent/`: Intent and NLU.
- `essence/ui/`: FastAPI Server and Web UI.
- `essence/cli.py`: CLI Entry Point.

## How to Run

### 1. Installation
```bash
pip install pydantic fastapi uvicorn httpx
```

### 2. CLI Usage
```bash
python3 -m essence.cli probe
```

### 3. Server Usage
```bash
uvicorn essence.ui.fastapi_app:app --host 0.0.0.0 --port 7860
```

### 4. Running Tests
```bash
pytest tests/
```
