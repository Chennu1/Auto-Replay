"""Commenter Memory Agent.

This module defines the memory-facing contract. The current persistence
implementation remains in main.py intentionally so this first refactor does
not alter database behavior or the autonomous worker flow.
"""

def format_commenter_memory(row: dict | None) -> str:
    if not row:
        return "No previous relationship with this commenter."
    facts = row.get("facts") or []
    return (
        f"Returning commenter. Interaction count: {row.get('interaction_count') or 0}. "
        f"Summary: {row.get('summary') or 'No summary yet'}. "
        f"Known facts: {', '.join(str(x) for x in facts[-10:])}. "
        f"Last interaction: {row.get('last_interaction_at') or 'unknown'}."
    )


__all__ = ["format_commenter_memory"]
