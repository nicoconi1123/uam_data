"""Generate passenger requests and fleets for the synthetic benchmark network."""

import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from generation.network import NetworkData
from generation.input_rules import require_node, valid_transit_leg, aircraft_parameters
from generation.economics import request_prices
from generation.time_dependent import TimeDependentRoadTimes

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "parameters/generation.json").read_text(encoding="utf-8"))
SETTINGS = CONFIG["settings"]
ZONES = {int(key): value for key, value in CONFIG["zones"].items()}
AIR_MODES = ("UAM", "SAV_UAM", "FLEXIBLE")


def fleet_region_sequence(count, ports, seed):
    """Balanced five-region allocation, with every remainder starting at the center."""
    center = 10005
    if set(ports) != set(range(10001, 10006)):
        raise ValueError("Fleet allocation requires the five configured vertiports.")
    outer = sorted(p for p in ports if p != center)
    offset = (seed - 1) % len(outer)
    order = [center] + outer[offset:] + outer[:offset]
    return [order[k % len(order)] for k in range(count)]


def ground_capacities(count, ports, seed, aircraft_count):
    """Assign the fixed capacity budget without consuming any random draws."""
    order = fleet_region_sequence(len(ports), ports, seed)
    values = SETTINGS["ground_capacities"].get(str(count))
    if values is None:
        values = [math.ceil(aircraft_count * (0.4 if p == 10005 else 0.2)) + 1
                  for p in order]
    if len(values) != len(order) or any(type(q) is not int or q < 1 for q in values):
        raise ValueError("Vertiport capacities must be five positive integers.")
    return dict(zip(order, values))


def apportioned_counts(total, probabilities):
    """Largest remainders: integer quotas sum to total; ties use dictionary order."""
    mass = sum(probabilities.values())
    raw = {label: total * p / mass for label, p in probabilities.items()}
    counts = {label: math.floor(value) for label, value in raw.items()}
    # Prevent binary floating-point noise from deciding mathematical ties.
    order = sorted(raw, key=lambda label: -round(raw[label] - counts[label], 12))
    for label in order[: total - sum(counts.values())]:
        counts[label] += 1
    return counts


def assign_group_labels(weights, counts, rng):
    """Allocate request-row quotas while giving both legs of each pair one label."""
    remaining = dict(counts)
    labels = [None] * len(weights)
    # Assign pairs first so singletons can absorb all odd quota remainders.
    for index in sorted(range(len(weights)), key=lambda i: -weights[i]):
        weight = weights[index]
        eligible = [label for label, quota in remaining.items() if quota >= weight]
        if not eligible:
            raise ValueError("Category quotas cannot accommodate the requested user bundles.")
        mass = np.array([remaining[label] for label in eligible], dtype=float)
        label = str(rng.choice(eligible, p=mass / mass.sum()))
        labels[index] = label
        remaining[label] -= weight
    if any(remaining.values()):
        raise ValueError("User-bundle weights do not exhaust the request quotas.")
    return labels


def request_mode_counts(count):
    """Control 60/30/10 macro shares first, retaining the existing within-group split."""
    p = SETTINGS["mode_probabilities"]
    categories = {
        "single": ("SAV", "UAM"),
        "combined": ("SAV_UAM", "SAV_PT"),
        "flexible": ("FLEXIBLE",),
    }
    macro = apportioned_counts(
        count, {k: sum(p[m] for m in modes) for k, modes in categories.items()}
    )
    result = {}
    for category, modes in categories.items():
        result.update(apportioned_counts(macro[category], {m: p[m] for m in modes}))
    return result


def earliest_chain_finish(reader, road, origin, dest, start, mode):
    """Reference completion: direct SAV, or the full nominal UAM chain for UAM-only."""

    def drive(a, b, t):
        return t + road.evaluate(a, b, t, reader.tt[a][b])

    if mode != "UAM":
        return drive(origin, dest, start + 0.1) + 0.1
    a, b = reader.ver_sorted[origin][0], reader.ver_sorted[dest][0]
    ready = drive(origin, a, start + 0.1) + 0.1
    landed = ready + 2 + reader.uam_trn[a][b] + 1
    return drive(b, dest, landed + 0.1) + 0.1


