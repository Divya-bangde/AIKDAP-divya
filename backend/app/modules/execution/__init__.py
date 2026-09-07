"""Execution job persistence module.

`ExecutionJob` is the durable state a future execution-launcher Celery
task will re-fetch by `job_id` (Phase 7B.7 design, Part 4/6/11) rather
than trusting a value carried on the Celery message itself. This module
establishes only that durable record -- no launcher, no Celery task, no
Docker access lives here.
"""
