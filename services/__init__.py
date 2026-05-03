"""Service layer — stateless, async, dependency-injected.

Each service owns one concern (db access, logic, alerts, notebook, etc.)
and exposes a thin public API. Cogs orchestrate; services compute.
"""
