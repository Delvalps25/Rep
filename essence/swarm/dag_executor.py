from __future__ import annotations
import threading
import asyncio
import dataclasses as _dc
from typing import Any, Callable, List as list
from essence.core.events import log
from essence.swarm.workflow_engine import WorkflowStep, WorkflowState, StepStatus

@_dc.dataclass
class DAGStep:
    step: WorkflowStep
    depends_on: list[int] = _dc.field(default_factory=list)

    @property
    def step_id(self) -> int:
        return self.step.step_id

class DAGWorkflowExecutor:
    def __init__(self, engine: Any, max_workers: int = 4) -> None:
        self._engine      = engine
        self._max_workers = max_workers

    @staticmethod
    def _build_dag(dag_steps: list[DAGStep]) -> dict[int, list[int]]:
        id_set   = {ds.step_id for ds in dag_steps}
        children: dict[int, list[int]] = {ds.step_id: [] for ds in dag_steps}
        for ds in dag_steps:
            for dep in ds.depends_on:
                if dep not in id_set:
                    raise ValueError(f"Step {ds.step_id} depends_on unknown step {dep}")
                children[dep].append(ds.step_id)
        return children

    @staticmethod
    def _topo_sort(dag_steps: list[DAGStep]) -> list[int]:
        in_degree: dict[int, int] = {ds.step_id: len(ds.depends_on) for ds in dag_steps}
        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        order: list[int] = []
        children: dict[int, list[int]] = {ds.step_id: [] for ds in dag_steps}
        for ds in dag_steps:
            for dep in ds.depends_on:
                if dep in children:
                    children[dep].append(ds.step_id)
        while queue:
            node = queue.pop(0)
            order.append(node)
            for child in children.get(node, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)
        if len(order) != len(dag_steps):
            raise ValueError("Cycle detected in workflow DAG — cannot execute")
        return order

    def run(self, state: WorkflowState,
            executor_fn: Callable[[WorkflowStep], str],
            replan_fn: Callable[[str, WorkflowStep], WorkflowStep | None] | None = None,
            ) -> bool:
        import concurrent.futures as _cf
        dag_steps = [
            DAGStep(step=s,
                    depends_on=s.args.pop("depends_on", []) if isinstance(s.args, dict) else [])
            for s in state.steps
        ]
        try:
            self._topo_sort(dag_steps)
        except ValueError as _e:
            log.error("dag_cycle_error", extra={"error": str(_e)})
            return False

        completed:  set[int] = set()
        failed:     set[int] = set()
        lock = threading.Lock()
        all_ok = True

        with _cf.ThreadPoolExecutor(max_workers=self._max_workers,
                                     thread_name_prefix="uais-dag") as pool:
            futures: dict[_cf.Future, int] = {}
            def _submit_ready() -> None:
                for ds in dag_steps:
                    sid = ds.step_id
                    if sid in completed or sid in failed: continue
                    if any(f_sid == sid for f_sid in futures.values()): continue
                    if all(dep in completed for dep in ds.depends_on):
                        fut = pool.submit(
                            self._engine.execute_step,
                            state, ds.step, executor_fn, replan_fn)
                        futures[fut] = sid
            _submit_ready()
            while futures:
                done, _ = _cf.wait(list(futures), return_when=_cf.FIRST_COMPLETED)
                for fut in done:
                    sid    = futures.pop(fut)
                    status = fut.result()
                    with lock:
                        if status == StepStatus.SUCCESS:
                            completed.add(sid)
                        else:
                            failed.add(sid)
                            all_ok = False
                            for other_ds in dag_steps:
                                if sid in other_ds.depends_on:
                                    other_ds.step.status = StepStatus.SKIPPED
                                    failed.add(other_ds.step_id)
                _submit_ready()
        return all_ok

    async def arun(self, state: WorkflowState,
                  executor_fn: Callable[[WorkflowStep], Any],
                  replan_fn: Callable[[str, WorkflowStep], Any] | None = None,
                  ) -> bool:
        dag_steps = [
            DAGStep(step=s,
                    depends_on=s.args.pop("depends_on", []) if isinstance(s.args, dict) else [])
            for s in state.steps
        ]
        try:
            self._topo_sort(dag_steps)
        except ValueError as _e:
            log.error("dag_cycle_error", extra={"error": str(_e)})
            return False

        completed: set[int] = set()
        failed:    set[int] = set()
        inflight:  dict[int, asyncio.Task] = {}
        all_ok = True

        while len(completed) + len(failed) < len(dag_steps):
            for ds in dag_steps:
                sid = ds.step_id
                if sid in completed or sid in failed or sid in inflight:
                    continue
                if all(dep in completed for dep in ds.depends_on):
                    task = asyncio.create_task(
                        self._engine.aexecute_step(state, ds.step, executor_fn, replan_fn))
                    inflight[sid] = task
            if not inflight:
                if len(completed) + len(failed) < len(dag_steps):
                     log.error("dag_deadlock", extra={"completed": list(completed), "failed": list(failed)})
                     return False
                break
            done, _ = await asyncio.wait(list(inflight.values()), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                sid = next(s for s, t in inflight.items() if t == task)
                inflight.pop(sid)
                try:
                    status = await task
                    if status == StepStatus.SUCCESS:
                        completed.add(sid)
                    else:
                        failed.add(sid)
                        all_ok = False
                        for other_ds in dag_steps:
                            if sid in other_ds.depends_on:
                                other_ds.step.status = StepStatus.SKIPPED
                                failed.add(other_ds.step_id)
                except Exception as _e:
                    log.error("dag_step_exception", extra={"sid": sid, "error": str(_e)})
                    failed.add(sid)
                    all_ok = False
        return all_ok
