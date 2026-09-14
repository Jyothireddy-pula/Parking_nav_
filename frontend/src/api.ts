// Thin fetch wrappers around the backend's /api/v1 routes. No values are
// invented here — everything rendered by Navigate.tsx comes from one of
// these calls.

export interface GateOut {
  gate_id: string;
  name: string;
  latitude: number;
  longitude: number;
  status: string;
}

export interface DestinationOut {
  destination_id: string;
  name: string;
  category: string;
  latitude: number;
  longitude: number;
}

export interface ParkingLotOut {
  parking_lot_id: string;
  name: string;
  status: string;
  center_latitude: number | null;
  center_longitude: number | null;
  geometry: { lat: number; lng: number }[] | null;
  total_capacity: number;
  usable_capacity: number;
}

export interface ParkingStateOut {
  parking_lot_id: string;
  occupied: number | null;
  available: number | null;
  occupancy_pct: number | null;
  status: string;
  freshness: "FRESH" | "AGING" | "STALE" | "UNKNOWN";
}

export interface TwinStateOut {
  parking: ParkingStateOut[];
}

export interface RouteLegOut {
  start_node_id: string;
  end_node_id: string;
  mode: string;
  distance_m: number;
  travel_time_s: number;
  geometry: { lat: number; lng: number }[];
  steps: string[];
}

export interface NearestResultOut {
  target: { node_id: string; node_type: string; name: string; latitude: number | null; longitude: number | null };
  route: RouteLegOut;
}

export interface DestinationSearchResultOut {
  destination_id: string;
  name: string;
  category: string;
  latitude: number;
  longitude: number;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : res.statusText);
  }
  return res.json() as Promise<T>;
}

const base = (campusId: string) => `/api/v1/campuses/${encodeURIComponent(campusId)}`;

export const fetchGates = (campusId: string) => getJson<GateOut[]>(`${base(campusId)}/gates`);
export const fetchDestinations = (campusId: string) => getJson<DestinationOut[]>(`${base(campusId)}/destinations`);
export const fetchParkingLots = (campusId: string) => getJson<ParkingLotOut[]>(`${base(campusId)}/parking-lots`);
export const fetchState = (campusId: string) => getJson<TwinStateOut>(`${base(campusId)}/state`);

export const fetchRoute = (campusId: string, start: string, end: string, mode: "walk" | "drive") =>
  getJson<RouteLegOut>(
    `${base(campusId)}/navigate/route?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&mode=${mode}`,
  );

export const fetchNearestParking = (campusId: string, start: string) =>
  getJson<NearestResultOut>(
    `${base(campusId)}/navigate/nearest-parking?start=${encodeURIComponent(start)}&mode=drive&require_available=true`,
  );

export const searchDestinations = (campusId: string, query: string) =>
  getJson<DestinationSearchResultOut[]>(`${base(campusId)}/navigate/search?query=${encodeURIComponent(query)}`);

export async function reportParkingStatus(
  campusId: string,
  parkingLotId: string,
  occupiedSpaces: number,
): Promise<void> {
  const res = await fetch(`${base(campusId)}/observations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      timestamp: new Date().toISOString(),
      parking_lot_id: parkingLotId,
      occupied_spaces: occupiedSpaces,
      source_label: "REAL",
      collection_method: "manual_count",
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : res.statusText);
  }
}
