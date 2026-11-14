import json

from overlay import DraggableOverlay
from region_selector import CONFIG_PATH, RegionSelector
from tracker import ExpTracker


def get_region(force_reselect: bool = False) -> dict[str, int]:
    if not force_reselect and CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
        if "exp_region" in data:
            return data["exp_region"]
    return RegionSelector().run()


def launch(force_reselect: bool = False) -> None:
    region = get_region(force_reselect=force_reselect)
    if not region:
        raise SystemExit("No EXP capture region configured.")
    tracker = ExpTracker(region)
    overlay = DraggableOverlay(tracker, on_reselect=lambda: launch(force_reselect=True))
    overlay.run()


if __name__ == "__main__":
    launch()