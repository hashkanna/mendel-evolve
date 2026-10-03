"""MendelEvolve dashboard: a single-page view of a run's state.json.

    python -m mendel.dashboard.server [--mock]                      the live dashboard
    python -m mendel.dashboard.snapshot --run ID --out FILE.html    one read-only HTML file

In code: `from mendel.dashboard import serve` and
`from mendel.dashboard.snapshot import snapshot`.
"""


def serve(runs_dir: str = "runs", port: int = 8765, **kwargs) -> None:
    """Serve the dashboard. See :func:`mendel.dashboard.server.serve`."""
    from .server import serve as _serve

    _serve(runs_dir, port, **kwargs)


__all__ = ["serve"]
