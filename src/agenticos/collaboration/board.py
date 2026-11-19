"""In-memory collaboration task board with dependency-aware transitions."""

from agenticos.collaboration.models import CollaborationTask, TaskStatus


class TaskBoard:
    def __init__(self) -> None:
        self._tasks: dict[str, CollaborationTask] = {}

    def add(self, task: CollaborationTask) -> None:
        if task.task_id in self._tasks:
            raise ValueError(f"Task already exists: {task.task_id}")
        self._tasks[task.task_id] = task

    def get(self, task_id: str) -> CollaborationTask:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise KeyError(f"Unknown task: {task_id}") from exc

    def list_tasks(self) -> tuple[CollaborationTask, ...]:
        return tuple(self._tasks[key] for key in sorted(self._tasks))

    def dependencies_complete(self, task_id: str) -> bool:
        task = self.get(task_id)
        return all(
            dependency in self._tasks
            and self._tasks[dependency].status is TaskStatus.COMPLETED
            for dependency in task.dependencies
        )

    def mark_ready(self, task_id: str) -> None:
        task = self.get(task_id)
        if task.status is not TaskStatus.BACKLOG:
            raise ValueError("Only backlog tasks can become ready")
        if not self.dependencies_complete(task_id):
            raise ValueError("Task dependencies are not all completed")
        task.status = TaskStatus.READY

    def start(self, task_id: str, agent_id: str) -> None:
        task = self.get(task_id)
        if task.status is not TaskStatus.READY:
            raise ValueError("Only ready tasks can start")
        if task.assigned_agent != agent_id:
            raise PermissionError("Task is not assigned to this agent")
        task.status = TaskStatus.IN_PROGRESS

    def complete(self, task_id: str, agent_id: str, result: str) -> None:
        task = self.get(task_id)
        if task.status is not TaskStatus.IN_PROGRESS:
            raise ValueError("Only in-progress tasks can be completed")
        if task.assigned_agent != agent_id:
            raise PermissionError("Task is not assigned to this agent")
        if not result.strip():
            raise ValueError("Task result cannot be empty")
        task.result = result
        task.status = TaskStatus.COMPLETED

    def fail(self, task_id: str, agent_id: str) -> None:
        task = self.get(task_id)
        if task.status is not TaskStatus.IN_PROGRESS:
            raise ValueError("Only in-progress tasks can fail")
        if task.assigned_agent != agent_id:
            raise PermissionError("Task is not assigned to this agent")
        task.status = TaskStatus.FAILED
