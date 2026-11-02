"""Read the benchmark network and calculate its baseline travel-time skims."""

import networkx as nx
import pandas as pd


class NetworkData:
    def __init__(self, path):
        sheets = pd.read_excel(path, sheet_name=None)
        nodes = sheets["node"]
        self.location = {int(r.id): (r.x, r.y) for r in nodes.itertuples()}
        for attribute, kind in (("ls_hl", "HL"), ("ls_al", "AL"),
                                ("ls_ts", "TS"), ("ls_depot", "DEPOT"),
                                ("ls_uam", "u")):
            setattr(self, attribute, [int(i) for i in nodes.loc[nodes.type == kind, "id"]])

        graphs = {}
        for name in ("link", "link_trn", "link_uam"):
            graph = nx.DiGraph()
            graph.add_nodes_from(self.location)
            for origin, destination, duration in sheets[name][["from", "to", "time_scale"]].itertuples(index=False, name=None):
                graph.add_edge(int(origin), int(destination), travel_time=float(duration))
            graphs[name] = graph

        service_nodes = self.ls_hl + self.ls_al + self.ls_ts + self.ls_depot + self.ls_uam
        self.tt = {}
        for origin in service_nodes:
            times = nx.single_source_dijkstra_path_length(graphs["link"], origin, weight="travel_time")
            self.tt[origin] = {destination: times[destination] for destination in service_nodes}
        self.stn_sorted = {i: sorted(self.ls_ts, key=lambda j: self.tt[i][j])
                           for i in self.ls_hl + self.ls_al}
        self.ver_sorted = {i: sorted(self.ls_uam, key=lambda j: self.tt[i][j])
                           for i in self.ls_hl + self.ls_al}
        self.tt_trn = {
            i: nx.single_source_dijkstra_path_length(graphs["link_trn"], i, weight="travel_time")
            for i in self.ls_ts
        }
        self.uam_trn = {
            i: nx.single_source_dijkstra_path_length(graphs["link_uam"], i, weight="travel_time")
            for i in self.ls_uam
        }
