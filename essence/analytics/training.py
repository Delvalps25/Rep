import os
import json
import time
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Union

def _tool_train_model(dataset_path: str, target_col: str,
                       model_type: str = "auto",
                       config: Optional[Dict] = None,
                       workspace: Optional[Path] = None,
                       tracker: Any = None) -> str:
    """
    End-to-end model training tool.
    """
    cfg  = config or {}
    ws   = workspace or Path.cwd()
    models_dir = ws / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"run_{int(time.time())}"
    run_dir = models_dir / run_id
    run_dir.mkdir()

    if tracker:
        tracker.start_run(run_id, tags={"model_type": model_type, "dataset": dataset_path})

    try:
        import pandas as pd
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import LabelEncoder, StandardScaler
        from sklearn.metrics import accuracy_score, f1_score, r2_score

        df  = pd.read_csv(Path(dataset_path).expanduser())
        y   = df[target_col].dropna()
        X   = df.drop(columns=[target_col]).select_dtypes("number").loc[y.index].fillna(0)
        is_clf = y.dtype == object or y.nunique() < 20

        if is_clf:
            le = LabelEncoder()
            y = le.fit_transform(y.astype(str))
        else:
            y = y.values

        sc = StandardScaler()
        Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42)
        Xtr_s = sc.fit_transform(Xtr)
        Xte_s = sc.transform(Xte)

        # PyTorch path
        if model_type == "pytorch_mlp":
            try:
                import torch
                import torch.nn as nn
            except ImportError:
                return json.dumps({"error": "torch not installed"})

            _Xtr_s, _Xte_s, _ytr, _yte = Xtr_s.copy(), Xte_s.copy(), ytr.copy(), yte.copy()
            _run_dir_t, _run_id_t, _is_clf = run_dir, run_id, is_clf

            def _pytorch_train():
                status_file = _run_dir_t / "status.json"
                status_file.write_text(json.dumps({"status": "running", "run_id": _run_id_t}))
                try:
                    import torch.nn as nn
                    class MLP(nn.Module):
                        def __init__(self, in_f: int, out_f: int):
                            super().__init__()
                            h = cfg.get("hidden", 128)
                            self.net = nn.Sequential(
                                nn.Linear(in_f, h), nn.ReLU(), nn.Dropout(0.2),
                                nn.Linear(h, h), nn.ReLU(),
                                nn.Linear(h, out_f))
                        def forward(self, x): return self.net(x)

                    n_out = len(set(_ytr)) if _is_clf else 1
                    model = MLP(_Xtr_s.shape[1], n_out)
                    opt = torch.optim.Adam(model.parameters(), lr=cfg.get("lr", 1e-3))
                    loss_fn = nn.CrossEntropyLoss() if _is_clf else nn.MSELoss()

                    xt = torch.tensor(_Xtr_s, dtype=torch.float32)
                    yt = torch.tensor(_ytr, dtype=torch.long if _is_clf else torch.float32)

                    for ep in range(cfg.get("epochs", 20)):
                        model.train()
                        opt.zero_grad()
                        out = model(xt)
                        loss = loss_fn(out, yt if _is_clf else yt.unsqueeze(1))
                        loss.backward(); opt.step()

                    torch.save(model.state_dict(), str(_run_dir_t / "model.pt"))
                    status_file.write_text(json.dumps({"status": "done", "run_id": _run_id_t}))
                except Exception as e:
                    status_file.write_text(json.dumps({"status": "error", "error": str(e)}))

            threading.Thread(target=_pytorch_train, daemon=True).start()
            return json.dumps({"status": "launched", "run_id": run_id})

        # Sklearn path
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        ModelCls = RandomForestClassifier if is_clf else RandomForestRegressor
        model = ModelCls(n_estimators=100, random_state=42)
        model.fit(Xtr_s, ytr)
        score = model.score(Xte_s, yte)

        result = {"status": "done", "run_id": run_id, "score": score}
        return json.dumps(result)

    except Exception as e:
        return json.dumps({"error": str(e)})
