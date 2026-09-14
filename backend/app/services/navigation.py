"""Module 6 — navigation and wayfinding.

The graph is built fresh per request from Module 1's config (gates,
parking lots, destinations as nodes; RouteEdge rows, derived from real
road geometry, as edges) and Module 3's live state (closed roads/gates/
lots are excluded). Nothing here invents a location name, a distance, or
a path: every route's geometry is the real road geometry, concatenated
in travel order, never a straight line between two points.
"""

import itertools
from dataclasses import dataclass, field

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.destination import Destination
from app.models.gate import Gate
from app.models.parking_lot import ParkingLot
from app.repositories.campus_config import CampusConfigRepository
from app.repositories.twin import TwinRepository
from app.services.campus_config import CampusNotFoundError

WALK = "walk"
DRIVE = "drive"
MODES = (WALK, DRIVE)

NODE_TYPE_GATE = "gate"
NODE_TYPE_PARKING_LOT = "parking_lot"
NODE_TYPE_DESTINATION = "destination"


class NodeNotFoundError(Exception):
    def __init__(self, campus_id: str, node_id: str) -> None:
        self.campus_id = campus_id
        self.node_id = node_id
        super().__init__(f"node {node_id!r} not found in campus {campus_id!r}")


class NoFeasibleRouteError(Exception):
    def __init__(self, campus_id: str, start: str, end: str, mode: str) -> None:
        self.campus_id = campus_id
        self.start = start
        self.end = end
        self.mode = mode
        super().__init__(f"no feasible {mode} route from {start!r} to {end!r} in campus {campus_id!r}")


@dataclass
class RouteLeg:
    start_node_id: str
    end_node_id: str
    mode: str
    distance_m: float
    travel_time_s: float
    geometry: list[dict]
    steps: list[str]


@dataclass
class NavNode:
    node_id: str
    node_type: str
    name: str
    latitude: float
    longitude: float


@dataclass
class NearestResult:
    target: NavNode
    route: RouteLeg


