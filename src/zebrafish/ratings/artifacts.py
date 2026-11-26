"""Locate released model artifacts without depending on research directories."""
from pathlib import Path
from zebrafish.paths import resource


def models_root(research_context: Path | None = None) -> Path:
    # Preserve custom contexts used by diagnostic tools and isolated tests.
    if research_context is not None and research_context.resolve() != resource("rating_research"):
        return research_context / "models"
    return resource("rating_models")