def initial_uam_pickup_floor(reader, road, vehicles, aircraft, origin, dest,
                             vehicle_type, uam_type, size, horizon):
    """Construct a zero-queue chain using initial fleets, independently for one request.

    Distinct access/egress SAVs and one compatible aircraft suffice. The aircraft
    can first fly empty to the origin port and, only if needed, recharge there.
    This is a sufficient availability check, not a joint schedule or demand filter.
    """
    a, b = reader.ver_sorted[origin][0], reader.ver_sorted[dest][0]

    def drive(o, d, t):
        return t + road.evaluate(o, d, t, reader.tt[o][d])

    savs = [v for v in vehicles if v["type"] == vehicle_type and v["capacity"] >= size]
    arrivals = [(v["v_id"], drive(v["depot"], origin, v["starting_time"]),
                 drive(v["depot"], b, v["starting_time"])) for v in savs]
    air_ready = []
    for e in aircraft:
        if e["type"] != uam_type or e["capacity"] < size:
            continue

        def energy(o, d):
            return (e["takeoff_landing_kwh"] + e["cruise_kwh_per_km"]
                    * reader.uam_trn[o][d] * e["energy_reference_speed_kmh"] / 60) if o != d else 0

        empty = energy(e["vertiport"], a)
        loaded = energy(a, b)
        usable = e["battery_kwh"] - e["reserve_kwh"]
        if max(empty, loaded, energy(b, e["vertiport"])) > usable:
            continue
        ready = e["starting_time"]
        if e["vertiport"] != a:
            ready += reader.uam_trn[e["vertiport"]][a]
        if e["battery_kwh"] - empty < loaded + e["reserve_kwh"]:
            ready += empty * 60 / (e["charge_power_kw"] * e["charge_efficiency"])
        air_ready.append(ready)

    def available(t):
        access_ready = drive(origin, a, t + 0.1) + 0.1
        off = access_ready + 2 + reader.uam_trn[a][b] + 1
        return (bool(air_ready) and min(air_ready) <= access_ready
                and any(i != j and access <= t and egress <= off
                        for i, access, _ in arrivals for j, _, egress in arrivals))

    if not available(horizon):
        raise ValueError("No compatible initial SAV-aircraft-SAV chain within the horizon.")
    left, right = 0, horizon
    while left < right:
        mid = (left + right) // 2
        if available(mid):
            right = mid
        else:
            left = mid + 1
    return left


def earliest_initial_sav_arrival(reader, road, vehicles, origin, vehicle_type, party_size):
    """Earliest direct arrival from a compatible initial depot, ignoring other jobs."""
    arrivals = [
        v["starting_time"]
        + road.evaluate(v["depot"], origin, v["starting_time"], reader.tt[v["depot"]][origin])
        for v in vehicles
        if v["type"] == vehicle_type and v["capacity"] >= party_size
    ]
    arrival = min(arrivals, default=math.inf)
    if not math.isfinite(arrival):
        raise ValueError("No compatible initial SAV can reach the request origin.")
    return arrival


def request_time_window(
    finish,
    sampled_start,
    width,
    total_buffer,
    initial_arrival,
    pickup_floor,
    horizon,
):
    """Fit integer windows with delivery_ub = F(pickup_ub) + buffer - width.

    Initial availability need only fall inside the pickup window, not precede
    its lower bound. A horizon adjustment may not undo that availability or the
    preceding user-trip gap. FIFO makes the deadline monotone in the start.
    """
    earliest_start = max(0, math.ceil(pickup_floor), math.ceil(initial_arrival) - width)
    start = max(int(round(sampled_start)), earliest_start)

    def bounds(lo):
        hi = lo + width
        first = finish(max(lo, initial_arrival))
        last = finish(hi)
        deadline = math.ceil(last + total_buffer - width)
        return lo, hi, deadline, first, last

    result = bounds(start)
    if result[2] > horizon:
        # Move earlier only as far as the initial arrival and user-trip gap allow.
        if bounds(earliest_start)[2] > horizon:
            raise ValueError(
                "Cannot fit initial SAV arrival, user-trip gap and sampled time-window "
                "slack within the service horizon."
            )
        left, right = earliest_start, start
        while left < right:
            mid = (left + right + 1) // 2
            if bounds(mid)[2] <= horizon:
                left = mid
            else:
                right = mid - 1
        result = bounds(left)
    lo, hi, deadline, first, last = result
    if not (0 <= lo < hi < deadline <= horizon and initial_arrival <= hi and last <= deadline):
        raise ValueError("Generated window fails initial availability or service timing checks.")
    return result


