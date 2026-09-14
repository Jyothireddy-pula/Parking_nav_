import { useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Polygon, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import type { LatLngBoundsExpression, LatLngExpression } from "leaflet";
import "leaflet/dist/leaflet.css";

import {
  ApiError,
  DestinationOut,
  DestinationSearchResultOut,
  GateOut,
  NearestResultOut,
  ParkingLotOut,
  ParkingStateOut,
  RouteLegOut,
  fetchDestinations,
  fetchGates,
  fetchNearestParking,
  fetchParkingLots,
  fetchRoute,
  fetchState,
  reportParkingStatus,
  searchDestinations,
} from "./api";

// The real VIT-AP campus boundary, pulled from OpenStreetMap via the
// Overpass API (Module 1B Step 1) — not a guessed center point. See
// configs/campuses/vitap/real_survey/osm_reference/.
const CAMPUS_ID = "vitap";
const VITAP_BOUNDS: LatLngBoundsExpression = [
  [16.4911, 80.4946],
  [16.4971, 80.5018],
];

const OSM_TILES = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const SATELLITE_TILES =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const SATELLITE_ATTRIBUTION = "Tiles &copy; Esri";

function toLatLngs(points: { lat: number; lng: number }[]): LatLngExpression[] {
  return points.map((p) => [p.lat, p.lng]);
}

function occupancyColor(state: ParkingStateOut | undefined): string {
  if (!state || state.occupancy_pct === null) return "#9aa19b"; // grey: unknown / never observed
  if (state.occupancy_pct >= 90) return "#c0392b"; // red
  if (state.occupancy_pct >= 60) return "#e08e0b"; // orange
  return "#2f8b57"; // green
}

function FitBounds({ bounds }: { bounds: LatLngBoundsExpression }) {
  const map = useMap();
  useEffect(() => {
    map.fitBounds(bounds);
  }, [map, bounds]);
  return null;
}

function GeolocateButton({ gates, onFound }: { gates: GateOut[]; onFound: (gateId: string) => void }) {
  const [status, setStatus] = useState<"idle" | "locating" | "error">("idle");

  function nearestGate(lat: number, lng: number): GateOut | null {
    if (gates.length === 0) return null;
    let best = gates[0];
    let bestDist = Infinity;
    for (const gate of gates) {
      const d = (gate.latitude - lat) ** 2 + (gate.longitude - lng) ** 2;
      if (d < bestDist) {
        bestDist = d;
        best = gate;
      }
    }
    return best;
  }

  function locate() {
    if (!("geolocation" in navigator)) {
      setStatus("error");
      return;
    }
    setStatus("locating");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setStatus("idle");
        const gate = nearestGate(pos.coords.latitude, pos.coords.longitude);
        if (gate) onFound(gate.gate_id);
      },
      () => setStatus("error"),
      { timeout: 8000 },
    );
  }

  return (
    <div className="geolocate">
      <button type="button" onClick={locate} disabled={status === "locating"}>
        {status === "locating" ? "Finding you…" : "Use my location"}
      </button>
      {status === "error" && <p className="hint">Couldn't get your location — pick a gate below instead.</p>}
    </div>
  );
}

