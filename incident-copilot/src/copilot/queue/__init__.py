"""Job queue adapters. Pick one with `build_queue(settings)`."""

from copilot.queue.factory import build_queue
from copilot.queue.local import LocalQueue
from copilot.queue.sqs import SQSQueue

__all__ = ["LocalQueue", "SQSQueue", "build_queue"]
