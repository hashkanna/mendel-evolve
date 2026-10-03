"""Cancel the Modal calls recorded in campaign journals. Usage: python scripts/cancel_calls.py runs/NAME [...]"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import modal


def cancel(call_id: str) -> bool:
    try:
        modal.FunctionCall.from_id(call_id).cancel()
        return True
    except Exception:  # noqa: BLE001 - already finished or already gone is fine
        return False


for run in sys.argv[1:]:
    journal = Path(run) / "modal_calls.json"
    if not journal.exists():
        print(f"{run}: no journal")
        continue
    ids = [c for c in json.loads(journal.read_text()).get("call_ids", []) if c]
    with ThreadPoolExecutor(16) as pool:
        done = sum(pool.map(cancel, ids))
    print(f"{run}: cancel requested for {done} of {len(ids)} calls")
