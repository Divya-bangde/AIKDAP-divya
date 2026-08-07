"""Enumerations for the tasks module."""

import enum


class TaskType(str, enum.Enum):
    """The category of work a task represents."""

    RESEARCH = "RESEARCH"
    BUSINESS_ANALYSIS = "BUSINESS_ANALYSIS"
    FINANCIAL_ANALYSIS = "FINANCIAL_ANALYSIS"
    DATA_ANALYSIS = "DATA_ANALYSIS"
    REPORT_GENERATION = "REPORT_GENERATION"
    CUSTOM = "CUSTOM"


class TaskStatus(str, enum.Enum):
    """Lifecycle state of a task.

    `ARCHIVED` is the soft-delete state: `DELETE /tasks/{id}` sets a
    task to this status rather than removing its row.
    """

    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ARCHIVED = "ARCHIVED"


class TaskPriority(str, enum.Enum):
    """Execution priority of a task."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
