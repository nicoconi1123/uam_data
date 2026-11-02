# Input definitions and generation settings

These definitions and settings describe the baseline synthetic instances in Section 5.1 and Appendix B of the manuscript. Sampling rules, fleet counts, ground capacities, and node pools are stored in `parameters/generation.json`.

## Input fields

Times are in minutes after 07:00, and monetary values are in MU. Node identifiers refer to `data/network.xlsx`.

### `demand.xlsx`

| Column | Meaning |
| --- | --- |
| `index` | Request identifier |
| `user_id` | User identifier; requests belonging to the same user are accepted or rejected together |
| `origin`, `dest` | Pickup and delivery node identifiers |
| `size` | Number of passengers in the request |
| `penalty` | Unserved-request penalty in MU, per request |
| `pickup_lb`, `pickup_ub` | Lower and upper bounds on the start of SAV boarding at the origin |
| `delivery_lb`, `delivery_ub` | Lower and upper bounds on completion of SAV alighting at the destination |
| `preferred_mode` | Admissible services, using the codes in the README |
| `accepts_pooling` | Whether SAV pooling is accepted: 1 for yes, 0 for no |
| `max_wait_minutes` | The same request-specific limit applies separately at PT egress, UAM boarding, and UAM egress |
| `vehicle_type` | Required SAV type, I or II |
| `uam_type` | Required aircraft type, I or II; `NA` for requests without UAM eligibility |

### `vehicle.xlsx`

The `vehicles` sheet contains SAV identifiers, initial depots, availability times, capacities, and types. The `evtols` sheet contains aircraft identifiers, initial vertiports, availability times, types, capacities, and energy/charging parameters. The `vertiport` sheet specifies simultaneous ground-occupancy capacities, including aircraft that are parked, receiving service, or charging.

Energy-column units are kWh for battery capacity, reserve, and takeoff–landing consumption; kWh/km for cruise consumption; and kW for charging power. Charging efficiency and the slowdown-energy fraction are dimensionless; reference speed is in km/h.

## Demand and time windows

Here, `n` is the number of requests.

| Parameter | Setting |
| --- | --- |
| Passenger service horizon | 0–600 min, starting at 07:00 |
| Party sizes 1, 2, 3, 4 | Probabilities 0.27, 0.40, 0.25, 0.08 |
| SAV pooling acceptance | Probability 0.73, sampled per user |
| Linked journeys | `floor(0.1 * n)` users with two requests each; remaining requests belong to single-journey users |
| Minimum activity gap | 90 min from the first journey's latest delivery to the second journey's earliest pickup |
| Pickup-window width | Integer uniform draw from 10 to 20 min |
| Delivery-buffer parameter | Integer uniform draw from 20 to 30 min |
| Initial pickup-start sampling span | 20–520 min, stratified across requests before timing adjustments |
| Transfer-waiting limit | 5 or 10 min, with request-row quotas of 40% and 60% |
| Spatial composition | Center–suburb 80%; suburb–suburb 20% |
| SAV boarding/alighting | 0.1 min each per request |
| eVTOL boarding/alighting | 2 / 1 min per request |
| PT transfer buffer | 2.5 min |
| Explicit aircraft relocation preparation | 2 min; may overlap charging |

The target admissible-service proportions are `SAV=0.34`, `UAM=0.26`, `SAV_UAM=0.18`, `SAV_PT=0.12`, and `FLEXIBLE=0.10`. The generator first apportions the single-service, two-service, and flexible groups in proportions 60/30/10, then apportions within each group. Integer quotas and linked-user consistency determine the realized counts. SAV and UAM type compatibility use approximately equal Type I/II quotas within their applicable request sets, independently of party size.

OD pairs are sampled from the five node pools in `generation.json`. PT-eligible pairs require distinct access and egress stations with valid connections in both directions; UAM-eligible pairs require distinct departure and arrival vertiports. Linked journeys reverse their endpoints and share party size, admissible services, pooling preference, vehicle compatibility, and waiting limits.

For pickup bounds `e` and `l`, width `w=l-e`, and sampled buffer `B`, the delivery deadline is:

```text
delivery_ub = ceil(reference_completion(l) + B - w)
delivery_lb = e
```

The reference journey is direct SAV service except for UAM-only requests, which use the complete SAV–UAM–SAV chain. Reference completion includes service durations, time-dependent road travel, and nominal flight times where applicable. Timing adjustments preserve the sampled width and buffer, initial-resource availability, linked-journey gap, and 600-minute service horizon. These checks establish individual timing conditions, not joint feasibility of all requests.

