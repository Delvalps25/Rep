import threading
import dataclasses as _dc
import enum as _enum
import time
import math
import json
from pathlib import Path
from typing import Any, List, Dict, Optional, Tuple

class CapabilityNodeType(_enum.Enum):
    DOMAIN    = "D"
    CLUSTER   = "C"
    TOOL      = "T"
    SKILL     = "S"
    PARAMETER = "P"
    PHANTOM   = "Φ"

class CapabilityEdgeType(_enum.Enum):
    CONTAINS     = "contains"
    REQUIRES     = "requires"
    COMPOSES     = "composes"
    CONFLICTS    = "conflicts"
    ENHANCES     = "enhances"
    PHANTOM_LINK = "phantom_link"

class ResolutionLevel(_enum.IntEnum):
    L1_SILHOUETTE   = 1
    L2_CONTOUR      = 2
    L3_BLUEPRINT    = 3
    L4_SCHEMATIC    = 4
    L5_EXPERIENTIAL = 5

@_dc.dataclass
class CapabilityNode:
    node_id: str
    node_type: CapabilityNodeType
    metadata: Dict[int, Dict[str, Any]] = _dc.field(default_factory=dict)
    usage_freq: int = 0
    recency: float = 0.0
    success_rate: float = 0.0
    confidence: float = 1.0
    safety_clearance: int = 0

@_dc.dataclass
class CapabilityEdge:
    source_id: str
    target_id: str
    edge_type: CapabilityEdgeType
    weight: float = 1.0

class CapabilityGraph:
    def __init__(self):
        self.nodes: Dict[str, CapabilityNode] = {}
        self.edges: List[CapabilityEdge] = []
        self._lock = threading.RLock()

    def graft(self, node: CapabilityNode):
        with self._lock: self.nodes[node.node_id] = node

    def link(self, source_id: str, target_id: str, edge_type: CapabilityEdgeType, weight: float = 1.0):
        with self._lock: self.edges.append(CapabilityEdge(source_id, target_id, edge_type, weight))

class RelevanceScorer:
    def __init__(self, workspace: Path, graph: CapabilityGraph = None):
        self.workspace = workspace
        self.graph = graph
        self.weights = {
            "semantic": 0.3, "plan": 0.2, "co_occurrence": 0.1,
            "recency": 0.1, "success": 0.1, "dependency": 0.1,
            "novelty": 0.05, "safety": 1.0
        }

    def score(self, node: CapabilityNode, context: Dict) -> float:
        s1 = context.get("semantic_affinity", {}).get(node.node_id, 0.5)
        s2 = 1.0 if node.node_id in context.get("plan_refs", []) else 0.0
        s3 = context.get("co_occurrence", {}).get(node.node_id, 0.0)
        s4 = 1.0 / (1.0 + (time.time() - node.recency) / 3600) if node.recency > 0 else 0.0
        s5 = node.success_rate
        s7 = 1.0 / (1.0 + node.usage_freq)
        s8 = 1.0 if node.safety_clearance >= 0 else 0.0

        raw_score = (self.weights["semantic"] * s1 + self.weights["plan"] * s2 +
                     self.weights["co_occurrence"] * s3 + self.weights["recency"] * s4 +
                     self.weights["success"] * s5 + self.weights["novelty"] * s7)
        return raw_score * s8

class ProjectionFunction:
    def __init__(self, graph: CapabilityGraph, scorer: RelevanceScorer):
        self.graph = graph
        self.scorer = scorer

    def project(self, context: Dict, budget: int) -> Dict[str, ResolutionLevel]:
        scored = []
        for nid, node in self.graph.nodes.items():
            scored.append((nid, self.scorer.score(node, context)))
        scored.sort(key=lambda x: x[1], reverse=True)

        res = {}
        used = 0
        for nid, score in scored:
            if score > 0.8: target_lvl = ResolutionLevel.L4_SCHEMATIC
            elif score > 0.6: target_lvl = ResolutionLevel.L3_BLUEPRINT
            elif score > 0.4: target_lvl = ResolutionLevel.L2_CONTOUR
            else: target_lvl = ResolutionLevel.L1_SILHOUETTE

            cost = {1:10, 2:50, 3:150, 4:500, 5:1000}.get(target_lvl.value, 10)
            if used + cost <= budget:
                res[nid] = target_lvl
                used += cost
            else:
                res[nid] = ResolutionLevel.L1_SILHOUETTE
        return res

class SelfEvolutionLoop:
    def __init__(self, scorer: RelevanceScorer, workspace: Path):
        self.scorer = scorer
        self.workspace = workspace
        self.log_path = workspace / "logs" / "discovery_evolution.jsonl"

    def evolve(self, metrics: Dict):
        hit_rate = metrics.get("hit_rate", 0.0)
        if hit_rate < 0.8: self.scorer.weights["semantic"] *= 1.1
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a") as f:
                f.write(json.dumps({"ts":time.time(), "metrics":metrics, "weights":self.scorer.weights}) + "\n")
        except: pass
