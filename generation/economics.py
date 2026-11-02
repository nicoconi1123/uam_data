"""Shared per-request fares and fare-linked penalties from manuscript Section 5.1.2.

Amounts are model monetary units (MU), not calibrated currency quotations.
Fares are per booking; party size determines vehicle loads.
"""

from dataclasses import dataclass
import math

from .input_rules import valid_transit_leg


@dataclass(frozen=True)
class FareParameters:
    sav_base: float = 5.0
    sav_per_minute: float = 1.0
    pooling_discount: float = 0.2
    air_base: float = 200.0
    air_per_minute: float = 4.0
    ground_penalty_factor: float = 0.5
    air_penalty_factor: float = 0.8


def request_prices(reader, origin, destination, mode, parameters=None):
    p = parameters or FareParameters()
    ta, tb = reader.stn_sorted[origin][0], reader.stn_sorted[destination][0]
    a, b = reader.ver_sorted[origin][0], reader.ver_sorted[destination][0]
    result = {}
    for name, i, j in (
        ("sav", origin, destination),
        ("transit_access", origin, ta),
        ("transit_egress", tb, destination),
        ("uam_access", origin, a),
        ("uam_egress", b, destination),
    ):
        fare = p.sav_base + p.sav_per_minute * reader.tt[i][j]
        result[f"standard_fare_{name}"] = fare
        result[f"pooling_fare_{name}"] = fare * (1 - p.pooling_discount)
    flight_time = reader.uam_trn[a][b]
    result["fare_uam_flight"] = p.air_base + p.air_per_minute * flight_time
    menu = {
        "SAV": ("sav",),
        "SAV_PT": ("sav", "pt"),
        "UAM": ("air",),
        "SAV_UAM": ("sav", "air"),
        "FLEXIBLE": ("sav", "pt", "air"),
    }
    if mode not in menu:
        raise ValueError(f"Unknown preferred_mode: {mode}")
    references = {"sav": result["standard_fare_sav"]}
    if valid_transit_leg(ta, tb, reader.tt_trn):
        references["pt"] = (
            result["standard_fare_transit_access"] + result["standard_fare_transit_egress"]
        )
    if a != b and math.isfinite(flight_time) and flight_time > 0:
        references["air"] = (
            result["standard_fare_uam_access"]
            + result["fare_uam_flight"]
            + result["standard_fare_uam_egress"]
        )
    available = [references[name] for name in menu[mode] if name in references]
    if not available:
        raise ValueError(f"Request {origin}->{destination} has no valid {mode} service chain.")
    reference = max(available)
    alpha = p.air_penalty_factor if "air" in menu[mode] else p.ground_penalty_factor
    result.update(reference_fare=reference, penalty_alpha=alpha, penalty=alpha * reference)
    return result
