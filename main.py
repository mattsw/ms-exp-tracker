import json
import signal
import sys

from overlay import DraggableOverlay
from region_selector import CONFIG_PATH, RegionSelector
from tracker import ExpTracker


def get_region(force_reselect: bool = False) -> dict[str, int]:
    if not force_reselect and CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
        if "exp_region" in data:
            return data["exp_region"]
    return RegionSelector().run()


def launch() -> None:
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    force_reselect = False
    while True:
        region = get_region(force_reselect=force_reselect)
        if not region:
            raise SystemExit("No EXP capture region configured.")

        tracker = ExpTracker(region)
        overlay = DraggableOverlay(tracker)
        force_reselect = overlay.run()
        if not force_reselect:
            break


if __name__ == "__main__":
    launch()