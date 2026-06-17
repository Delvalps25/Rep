import json
from pathlib import Path
from typing import Any, Dict, Optional, List

_ANALYSIS_TASKS = [
    "eda", "cluster", "classify", "regress", "forecast",
    "anomaly", "ab_test", "sentiment", "risk", "churn",
    "feature_importance", "correlation", "segmentation",
]

def _run_eda(df: Any, target_col: str, cfg: Dict, plots_dir: Path) -> Dict:
    """Automatic EDA: shape, dtypes, missing, distributions, correlations."""
    import pandas as pd
    result: Dict[str, Any] = {
        "rows": len(df), "cols": len(df.columns),
        "columns": list(df.columns),
        "dtypes": df.dtypes.astype(str).to_dict(),
        "missing": df.isnull().sum().to_dict(),
        "describe": json.loads(df.describe(include="all").to_json()),
    }
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        numeric_cols = df.select_dtypes("number").columns
        fig, axes = plt.subplots(1, min(4, len(numeric_cols)), figsize=(14, 4))
        if not hasattr(axes, "__len__"): axes = [axes]
        for ax, col in zip(axes, numeric_cols[:4]):
            df[col].dropna().hist(ax=ax, bins=30, color="#6c8cff", alpha=0.8)
            ax.set_title(col, fontsize=9)
        plt.tight_layout()
        out = plots_dir / "eda_summary.png"
        plt.savefig(out, dpi=100)
        plt.close()
        result["plot"] = str(out)
    except Exception:
        pass
    return result

def _run_cluster(df: Any, target_col: str, cfg: Dict, plots_dir: Path) -> Dict:
    try:
        from sklearn.cluster import KMeans
        X = df.select_dtypes("number").fillna(0)
        n_clusters = cfg.get("n_clusters", 3)
        model = KMeans(n_clusters=n_clusters, random_state=42)
        clusters = model.fit_predict(X)
        result = {"n_clusters": n_clusters, "clusters": clusters.tolist()}
        return result
    except ImportError:
        return {"error": "scikit-learn not installed"}

def _run_regress(df: Any, target_col: str, cfg: Dict, plots_dir: Path) -> Dict:
    # Placeholder for actual regression logic
    return {"status": "regress_not_implemented"}

def _run_classify(df: Any, target_col: str, cfg: Dict, plots_dir: Path) -> Dict:
    # Placeholder for actual classification logic
    return {"status": "classify_not_implemented"}

def _run_forecast(df: Any, target_col: str, cfg: Dict, plots_dir: Path) -> Dict:
    # Placeholder for actual forecasting logic
    return {"status": "forecast_not_implemented"}

def _run_anomaly(df: Any, target_col: str, cfg: Dict, plots_dir: Path) -> Dict:
    # Placeholder for actual anomaly detection logic
    return {"status": "anomaly_not_implemented"}

def _run_ab_test(df: Any, target_col: str, cfg: Dict, plots_dir: Path) -> Dict:
    return {"status": "ab_test_not_implemented"}

def _run_sentiment(df: Any, target_col: str, cfg: Dict, plots_dir: Path) -> Dict:
    return {"status": "sentiment_not_implemented"}

def _run_risk(df: Any, target_col: str, cfg: Dict, plots_dir: Path) -> Dict:
    return {"status": "risk_not_implemented"}

def _run_churn(df: Any, target_col: str, cfg: Dict, plots_dir: Path) -> Dict:
    return {"status": "churn_not_implemented"}

def _run_correlation(df: Any, target_col: str, cfg: Dict, plots_dir: Path) -> Dict:
    # Placeholder for correlation matrix logic
    return {"status": "correlation_not_implemented"}

def _run_feature_importance(df: Any, target_col: str, cfg: Dict, plots_dir: Path) -> Dict:
    if not target_col:
        return {"error": "target_col required"}
    try:
        from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
        from sklearn.preprocessing import LabelEncoder
        y = df[target_col].dropna()
        X = df.drop(columns=[target_col]).select_dtypes("number").loc[y.index].fillna(0)
        if y.dtype == object or y.nunique() < 20:
            le = LabelEncoder()
            y2 = le.fit_transform(y.astype(str))
            clf = RandomForestClassifier(n_estimators=100, random_state=42)
        else:
            y2 = y.values
            clf = RandomForestRegressor(n_estimators=100, random_state=42)
        clf.fit(X, y2)
        fi = sorted(zip(X.columns, clf.feature_importances_), key=lambda x: -x[1])
        result = {"top_features": {k: float(v) for k, v in fi[:20]}}
        return result
    except ImportError:
        return {"error": "scikit-learn not installed"}

def _tool_run_analysis(dataset_path: str, task: str,
                        target_col: str = "",
                        config: Optional[Dict] = None,
                        workspace: Optional[Path] = None) -> str:
    """
    Unified data analysis dispatcher.
    """
    cfg       = config or {}
    ws        = workspace or Path.cwd()
    plots_dir = ws / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    try:
        import pandas as pd
        p = Path(dataset_path).expanduser()
        if not p.exists():
            return json.dumps({"error": f"File not found: {dataset_path}"})
        ext = p.suffix.lower()
        if ext == ".csv": df = pd.read_csv(p)
        elif ext in (".parquet", ".pq"): df = pd.read_parquet(p)
        elif ext == ".json": df = pd.read_json(p)
        else: return json.dumps({"error": f"Unsupported format: {ext}"})
    except ImportError:
        return json.dumps({"error": "pandas not installed"})
    except Exception as e:
        return json.dumps({"error": str(e)})

    dispatch = {
        "eda":                _run_eda,
        "cluster":            _run_cluster,
        "segmentation":       _run_cluster,
        "regress":            _run_regress,
        "classify":           _run_classify,
        "forecast":           _run_forecast,
        "anomaly":            _run_anomaly,
        "ab_test":            _run_ab_test,
        "sentiment":          _run_sentiment,
        "risk":               _run_risk,
        "churn":              _run_churn,
        "correlation":        _run_correlation,
        "feature_importance": _run_feature_importance,
    }

    func = dispatch.get(task)
    if not func:
        return json.dumps({"error": f"Unknown analysis task: {task}"})

    result = func(df, target_col, cfg, plots_dir)
    return json.dumps(result)
