"""Task execution foundation module.

A Task is a unit of work inside a Project. Every future AI execution —
Planner, LangGraph, Agents, Memory, Timeline, Reports — attaches to a
Task. This module establishes the Task domain (CRUD, ownership,
soft-delete) only; no execution logic lives here yet.
"""
