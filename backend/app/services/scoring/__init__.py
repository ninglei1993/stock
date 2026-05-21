from app.services.scoring.base import ScoreDimensionDef, ScoringEngine

__all__ = [
    "ScoringEngine",
    "ScoreDimensionDef",
    "get_scoring_engine",
]


def __getattr__(name: str):
    if name in {
        "get_scoring_engine",
    }:
        from app.services.scoring import factory as factory_mod

        return getattr(factory_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
