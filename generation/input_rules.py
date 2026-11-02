"""Physical node roles and admissible PT legs for the current study network."""

import math

NODE_IDS = {
    "depot": range(101, 141),
    "activity": range(201, 251),
    "station": range(301, 318),
    "home": range(401, 451),
    "vertiport": range(10001, 10006),
}


def require_node(node, *roles):
    if not any(node in NODE_IDS[role] for role in roles):
        raise ValueError(f"Node {node} is not an allowed {'/'.join(roles)} node.")


def valid_transit_leg(origin, destination, transit_times):
    duration = transit_times.get(origin, {}).get(destination, math.inf)
    return origin != destination and math.isfinite(duration) and duration > 0


def aircraft_parameters(specification, aircraft_type):
    """Return the configured parameters of one aircraft type."""
    return dict(specification["types"][aircraft_type])