export default function Navigate() {
  const [gates, setGates] = useState<GateOut[]>([]);
  const [destinations, setDestinations] = useState<DestinationOut[]>([]);
  const [lots, setLots] = useState<ParkingLotOut[]>([]);
  const [parkingState, setParkingState] = useState<Record<string, ParkingStateOut>>({});
  const [loadError, setLoadError] = useState<string | null>(null);

  const [satellite, setSatellite] = useState(false);
  const [startGateId, setStartGateId] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<DestinationSearchResultOut[]>([]);
  const [destinationId, setDestinationId] = useState<string>("");

  const [legToParking, setLegToParking] = useState<NearestResultOut | null>(null);
  const [legToDestination, setLegToDestination] = useState<RouteLegOut | null>(null);
  const [routeError, setRouteError] = useState<string | null>(null);
  const [routing, setRouting] = useState(false);

  const [reportLotId, setReportLotId] = useState<string>("");
  const [reportCount, setReportCount] = useState<string>("");
  const [reportStatus, setReportStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");

  useEffect(() => {
    Promise.all([fetchGates(CAMPUS_ID), fetchDestinations(CAMPUS_ID), fetchParkingLots(CAMPUS_ID)])
      .then(([g, d, l]) => {
        setGates(g);
        setDestinations(d);
        setLots(l);
        if (g.length > 0) setStartGateId(g[0].gate_id);
        if (l.length > 0) setReportLotId(l[0].parking_lot_id);
      })
      .catch((err: unknown) => setLoadError(err instanceof ApiError ? err.message : "Could not load campus data."));
  }, []);

  useEffect(() => {
    let cancelled = false;
    function poll() {
      fetchState(CAMPUS_ID)
        .then((state) => {
          if (cancelled) return;
          const byLot: Record<string, ParkingStateOut> = {};
          for (const p of state.parking) byLot[p.parking_lot_id] = p;
          setParkingState(byLot);
        })
        .catch(() => {
          /* live status is best-effort; markers just show "unknown" */
        });
    }
    poll();
    const interval = setInterval(poll, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (searchQuery.trim().length < 2) {
      setSearchResults([]);
      return;
    }
    let cancelled = false;
    searchDestinations(CAMPUS_ID, searchQuery)
      .then((results) => {
        if (!cancelled) setSearchResults(results);
      })
      .catch(() => {
        if (!cancelled) setSearchResults([]);
      });
    return () => {
      cancelled = true;
    };
  }, [searchQuery]);

  async function planRoute() {
    if (!startGateId || !destinationId) return;
    setRouting(true);
    setRouteError(null);
    setLegToParking(null);
    setLegToDestination(null);
    try {
      const parkingLeg = await fetchNearestParking(CAMPUS_ID, startGateId);
      const destinationLeg = await fetchRoute(CAMPUS_ID, parkingLeg.target.node_id, destinationId, "walk");
      setLegToParking(parkingLeg);
      setLegToDestination(destinationLeg);
    } catch (err) {
      setRouteError(
        err instanceof ApiError
          ? err.status === 409
            ? "No route found — that destination may not be reachable right now."
            : err.message
          : "Something went wrong finding a route.",
      );
    } finally {
      setRouting(false);
    }
  }

  async function submitReport() {
    const count = Number(reportCount);
    if (!reportLotId || Number.isNaN(count) || count < 0) return;
    setReportStatus("sending");
    try {
      await reportParkingStatus(CAMPUS_ID, reportLotId, count);
      setReportStatus("sent");
      setReportCount("");
      fetchState(CAMPUS_ID).then((state) => {
        const byLot: Record<string, ParkingStateOut> = {};
        for (const p of state.parking) byLot[p.parking_lot_id] = p;
        setParkingState(byLot);
      });
    } catch {
      setReportStatus("error");
    }
  }

  const allSteps = useMemo(() => {
    const steps: string[] = [];
    if (legToParking) steps.push(...legToParking.route.steps, `Park at ${legToParking.target.name}.`);
    if (legToDestination) steps.push(...legToDestination.steps);
    return steps;
  }, [legToParking, legToDestination]);

  if (loadError) {
    return (
      <main className="nav-shell">
        <p className="nav-error">Couldn't load campus data: {loadError}</p>
      </main>
    );
  }

  return (
    <div className="nav-shell">
      <div className="nav-map">
        <MapContainer bounds={VITAP_BOUNDS} className="leaflet-container" scrollWheelZoom>
          <FitBounds bounds={VITAP_BOUNDS} />
          {satellite ? (
            <TileLayer url={SATELLITE_TILES} attribution={SATELLITE_ATTRIBUTION} />
          ) : (
            <TileLayer url={OSM_TILES} attribution={OSM_ATTRIBUTION} />
          )}

          {gates.map((gate) => (
            <CircleMarker
              key={gate.gate_id}
              center={[gate.latitude, gate.longitude]}
              radius={7}
              pathOptions={{ color: "#1d3557", fillColor: "#1d3557", fillOpacity: 0.9 }}
            >
              <Popup>{gate.name} (gate)</Popup>
            </CircleMarker>
          ))}

          {destinations.map((destination) => (
            <CircleMarker
              key={destination.destination_id}
              center={[destination.latitude, destination.longitude]}
              radius={6}
              pathOptions={{ color: "#457b9d", fillColor: "#457b9d", fillOpacity: 0.85 }}
            >
              <Popup>{destination.name}</Popup>
            </CircleMarker>
          ))}

          {lots.map((lot) => {
            const state = parkingState[lot.parking_lot_id];
            const color = occupancyColor(state);
            const stale = state && state.freshness !== "FRESH";
            const badge =
              state?.occupancy_pct !== undefined && state?.occupancy_pct !== null
                ? `${Math.round(state.occupancy_pct)}% full`
                : "No recent data";
            const positioned = lot.center_latitude !== null && lot.center_longitude !== null;

            return (
              <div key={lot.parking_lot_id}>
                {lot.geometry && lot.geometry.length >= 3 && (
                  <Polygon
                    positions={toLatLngs(lot.geometry)}
                    pathOptions={{ color, fillColor: color, fillOpacity: stale ? 0.15 : 0.3, dashArray: stale ? "4 4" : undefined }}
                  />
                )}
                {positioned && (
                  <CircleMarker
                    center={[lot.center_latitude as number, lot.center_longitude as number]}
                    radius={9}
                    pathOptions={{
                      color,
                      fillColor: color,
                      fillOpacity: stale ? 0.4 : 0.95,
                      dashArray: stale ? "2 3" : undefined,
                    }}
                  >
                    <Popup>
                      <strong>{lot.name}</strong>
                      <br />
                      {badge}
                      {state && ` (${state.freshness.toLowerCase()})`}
                    </Popup>
                  </CircleMarker>
                )}
              </div>
            );
          })}

          {legToParking && (
            <Polyline positions={toLatLngs(legToParking.route.geometry)} pathOptions={{ color: "#1d3557", weight: 5 }} />
          )}
          {legToDestination && (
            <Polyline positions={toLatLngs(legToDestination.geometry)} pathOptions={{ color: "#e08e0b", weight: 5 }} />
          )}
        </MapContainer>

        <button type="button" className="layer-toggle" onClick={() => setSatellite((s) => !s)}>
          {satellite ? "Map view" : "Satellite view"}
        </button>
      </div>

      <div className="nav-panel">
        <h1>Find parking &amp; get there</h1>

        <section>
          <h2>1. Where are you entering from?</h2>
          <GeolocateButton gates={gates} onFound={setStartGateId} />
          <label>
            Gate
            <select value={startGateId} onChange={(e) => setStartGateId(e.target.value)}>
              {gates.map((gate) => (
                <option key={gate.gate_id} value={gate.gate_id}>
                  {gate.name}
                </option>
              ))}
            </select>
          </label>
        </section>

        <section>
          <h2>2. Where are you going?</h2>
          <input
            type="text"
            placeholder="Search a building, hostel, library…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchResults.length > 0 && (
            <ul className="search-results">
              {searchResults.map((result) => (
                <li key={result.destination_id}>
                  <button
                    type="button"
                    className={result.destination_id === destinationId ? "selected" : ""}
                    onClick={() => {
                      setDestinationId(result.destination_id);
                      setSearchQuery(result.name);
                      setSearchResults([]);
                    }}
                  >
                    {result.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <button type="button" className="primary" onClick={planRoute} disabled={!startGateId || !destinationId || routing}>
          {routing ? "Finding route…" : "Get directions"}
        </button>

        {routeError && <p className="nav-error">{routeError}</p>}

        {allSteps.length > 0 && (
          <section className="steps">
            <h2>Directions</h2>
            <ol>
              {allSteps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          </section>
        )}

        <section className="report">
          <h2>Report parking status</h2>
          <p className="hint">Seeing this lot right now? Let others know how full it is.</p>
          <label>
            Lot
            <select value={reportLotId} onChange={(e) => setReportLotId(e.target.value)}>
              {lots.map((lot) => (
                <option key={lot.parking_lot_id} value={lot.parking_lot_id}>
                  {lot.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Cars parked right now
            <input
              type="number"
              min={0}
              inputMode="numeric"
              value={reportCount}
              onChange={(e) => setReportCount(e.target.value)}
            />
          </label>
          <button type="button" onClick={submitReport} disabled={reportStatus === "sending"}>
            {reportStatus === "sending" ? "Sending…" : "Report"}
          </button>
          {reportStatus === "sent" && <p className="hint">Thanks — status updated.</p>}
          {reportStatus === "error" && <p className="nav-error">Couldn't send that — try again.</p>}
        </section>
      </div>
    </div>
  );
}