def build_instance(reader, road_spec, energy_spec, count, seed, base_seed=20261004):
    rng = np.random.default_rng(np.random.SeedSequence([base_seed, count, seed]))
    road = TimeDependentRoadTimes(road_spec)
    cfg = SETTINGS

    def choice(dist):
        return str(rng.choice(list(dist), p=list(dist.values())))

    nv, ne = cfg["fleet_counts"].get(
        str(count), [max(6, math.ceil(0.35 * count)), max(2, math.ceil(0.1 * count))]
    )
    # Interstitial sizes must not have fewer vehicles than a smaller design size.
    for n, (sav_count, air_count) in cfg["fleet_counts"].items():
        if int(n) <= count:
            nv, ne = max(nv, sav_count), max(ne, air_count)
    for role, nodes in (
        ("depot", reader.ls_depot),
        ("home", reader.ls_hl),
        ("activity", reader.ls_al),
        ("station", reader.ls_ts),
        ("vertiport", reader.ls_uam),
    ):
        for node in nodes:
            require_node(node, role)
    ports = sorted(int(v) for v in reader.ls_uam)
    order = fleet_region_sequence(len(ports), ports, seed)
    center, outer = order[0], order[1:]
    sav_regions = fleet_region_sequence(nv, ports, seed)
    air_regions = fleet_region_sequence(ne, ports, seed)

    for zone in ZONES.values():
        for role in ("depot", "home", "activity"):
            for node in zone[role]:
                require_node(node, role)
                if node not in reader.location:
                    raise ValueError(f"Configured {role} node {node} is absent from the network.")
    depots = {p: ZONES[p]["depot"] for p in ports}
    vehicles = [
        dict(
            v_id=k + 1,
            depot=int(rng.choice(depots[sav_regions[k]])),
            starting_time=0,
            capacity=4 if k % 2 else 8,
            type="I" if k % 2 else "II",
        )
        for k in range(nv)
    ]
    aircraft = [
        dict(
            v_id=k + 1,
            vertiport=air_regions[k],
            starting_time=0,
            type="I" if (k + seed) % 2 else "II",
            **aircraft_parameters(energy_spec, "I" if (k + seed) % 2 else "II"),
        )
        for k in range(ne)
    ]
    caps = ground_capacities(count, ports, seed, ne)
    initial = Counter(a["vertiport"] for a in aircraft)
    for p in ports:
        if initial[p] > caps[p]:
            raise ValueError(
                f"Initial aircraft ({initial[p]}) exceed vertiport {p} capacity ({caps[p]})."
            )
    vertiports = [dict(vertiport=p, capacity=caps[p]) for p in ports]
    od_nodes = {p: ZONES[p]["home"] + ZONES[p]["activity"] for p in ports}
    pairs = int(count * cfg["paired_request_fraction"] / 2)
    groups = count - pairs
    weights = [2] * pairs + [1] * (groups - pairs)
    modes = assign_group_labels(weights, request_mode_counts(count), rng)
    strata = assign_group_labels(
        weights, apportioned_counts(count, cfg["spatial_probabilities"]), rng
    )
    sav_types = assign_group_labels(weights, apportioned_counts(count, {"I": 1, "II": 1}), rng)
    wait_limits = assign_group_labels(
        weights, apportioned_counts(count, cfg["transfer_wait_probabilities"]), rng
    )
    air_groups = [g for g, mode in enumerate(modes) if mode in AIR_MODES]
    air_weights = [weights[g] for g in air_groups]
    air_types = dict(
        zip(
            air_groups,
            assign_group_labels(
                air_weights, apportioned_counts(sum(air_weights), {"I": 1, "II": 1}), rng
            ),
        )
    )
    rows = []
    for group in range(groups):
        bundle = weights[group]
        mode = str(modes[group])
        air_mode = mode in AIR_MODES
        origin_zone = int(rng.choice(outer))
        destination_zone = (
            center
            if strata[group] == "hub_spoke"
            else int(rng.choice([p for p in outer if p != origin_zone]))
        )
        if rng.random() < 0.5:
            origin_zone, destination_zone = destination_zone, origin_zone
        # Sample from admissible pairs within the selected zone pair. Checking
        # both directions also covers the return leg and reversed singletons.
        candidates = []
        for origin in od_nodes[origin_zone]:
            for destination in od_nodes[destination_zone]:
                a, b = reader.stn_sorted[origin][0], reader.stn_sorted[destination][0]
                if mode in ("SAV_PT", "FLEXIBLE") and not (
                    valid_transit_leg(a, b, reader.tt_trn)
                    and valid_transit_leg(b, a, reader.tt_trn)
                ):
                    continue
                if air_mode and reader.ver_sorted[origin][0] == reader.ver_sorted[destination][0]:
                    continue
                candidates.append((origin, destination))
        if not candidates:
            raise ValueError(f"No valid {mode} OD in zones {origin_zone}, {destination_zone}.")
        o, d = candidates[int(rng.integers(len(candidates)))]
        size = int(choice(cfg["party_probabilities"]))
        pooling = int(rng.random() < cfg["pooling_probability"])
        previous_deadline = None
        for member in range(bundle):
            slot = group if member == 0 else groups + group
            span_lo, span_hi = cfg["pickup_span_minutes"]
            slot_width = (span_hi - span_lo) / count
            start = span_lo + slot * slot_width + float(rng.uniform(0, slot_width))
            width = int(rng.integers(cfg["pickup_width_minutes"][0], cfg["pickup_width_minutes"][1] + 1))
            initial_arrival = earliest_initial_sav_arrival(
                reader, road, vehicles, o, sav_types[group], size
            )
            chain_arrival = initial_arrival
            if mode == "UAM":
                chain_arrival = initial_uam_pickup_floor(
                    reader, road, vehicles, aircraft, o, d, sav_types[group],
                    air_types[group], size, cfg["service_horizon_minutes"],
                )
            pickup_floor = (
                previous_deadline + cfg["minimum_activity_gap_minutes"]
                if previous_deadline is not None
                else 0
            )
            total_buffer = int(rng.integers(
                cfg["total_travel_buffer_minutes"][0], cfg["total_travel_buffer_minutes"][1] + 1
            ))
            lo, hi, deadline, first, last = request_time_window(
                lambda t: earliest_chain_finish(reader, road, o, d, t, mode),
                start,
                width,
                total_buffer,
                chain_arrival,
                pickup_floor,
                cfg["service_horizon_minutes"],
            )
            index = len(rows) + 1
            rows.append(
                dict(
                    index=index,
                    user_id=group + 1,
                    origin=o,
                    dest=d,
                    size=size,
                    penalty=0,
                    pickup_lb=lo,
                    pickup_ub=hi,
                    # No independent earliest-arrival restriction: precedence
                    # and travel/service constraints enforce physical feasibility.
                    delivery_lb=lo,
                    delivery_ub=deadline,
                    preferred_mode=mode,
                    accepts_pooling=pooling,
                    max_wait_minutes=int(wait_limits[group]),
                    vehicle_type=sav_types[group],
                    uam_type=air_types[group] if air_mode else "NA",
                )
            )
            previous_deadline = deadline
            o, d = d, o
    # Input penalties agree with the reader's fare-based opportunity-cost rule.
    for row in rows:
        o, d = row["origin"], row["dest"]
        a, b = reader.ver_sorted[o][0], reader.ver_sorted[d][0]
        mode = row["preferred_mode"]
        row["penalty"] = request_prices(reader, o, d, mode)["penalty"]
        assert any(
            v["type"] in row["vehicle_type"].split(",") and v["capacity"] >= row["size"]
            for v in vehicles
        )
        if mode in ("UAM", "SAV_UAM", "FLEXIBLE") and a != b:
            assert any(
                a["type"] == row["uam_type"] and a["capacity"] >= row["size"] for a in aircraft
            ), "No compatible aircraft type/capacity"
            ep = aircraft_parameters(energy_spec, row["uam_type"])
            required = (
                ep["takeoff_landing_kwh"]
                + ep["cruise_kwh_per_km"] * reader.uam_trn[a][b] * ep["energy_reference_speed_kmh"] / 60
            )
            assert (
                required <= ep["battery_kwh"] - ep["reserve_kwh"]
            ), "Request needs more than usable battery"
    return pd.DataFrame(rows), {
        "vehicles": pd.DataFrame(vehicles),
        "evtols": pd.DataFrame(aircraft),
        "vertiport": pd.DataFrame(vertiports),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instances", nargs="+", help="Benchmark names from data/instance_seeds.csv; default: all 50")
    parser.add_argument("--calls", nargs="+", type=int, help="Request counts for additional instances")
    parser.add_argument("--seeds", nargs="+", type=int, help="Generation seeds for additional instances")
    parser.add_argument("--base-seed", type=int, default=20261004)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "generated")
    args = parser.parse_args()
    if args.calls is not None or args.seeds is not None:
        if not args.calls or not args.seeds or args.instances:
            parser.error("Use --calls and --seeds together, separately from --instances.")
        if min(args.calls) < 1 or min(args.seeds) < 0 or args.base_seed < 0:
            parser.error("Request counts must be positive and seeds nonnegative.")
        jobs = [(f"Inst_c{n}_{s}", n, args.base_seed, s) for n in args.calls for s in args.seeds]
    else:
        with (ROOT / "data/instance_seeds.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        known = {row["instance"] for row in rows}
        if args.instances and set(args.instances) - known:
            parser.error("Unknown benchmark instance: " + ", ".join(sorted(set(args.instances) - known)))
        jobs = [(r["instance"], int(r["requests"]), int(r["base_seed"]), int(r["generation_seed"]))
                for r in rows if not args.instances or r["instance"] in args.instances]
    reader = NetworkData(ROOT / "data/network.xlsx")
    road = json.loads((ROOT / "parameters/road_speed_profiles.json").read_text(encoding="utf-8"))
    energy = json.loads((ROOT / "parameters/aircraft_energy.json").read_text(encoding="utf-8"))
    for name, count, base_seed, seed in jobs:
        demand, fleet = build_instance(reader, road, energy, count, seed, base_seed)
        directory = args.output_dir / name
        directory.mkdir(parents=True, exist_ok=True)
        provenance = {"seed_components": [base_seed, count, seed],
                      "service_horizon_minutes": SETTINGS["service_horizon_minutes"],
                      "corridor_capacity": SETTINGS["corridor_capacity"],
                      "max_relocation_visits": SETTINGS["max_relocation_visits"]}
        with pd.ExcelWriter(directory / "demand.xlsx", engine="openpyxl") as writer:
            demand.to_excel(writer, index=False)
            writer.book.properties.description = json.dumps({"uam_instance_provenance": provenance})
        with pd.ExcelWriter(directory / "vehicle.xlsx", engine="openpyxl") as writer:
            for sheet, frame in fleet.items():
                frame.to_excel(writer, sheet_name=sheet, index=False)
            writer.book.properties.description = json.dumps({"uam_instance_provenance": provenance})
        print(f"{name}: {count} requests, {len(fleet['vehicles'])} SAVs, {len(fleet['evtols'])} eVTOLs")


if __name__ == "__main__":
    main()