Random draws use NumPy's PCG64 generator initialized by `SeedSequence([base_seed, request_count, generation_seed])`. The supplied cases use the seeds in `data/instance_seeds.csv`. For additional cases, the generator reports count/seed combinations for which it cannot construct the prescribed time windows and initial-resource conditions.

## Fleets and infrastructure

| Requests | SAVs | eVTOLs | Central ground capacity | Four suburban ground capacities |
| ---: | ---: | ---: | ---: | --- |
| 10 | 6 | 2 | 1 | 1, 1, 1, 1 |
| 15 | 6 | 2 | 1 | 1, 1, 1, 1 |
| 20 | 8 | 2 | 2 | 1, 1, 1, 1 |
| 25 | 10 | 3 | 2 | 2, 1, 1, 1 |
| 30 | 12 | 4 | 2 | 2, 2, 1, 1 |
| 40 | 15 | 4 | 2 | 2, 2, 2, 2 |
| 50 | 18 | 5 | 3 | 3, 2, 2, 2 |
| 60 | 21 | 6 | 3 | 3, 3, 3, 3 |
| 80 | 28 | 8 | 4 | 4, 3, 3, 3 |
| 100 | 35 | 10 | 4 | 4, 4, 4, 4 |

Suburban placement order rotates with the generation seed; the four suburban capacity entries follow that order. Both fleets are distributed as evenly as integer counts permit, starting with the central area. Type I and Type II have four and eight passenger seats, respectively. All vehicles are available at time zero, and all aircraft start fully charged. The baseline directed-corridor capacity is four aircraft. Each aircraft has at most two explicit relocation visits per vertiport.

## Road profiles and aircraft energy

Baseline travel times are shortest-path sums of `time_scale` within the road, PT, and UAM layers. Stations and vertiports are ordered by baseline SAV travel time from each request endpoint, with workbook node order resolving ties. The generator uses the first station and vertiport in these lists.

| Road profile | 0–120 min | 120–240 min | 240–480 min | 480–600 min | After 600 min |
| --- | ---: | ---: | ---: | ---: | ---: |
| Either endpoint central | 0.55 | 0.85 | 1.00 | 0.65 | 1.00 |
| Different suburban areas | 0.65 | 0.90 | 1.00 | 0.70 | 1.00 |
| Same suburban area | 0.80 | 0.95 | 1.00 | 0.85 | 1.00 |

Road travel uses the relative speed factors in `parameters/road_speed_profiles.json`; a factor below one reduces speed. Travel progress is integrated across time periods to preserve FIFO, and the last factor continues during vehicle returns. The file also provides the endpoint-zone assignments.

Aircraft energy and charging inputs are stored in `parameters/aircraft_energy.json` and in each instance's `evtols` sheet.

| Aircraft parameter | Type I | Type II |
| --- | ---: | ---: |
| Passenger capacity | 4 | 8 |
| Battery capacity (kWh) | 180 | 270 |
| Minimum reserve (kWh) | 36 | 54 |
| Fixed takeoff and landing energy (kWh) | 10 | 15 |
| Cruise energy (kWh/km) | 0.5178093268644449 | 0.7767139902966674 |
| Effective charging power (kW) | 200 | 256 |
| Charging efficiency | 1 | 1 |
| Reference cruise speed (km/h) | 150 | 150 |
| Minimum cruise speed (km/h) | 100 | 100 |
| Additional cruise-energy fraction at maximum flight-time slack | 0.10 | 0.10 |

The fixed distance used for aircraft energy is inferred from the nominal flight time at the 150 km/h reference speed:

```text
flight_distance_km = nominal_flight_time_minutes * 150 / 60
nominal_flight_energy_kwh = takeoff_landing_kwh + cruise_kwh_per_km * flight_distance_km
```

Maximum flight-time slack is `nominal_flight_time_minutes * (150/100 - 1)`. Additional energy varies linearly with slack, reaching 10% of nominal cruise energy at maximum slack. Effective charging power already incorporates the charging derating, so `charge_efficiency=1`. The rationale for these experimental settings is given in manuscript Section 5.1.2.

## Fares and rejection penalties

Fares are charged per request. The generator's fare rules are implemented in `generation/economics.py`.

| Quantity | Setting |
| --- | --- |
| Solo SAV fare | `5 + baseline_SAV_time` MU per leg |
| Pooled SAV fare | 80% of the corresponding solo fare |
| UAM flight fare | `200 + 4 * nominal_flight_time` MU |
| Default rejection penalty | Highest admissible complete platform fare using solo SAV fares, multiplied by 0.8 if UAM is admissible and 0.5 otherwise |

The reference platform fare includes the SAV access and egress legs and excludes externally collected PT fares. Explicit penalties in `demand.xlsx` take precedence over the default rule.
