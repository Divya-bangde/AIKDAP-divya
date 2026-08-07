"""Research Workspace: run the LangGraph orchestration and record its trace.

Owns the run lifecycle (`research_runs`), the per-node execution record
(`research_steps`), and the agent transcript (`agent_messages`). The
orchestration itself lives in `app.agents.planner`; this module decides
*when* it runs, *for whom*, and what is persisted.
"""