@dataclass
class NavigationService:
    config_repository: CampusConfigRepository = field(default_factory=CampusConfigRepository)
    twin_repository: TwinRepository = field(default_factory=TwinRepository)

    async def _require_campus(self, session: AsyncSession, campus_id: str) -> None:
        campus = await self.config_repository.get_campus(session, campus_id)
        if campus is None:
            raise CampusNotFoundError(campus_id)

    # -- graph construction -------------------------------------------------

    async def _load_nodes(
        self, session: AsyncSession, campus_id: str
    ) -> tuple[dict[str, NavNode], dict[str, Gate], dict[str, ParkingLot], dict[str, Destination]]:
        gates = {g.gate_id: g for g in await self.config_repository.list_gates(session, campus_id)}
        lots = {p.parking_lot_id: p for p in await self.config_repository.list_parking_lots(session, campus_id)}
        destinations = {
            d.destination_id: d for d in await self.config_repository.list_destinations(session, campus_id)
        }

        nodes: dict[str, NavNode] = {}
        for gate in gates.values():
            nodes[gate.gate_id] = NavNode(gate.gate_id, NODE_TYPE_GATE, gate.name, gate.latitude, gate.longitude)
        for lot in lots.values():
            lat = lot.center_latitude
            lng = lot.center_longitude
            nodes[lot.parking_lot_id] = NavNode(lot.parking_lot_id, NODE_TYPE_PARKING_LOT, lot.name, lat, lng)
        for destination in destinations.values():
            nodes[destination.destination_id] = NavNode(
                destination.destination_id,
                NODE_TYPE_DESTINATION,
                destination.name,
                destination.latitude,
                destination.longitude,
            )
        return nodes, gates, lots, destinations

    async def _closed_node_ids(self, session: AsyncSession, campus_id: str) -> set[str]:
        closed: set[str] = set()
        for gate_state in await self.twin_repository.list_gate_states(session, campus_id):
            if gate_state.status == "closed":
                closed.add(gate_state.gate_id)
        for lot_state in await self.twin_repository.list_parking_states(session, campus_id):
            if lot_state.status == "closed":
                closed.add(lot_state.parking_lot_id)
        return closed

    async def _closed_road_ids(self, session: AsyncSession, campus_id: str) -> set[str]:
        return {
            road_state.road_id
            for road_state in await self.twin_repository.list_road_states(session, campus_id)
            if road_state.status == "closed"
        }

    async def _build_graph(self, session: AsyncSession, campus_id: str, mode: str) -> nx.DiGraph:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")

        edges = await self.config_repository.list_route_edges(session, campus_id)
        closed_nodes = await self._closed_node_ids(session, campus_id)
        closed_roads = await self._closed_road_ids(session, campus_id)

        graph = nx.DiGraph()
        for edge in edges:
            if edge.mode != mode:
                continue
            if edge.road_id in closed_roads:
                continue
            if edge.from_node in closed_nodes or edge.to_node in closed_nodes:
                continue
            weight = edge.travel_time or edge.distance
            graph.add_edge(edge.from_node, edge.to_node, weight=weight, route_edge=edge)
        return graph

    async def _road_geometry_by_id(self, session: AsyncSession, campus_id: str) -> dict[str, list[dict]]:
        roads = await self.config_repository.list_roads(session, campus_id)
        return {road.road_id: {"geometry": road.geometry, "start": road.start_node, "name": road.name} for road in roads}

    # -- routing --------------------------------------------------------

    async def find_route(
        self, session: AsyncSession, campus_id: str, start: str, end: str, mode: str
    ) -> RouteLeg:
        await self._require_campus(session, campus_id)
        nodes, *_ = await self._load_nodes(session, campus_id)
        if start not in nodes:
            raise NodeNotFoundError(campus_id, start)
        if end not in nodes:
            raise NodeNotFoundError(campus_id, end)

        graph = await self._build_graph(session, campus_id, mode)
        if start == end:
            return RouteLeg(start, end, mode, 0.0, 0.0, [], ["You're already there."])

        try:
            path = nx.dijkstra_path(graph, start, end, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
            raise NoFeasibleRouteError(campus_id, start, end, mode) from exc

        return await self._assemble_route(session, campus_id, path, mode, nodes, graph)

    async def _assemble_route(
        self,
        session: AsyncSession,
        campus_id: str,
        path: list[str],
        mode: str,
        nodes: dict[str, NavNode],
        graph: nx.DiGraph,
    ) -> RouteLeg:
        road_lookup = await self._road_geometry_by_id(session, campus_id)

        geometry: list[dict] = []
        steps: list[str] = []
        total_distance = 0.0
        total_time = 0.0

        for from_id, to_id in itertools.pairwise(path):
            edge_data = graph.get_edge_data(from_id, to_id)
            edge = edge_data["route_edge"]
            road = road_lookup[edge.road_id]
            points = [dict(p) for p in road["geometry"]]
            if road["start"] != edge.from_node:
                points = list(reversed(points))

            if geometry and points and geometry[-1] == points[0]:
                points = points[1:]
            geometry.extend(points)

            total_distance += edge.distance
            total_time += edge.travel_time

            verb = "Walk" if mode == WALK else "Drive"
            steps.append(
                f"{verb} along {road['name']} to {nodes[to_id].name} "
                f"({edge.distance:.0f} m, ~{edge.travel_time:.0f} s)"
            )

        return RouteLeg(path[0], path[-1], mode, round(total_distance, 1), round(total_time, 1), geometry, steps)

    async def find_route_to_nearest(
        self,
        session: AsyncSession,
        campus_id: str,
        start: str,
        target_type: str,
        mode: str,
        require_available: bool = False,
    ) -> NearestResult:
        await self._require_campus(session, campus_id)
        nodes, gates, lots, destinations = await self._load_nodes(session, campus_id)
        if start not in nodes:
            raise NodeNotFoundError(campus_id, start)

        if target_type == NODE_TYPE_PARKING_LOT:
            candidates = set(lots)
        elif target_type == NODE_TYPE_GATE:
            candidates = set(gates)
        elif target_type == NODE_TYPE_DESTINATION:
            candidates = set(destinations)
        else:
            raise ValueError(f"target_type must be one of gate/parking_lot/destination, got {target_type!r}")

        if require_available and target_type == NODE_TYPE_PARKING_LOT:
            # A lot is only excluded when we know for a fact it's unusable
            # (closed, or observed full). A lot with no observation yet is
            # MISSING data, not "assumed full" — excluding it on a guess
            # would be exactly the kind of silent assumption this project
            # avoids, so it stays a candidate.
            confirmed_unavailable = set()
            for lot_state in await self.twin_repository.list_parking_states(session, campus_id):
                if lot_state.status == "closed":
                    confirmed_unavailable.add(lot_state.parking_lot_id)
                    continue
                if lot_state.occupied is not None:
                    available = lot_state.usable_capacity - lot_state.occupied
                    if available <= 0:
                        confirmed_unavailable.add(lot_state.parking_lot_id)
            candidates -= confirmed_unavailable

        graph = await self._build_graph(session, campus_id, mode)
        if start not in graph:
            raise NoFeasibleRouteError(campus_id, start, target_type, mode)

        try:
            distances, paths = nx.single_source_dijkstra(graph, start, weight="weight")
        except nx.NodeNotFound as exc:
            raise NoFeasibleRouteError(campus_id, start, target_type, mode) from exc

        reachable_candidates = [node_id for node_id in candidates if node_id in distances]
        if not reachable_candidates:
            raise NoFeasibleRouteError(campus_id, start, target_type, mode)

        nearest_id = min(reachable_candidates, key=lambda node_id: distances[node_id])
        route = await self._assemble_route(session, campus_id, paths[nearest_id], mode, nodes, graph)
        return NearestResult(target=nodes[nearest_id], route=route)

    # -- search -----------------------------------------------------------

    async def search_destinations(
        self, session: AsyncSession, campus_id: str, query: str, category: str | None = None
    ) -> list[Destination]:
        await self._require_campus(session, campus_id)
        destinations = await self.config_repository.list_destinations(session, campus_id)

        query_lower = query.strip().lower()
        results = []
        for destination in destinations:
            if category and destination.category != category:
                continue
            haystacks = [destination.name.lower(), *[alias.lower() for alias in destination.searchable_aliases]]
            if any(query_lower in haystack for haystack in haystacks):
                results.append(destination)
        return results
