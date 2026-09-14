from pydantic import BaseModel


class RouteLegOut(BaseModel):
    start_node_id: str
    end_node_id: str
    mode: str
    distance_m: float
    travel_time_s: float
    geometry: list[dict]
    steps: list[str]


class NavNodeOut(BaseModel):
    node_id: str
    node_type: str
    name: str
    latitude: float | None
    longitude: float | None


class NearestResultOut(BaseModel):
    target: NavNodeOut
    route: RouteLegOut


class DestinationSearchResultOut(BaseModel):
    destination_id: str
    name: str
    category: str
    latitude: float
    longitude: float
