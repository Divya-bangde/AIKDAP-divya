"""AI agent orchestration layer.

Packages under `app.agents` contain orchestration logic only: graph
topology, node behaviour, and the strategy abstractions that future
sprints swap real LLMs and external tools into. They deliberately hold
no persistence, HTTP, or authentication concerns — those belong to the
feature modules under `app.modules` that drive them.

The dependency direction is one-way: `app.modules.research` imports
`app.agents.planner`, never the reverse.
"""
