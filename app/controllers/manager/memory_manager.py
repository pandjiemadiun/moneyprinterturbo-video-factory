from queue import Queue
from typing import Dict, Optional

from app.controllers.manager.base_manager import TaskManager


class InMemoryTaskManager(TaskManager):
    def create_queue(self):
        return Queue(maxsize=self.max_queued_tasks)

    def enqueue(self, task: Dict):
        self.queue.put(task)

    def dequeue(self) -> Optional[Dict]:
        """Dequeue next non-cancelled task. Returns None if all remaining are cancelled."""
        while not self.queue.empty():
            task_info = self.queue.get()
            # Check if this task has been cancelled
            kwargs = task_info.get("kwargs", {})
            task_id = kwargs.get("task_id")
            if task_id and task_id in self._cancelled_ids:
                # Skip cancelled task, don't count it
                self._cancelled_ids.discard(task_id)
                self.current_tasks -= 1  # Release the slot
                continue
            return task_info
        return None

    def is_queue_empty(self):
        return self.queue.empty()

    def queue_size(self):
        return self.queue.qsize()
