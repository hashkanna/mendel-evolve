"""Trusted evaluator for the toy problem: n integers in 0..100, score = their mean."""


def instance_key(instance: dict) -> str:
    return f"n{instance['n']}"


def evaluate(instance: dict, solution) -> dict:
    n = instance.get("n") if isinstance(instance, dict) else None
    if not isinstance(solution, list) or len(solution) != n:
        return {"valid": False, "score": 0.0, "detail": {"reason": f"expected a list of {n} integers"}}
    for v in solution:
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 100:
            return {"valid": False, "score": 0.0, "detail": {"reason": f"entry {v!r} is not an integer in 0..100"}}
    total = sum(solution)
    return {"valid": True, "score": total / n, "detail": {"sum": total}}
