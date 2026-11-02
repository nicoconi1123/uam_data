"""FIFO travel times obtained by integrating positive, piecewise-constant speed factors."""

from bisect import bisect_right
from dataclasses import dataclass
import json



@dataclass(frozen=True)
class SpeedProfile:
    starts: tuple
    speeds: tuple

    def __post_init__(self):
        if not self.starts or self.starts[0] != 0 or len(self.starts) != len(self.speeds):
            raise ValueError("Speed profiles must start at zero and have matching arrays.")
        if any(b <= a for a, b in zip(self.starts, self.starts[1:])) or min(self.speeds) <= 0:
            raise ValueError("Strictly increasing breakpoints and positive speeds are required.")

    def progress(self, t):
        if t < -1e-7:
            raise ValueError("Time cannot be negative.")
        result = 0.0
        for k, start in enumerate(self.starts):
            end = self.starts[k + 1] if k + 1 < len(self.starts) else max(t, start)
            result += max(0.0, min(t, end) - start) * self.speeds[k]
        return result

    def inverse(self, distance):
        remaining = distance
        for k, start in enumerate(self.starts):
            if k + 1 == len(self.starts):
                return start + remaining / self.speeds[k]
            length = (self.starts[k + 1] - start) * self.speeds[k]
            if remaining <= length:
                return start + remaining / self.speeds[k]
            remaining -= length

    def travel(self, departure, base_time):
        # Independent segment-by-segment integration, also used by validation.
        t, remaining = float(departure), float(base_time)
        while remaining > 1e-10:
            k = max(0, bisect_right(self.starts, t + 1e-10) - 1)
            if k + 1 == len(self.starts):
                t += remaining / self.speeds[k]
                break
            boundary = self.starts[k + 1]
            covered = (boundary - t) * self.speeds[k]
            if remaining <= covered + 1e-10:
                t += remaining / self.speeds[k]
                break
            remaining -= covered
            t = boundary
        return t - departure


class TimeDependentRoadTimes:
    def __init__(self, specification):
        self.spec = specification
        self.profiles = {
            name: SpeedProfile(tuple(v["starts"]), tuple(v["speed_factors"]))
            for name, v in specification["profiles"].items()
        }
        self.zones = specification["node_zones"]

    @classmethod
    def from_file(cls, path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def profile_name(self, origin, destination):
        a, b = self.zones[str(int(origin))], self.zones[str(int(destination))]
        if a == "central" or b == "central":
            return "central"
        return "local" if a == b else "cross_area"

    def evaluate(self, origin, destination, departure, base_time):
        return self.profiles[self.profile_name(origin, destination)].travel(departure, base_time)
