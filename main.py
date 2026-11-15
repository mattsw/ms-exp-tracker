import json
import signal
import sys

from overlay import DraggableOverlay
from region_selector import CONFIG_PATH, RegionSelector
from tracker import ExpTracker


def get_regions(force_reselect: bool = False) -> dict[str, dict[str, int]]:
    if not force_reselect and CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
        if "exp_region" in data and "pct_region" in data:
            return data
    return RegionSelector().run()


def launch() -> None:
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    force_reselect = False
    while True:
        regions = get_regions(force_reselect=force_reselect)
        if not regions or "exp_region" not in regions or "pct_region" not in regions:
            raise SystemExit("Both EXP and percentage capture regions must be configured.")

        tracker = ExpTracker(regions["exp_region"], regions["pct_region"])
        overlay = DraggableOverlay(tracker)
        force_reselect = overlay.run()
        if not force_reselect:
            break


if __name__ == "__main__":
    launch()