# Multimodal UAM Data and Instance Generation

Data and instance-generation code accompanying **Integrated Air–Ground Operations in Multimodal Urban Mobility: Joint Service-Chain Selection, Fleet Routing, and Scheduling**.

This package provides the baseline synthetic inputs and their generator: five instances at each request size of 10, 15, 20, 25, 30, 40, 50, 60, 80, and 100, for a total of 50 instances.

## Contents

```text
data/
  network.xlsx                 Multimodal network
  instance_seeds.csv           Benchmark names and their actual generation seeds
  instances/Inst_cN_S/
    demand.xlsx                Passenger requests
    vehicle.xlsx               SAVs, eVTOLs, and vertiport ground capacities
parameters/                    Generation, road-profile, and aircraft settings
generation/                    Utilities used by the generator
generate_instances.py          Instance generator
PARAMETERS.md                  Input fields, units, and generation rules
requirements.txt              Python dependencies
```

## Installation and generation

Use Python 3.10 or later. From this directory:

```bash
python -m pip install -r requirements.txt
python generate_instances.py
```

The default command regenerates all 50 instances in `generated/`, using the network and seed mapping supplied in `data/`. No solver installation is required.

All 50 instances were reproduced with Python 3.12.14, NumPy 2.3.5, pandas 3.0.1, NetworkX 3.4.2, and openpyxl 3.1.5.

To regenerate selected benchmark instances:

```bash
python generate_instances.py --instances Inst_c10_1 Inst_c100_5
```

To generate additional instances using explicitly chosen seeds:

```bash
python generate_instances.py --calls 20 40 --seeds 1 2 3 --output-dir generated/new_instances
```

**The final number in a benchmark directory name is an instance identifier, not necessarily its generation seed.** Use `data/instance_seeds.csv` to reproduce the supplied cases. Additional instances use their generation seed in the directory name; the default base seed is 20261004.

## Using the data

Times are in minutes after 07:00, with a passenger service horizon of 600 minutes (17:00). Monetary values are model monetary units (MU). `network.xlsx` contains four sheets:

| Sheet | Columns | Meaning |
| --- | --- | --- |
| `node` | `id`, `x`, `y`, `type` | Node identifier, schematic layout coordinates, and node role |
| `link` | `from`, `to`, `time_scale` | Directed road connection and baseline travel time in minutes |
| `link_trn` | `from`, `to`, `time_scale` | Directed PT connection and travel time in minutes |
| `link_uam` | `from`, `to`, `time_scale` | Directed aerial corridor and nominal flight time in minutes |

Service-node types are `DEPOT` (SAV depot), `AL` (activity location), `HL` (home location), `TS` (transit station), and `u` (vertiport).

**Use `time_scale` directly: scaling is already included.** The `x` and `y` columns describe the network layout; travel times come from the link weights.

Each instance contains `demand.xlsx` for passenger requests and `vehicle.xlsx` for the SAV fleet, eVTOL fleet, and vertiport ground capacities. The `preferred_mode` field specifies the admissible services:

| Code | Admissible complete services |
| --- | --- |
| `SAV` | Direct SAV |
| `UAM` | SAV–UAM–SAV |
| `SAV_UAM` | Direct SAV or SAV–UAM–SAV |
| `SAV_PT` | Direct SAV or SAV–PT–SAV |
| `FLEXIBLE` | All three services |

When reading `demand.xlsx` with pandas, use `keep_default_na=False` to preserve the literal `NA` aircraft-type code.

See [PARAMETERS.md](PARAMETERS.md) for the complete field definitions, sampling rules, fleet settings, travel-time calculations, and energy and penalty formulas.
