"""Mendel dashboard: a single-page view of a run's state.json.

Run it with ``python -m mendel.dashboard.server`` (add ``--mock`` for demo data).
"""


def serve(runs_dir: str = "runs", port: int = 8765, **kwargs) -> None:
    """Serve the dashboard. See :func:`mendel.dashboard.server.serve`."""
    from .server import serve as _serve

    _serve(runs_dir, port, **kwargs)


__all__ = ["serve"]
