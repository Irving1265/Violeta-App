#!/usr/bin/env python3
"""Genera datos de transporte para Monterrey (rutas + paradas).

Fuentes:
- OpenStreetMap / Overpass: relaciones route=bus|trolleybus + nodos bus_stop
- Regio Ruta: páginas públicas de Moovit (incluyen lista de paradas con lat/lng)

Salida:
- static/data/base_datos_rutas_mty.json      (merge de existentes + OSM + Regio Ruta)
- static/data/regioruta_monterrey.json       (solo Regio Ruta A-E)
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
STATIC_DATA = ROOT / "static" / "data"
INSTANCE_DIR = ROOT / "instance"
STATIC_DATA.mkdir(parents=True, exist_ok=True)
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)

# Área metropolitana de Monterrey: south,west,north,east
BBOX = (25.30, -100.80, 26.10, -99.90)
LAT0 = 25.6866  # para proyección local aproximada

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
USER_AGENT = "VioletaApp/1.0 (+contact@example.com)"
MOOVIT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

BASE_FILE = STATIC_DATA / "base_datos_rutas_mty.json"
REGIO_FILE = STATIC_DATA / "regioruta_monterrey.json"
MOOVIT_BUSES_FILE = STATIC_DATA / "moovit_buses_monterrey.json"
MOOVIT_REGIORUTA_LINES_URL = "https://moovitapp.com/index/es-419/transporte_p%C3%BAblico-lines-Monterrey-3081-3778826"
MOOVIT_REGIORUTA_BASE_URL = "https://moovitapp.com/index/es-419"
MOOVIT_MONTERREY_URL = "https://moovitapp.com/index/es-419/transporte_p%C3%BAblico-Monterrey-3081"

REGIO_COLORS = {
    "A": "#22c55e",
    "B": "#f59e0b",
    "C": "#3b82f6",
    "D": "#ef4444",
    "E": "#a855f7",
    "G": "#06b6d4",
}


@dataclass
class StopNode:
    stop_id: int
    name: str
    lat: float
    lon: float


def slug(text: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower())
    raw = raw.strip("_")
    return raw or "ruta"


def to_xy(lat: float, lon: float) -> Tuple[float, float]:
    x = lon * math.cos(math.radians(LAT0)) * 111_320.0
    y = lat * 110_540.0
    return x, y


def haversine_m(a: Sequence[float], b: Sequence[float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    aa = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    return 2 * r * math.asin(math.sqrt(aa))


def overpass_query(query: str, timeout: int = 60, tries: int = 2) -> Dict:
    payload = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last_err: Optional[Exception] = None
    for attempt in range(tries):
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                req = urllib.request.Request(
                    endpoint,
                    data=payload,
                    headers={"User-Agent": USER_AGENT},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                last_err = e
                time.sleep(0.35 + attempt * 0.2)
    raise RuntimeError(f"Overpass query failed: {last_err}")


def fetch_route_relations() -> List[Dict]:
    south, west, north, east = BBOX
    q = f"""
    [out:json][timeout:60];
    (
      relation["type"="route"]["route"~"bus|trolleybus"]({south},{west},{north},{east});
    );
    out ids tags;
    """.strip()
    data = overpass_query(q, timeout=120, tries=3)
    rels = [e for e in data.get("elements", []) if e.get("type") == "relation"]
    rels.sort(key=lambda e: ((e.get("tags") or {}).get("ref") or "", (e.get("tags") or {}).get("name") or ""))
    return rels


def fetch_stop_nodes() -> List[StopNode]:
    south, west, north, east = BBOX
    q = f"""
    [out:json][timeout:60];
    (
      node["highway"="bus_stop"]({south},{west},{north},{east});
      node["public_transport"="platform"]["bus"="yes"]({south},{west},{north},{east});
    );
    out body;
    """.strip()
    data = overpass_query(q, timeout=120, tries=3)
    stops: List[StopNode] = []
    seen: set[int] = set()
    for e in data.get("elements", []):
        if e.get("type") != "node":
            continue
        sid = int(e.get("id"))
        if sid in seen:
            continue
        seen.add(sid)
        tags = e.get("tags") or {}
        name = tags.get("name") or tags.get("ref") or f"Parada {sid}"
        lat = e.get("lat")
        lon = e.get("lon")
        if lat is None or lon is None:
            continue
        stops.append(StopNode(stop_id=sid, name=name, lat=float(lat), lon=float(lon)))
    return stops


def fetch_relation_line(rel_id: int) -> Tuple[Optional[Dict], List[List[float]]]:
    q = f"""
    [out:json][timeout:25];
    relation({rel_id});
    out body;
    way(r);
    out tags geom;
    """.strip()
    data = overpass_query(q, timeout=80, tries=3)
    rel = None
    way_map: Dict[int, List[List[float]]] = {}

    for e in data.get("elements", []):
        if e.get("type") == "relation":
            rel = e
        elif e.get("type") == "way":
            geom = e.get("geometry") or []
            coords: List[List[float]] = []
            for pt in geom:
                lat = pt.get("lat")
                lon = pt.get("lon")
                if lat is None or lon is None:
                    continue
                coords.append([float(lat), float(lon)])
            if len(coords) > 1:
                way_map[int(e.get("id"))] = coords

    if not rel or not way_map:
        return rel, []

    line: List[List[float]] = []
    prev_end: Optional[List[float]] = None
    for m in rel.get("members", []):
        if m.get("type") != "way":
            continue
        wcoords = way_map.get(int(m.get("ref")))
        if not wcoords:
            continue
        chunk = [p[:] for p in wcoords]
        if prev_end is not None and len(chunk) > 1:
            d_first = haversine_m(prev_end, chunk[0])
            d_last = haversine_m(prev_end, chunk[-1])
            if d_last < d_first:
                chunk.reverse()
        if not line:
            line.extend(chunk)
        else:
            if line[-1] == chunk[0]:
                line.extend(chunk[1:])
            else:
                line.extend(chunk)
        prev_end = line[-1] if line else prev_end

    # Limpieza simple de duplicados contiguos
    if line:
        cleaned = [line[0]]
        for p in line[1:]:
            if p != cleaned[-1]:
                cleaned.append(p)
        line = cleaned

    return rel, line


def project_point_to_segment(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> Tuple[float, float]:
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    seg2 = vx * vx + vy * vy
    if seg2 <= 0:
        return math.hypot(px - ax, py - ay), 0.0
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / seg2))
    qx, qy = ax + t * vx, ay + t * vy
    return math.hypot(px - qx, py - qy), t


def match_stops_to_line(line: List[List[float]], stops: List[StopNode], max_dist_m: float = 45.0) -> List[Dict]:
    if len(line) < 2:
        return []

    lats = [p[0] for p in line]
    lons = [p[1] for p in line]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    # ~200m de margen aproximado
    margin_lat = 0.002
    margin_lon = 0.002

    candidates = [
        s
        for s in stops
        if (min_lat - margin_lat) <= s.lat <= (max_lat + margin_lat)
        and (min_lon - margin_lon) <= s.lon <= (max_lon + margin_lon)
    ]
    if not candidates:
        return []

    line_xy = [to_xy(lat, lon) for lat, lon in line]
    cum = [0.0]
    for i in range(1, len(line_xy)):
        ax, ay = line_xy[i - 1]
        bx, by = line_xy[i]
        cum.append(cum[-1] + math.hypot(bx - ax, by - ay))

    matched: List[Tuple[float, StopNode]] = []
    for s in candidates:
        px, py = to_xy(s.lat, s.lon)
        best_dist = float("inf")
        best_along = 0.0
        for i in range(1, len(line_xy)):
            ax, ay = line_xy[i - 1]
            bx, by = line_xy[i]
            d, t = project_point_to_segment(px, py, ax, ay, bx, by)
            if d < best_dist:
                best_dist = d
                seg_len = math.hypot(bx - ax, by - ay)
                best_along = cum[i - 1] + t * seg_len
        if best_dist <= max_dist_m:
            matched.append((best_along, s))

    matched.sort(key=lambda x: x[0])
    result: List[Dict] = []
    seen_key: set[str] = set()
    order = 1
    for _, s in matched:
        k = f"{slug(s.name)}|{round(s.lat,6)}|{round(s.lon,6)}"
        if k in seen_key:
            continue
        seen_key.add(k)
        result.append(
            {
                "nombre": s.name,
                "lat": round(s.lat, 6),
                "lng": round(s.lon, 6),
                "orden": order,
            }
        )
        order += 1
    return result


def fetch_html(url: str, timeout: int = 30, user_agent: Optional[str] = None) -> str:
    ua = user_agent or USER_AGENT
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def moovit_hydrated_state(url: str) -> Optional[Dict]:
    try:
        html = fetch_html(url, timeout=35, user_agent=MOOVIT_USER_AGENT)
    except Exception:
        return None
    m = re.search(r'window\.__HydratedState__\s*=\s*"([^"]+)"', html)
    if not m:
        return None
    try:
        raw = base64.b64decode(m.group(1))
        return json.loads(raw)
    except Exception:
        return None


def moovit_regioruta_line_paths() -> List[str]:
    try:
        html = fetch_html(MOOVIT_REGIORUTA_LINES_URL, timeout=35, user_agent=MOOVIT_USER_AGENT)
    except Exception:
        return []
    paths = set(
        re.findall(r"/transporte_p%C3%BAblico-line-reg-Monterrey-3081-3778826-[0-9]+-0", html, flags=re.I)
    )
    return sorted(paths)


def parse_regio_letter(title: str) -> Optional[str]:
    t = (title or "").strip()
    m = re.search(r"\bRuta\s+([A-Z])\s*:", t, flags=re.I)
    if m:
        return m.group(1).upper()
    return None


def build_regioruta_routes() -> List[Dict]:
    routes: List[Dict] = []

    for path in moovit_regioruta_line_paths():
        m_id = re.search(r"-([0-9]+)-0$", path)
        line_id = m_id.group(1) if m_id else None
        url = f"{MOOVIT_REGIORUTA_BASE_URL}{path}"
        state = moovit_hydrated_state(url)
        if not state:
            continue

        model = state.get("model") or {}
        agency = model.get("agency") or {}
        agency_name = (agency.get("agencyName") or "Regio Ruta").strip()

        title = (model.get("lineTitle") or model.get("lineDisplayTitle") or "").strip()
        if not title:
            title = f"Línea {model.get('lineNumber') or 'REG'}"

        letter = parse_regio_letter(title)
        display_name = title
        if display_name.lower().startswith("ruta "):
            display_name = f"Regio {display_name}"  # -> "Regio Ruta X: ..."
        else:
            display_name = f"Regio Ruta · {display_name}"

        stops = model.get("stops") or []
        paradas: List[Dict] = []
        for idx, s in enumerate(stops, 1):
            loc = (s or {}).get("location") or {}
            lat = loc.get("lat")
            lng = loc.get("lng")
            if lat is None or lng is None:
                continue
            paradas.append(
                {
                    "nombre": (s.get("name") or f"Parada {idx}").strip(),
                    "lat": round(float(lat), 6),
                    "lng": round(float(lng), 6),
                    "orden": idx,
                }
            )
        if len(paradas) < 2:
            continue

        line: List[List[float]] = [[p["lat"], p["lng"]] for p in paradas]
        # Remover duplicados contiguos
        cleaned = [line[0]]
        for p in line[1:]:
            if p != cleaned[-1]:
                cleaned.append(p)
        line = cleaned

        rid = f"REGIORUTA_{letter or 'X'}_{line_id or slug(title)}"
        routes.append(
            {
                "key": f"regioruta_{line_id or slug(title)}",
                "id_ruta": rid,
                "nombre": display_name,
                "tipo": "bus",
                "ref": (model.get("lineNumber") or "REG").strip(),
                "operator": agency_name,
                "color": REGIO_COLORS.get(letter) if letter else None,
                "fuente": "Moovit (Regio Ruta) - lista pública de paradas",
                "linea": line,
                "paradas": paradas,
                "moovit_url": url,
            }
        )
    return routes


def moovit_bus_agencies() -> List[Dict]:
    """Obtiene agencias de transporte tipo bus dentro de Monterrey desde Moovit."""
    state = moovit_hydrated_state(MOOVIT_MONTERREY_URL)
    if not state:
        return []
    model = state.get("model") or {}
    agencies: List[Dict] = []
    for block in model.get("agenciesByType", []) or []:
        for a in block.get("agencies", []) or []:
            if str(a.get("agencyTransitTypeName") or "").lower() == "bus":
                agencies.append(a)
    return agencies


def moovit_line_paths_from_agency_lines_page(url: str) -> List[str]:
    """Extrae paths de líneas Moovit desde una página '...lines-...-AGENCYID'."""
    try:
        html = fetch_html(url, timeout=35, user_agent=MOOVIT_USER_AGENT)
    except Exception:
        return []
    # Ejemplos:
    # /transporte_p%C3%BAblico-line-tme-Monterrey-3081-854199-208742779-0
    # /transporte_p%C3%BAblico-line-411-Monterrey-3081-2019452-208311853-0
    paths = set(re.findall(r"/transporte_p%C3%BAblico-line-[^\"']+", html, flags=re.I))
    return sorted(paths)


def moovit_route_from_line_url(line_url: str, fallback_operator: Optional[str] = None) -> Optional[Dict]:
    state = moovit_hydrated_state(line_url)
    if not state:
        return None
    model = state.get("model") or {}
    agency = model.get("agency") or {}
    operator = (agency.get("agencyName") or fallback_operator or "").strip() or None

    ref = (model.get("lineNumber") or "").strip() or None
    title = (model.get("lineTitle") or model.get("lineDisplayTitle") or "").strip()
    if not title:
        title = f"Línea {ref or 'bus'}"

    # stops[]: [{ name, location: {lat,lng}, ... }]
    stops = model.get("stops") or []
    paradas: List[Dict] = []
    for idx, s in enumerate(stops, 1):
        if not isinstance(s, dict):
            continue
        loc = s.get("location") or {}
        lat = loc.get("lat")
        lng = loc.get("lng")
        if lat is None or lng is None:
            continue
        paradas.append(
            {
                "nombre": (s.get("name") or f"Parada {idx}").strip(),
                "lat": round(float(lat), 6),
                "lng": round(float(lng), 6),
                "orden": idx,
            }
        )
    if len(paradas) < 2:
        return None

    # Aproximación: el "trazo" es la secuencia de paradas. Moovit no expone la geometría completa aquí.
    line: List[List[float]] = [[p["lat"], p["lng"]] for p in paradas]
    cleaned = [line[0]]
    for p in line[1:]:
        if p != cleaned[-1]:
            cleaned.append(p)
    line = cleaned

    # extraer ids del path (si aplica)
    line_id = None
    m = re.search(r"-([0-9]+)-0$", line_url)
    if m:
        line_id = m.group(1)

    rid = f"MOOVIT_{line_id or slug(title)}"
    return {
        "key": f"moovit_{line_id or slug(title)}",
        "id_ruta": rid,
        "nombre": title,
        "tipo": "bus",
        "ref": ref,
        "operator": operator,
        "fuente": "Moovit (página pública) - lista de paradas",
        "linea": line,
        "paradas": paradas,
        "moovit_url": line_url,
    }


def build_moovit_bus_routes(limit: Optional[int] = None) -> List[Dict]:
    """Construye rutas de camión desde Moovit para Monterrey.

    Nota: Este método depende de páginas públicas de Moovit. Es útil para prototipo/offline.
    """
    agencies = moovit_bus_agencies()
    if not agencies:
        return []

    routes: List[Dict] = []
    seen_line_urls: set[str] = set()

    for a in agencies:
        agency_name = (a.get("agencyName") or "").strip() or None
        ap = (a.get("agencyPageUrl") or "").strip()
        if not ap:
            continue

        if ap.lower().startswith("http"):
            agency_url = ap
        else:
            agency_url = f"{MOOVIT_REGIORUTA_BASE_URL}/{ap}"

        line_urls: List[str] = []
        if "/transporte_p%C3%BAblico-lines-" in agency_url:
            paths = moovit_line_paths_from_agency_lines_page(agency_url)
            for p in paths:
                line_urls.append(f"{MOOVIT_REGIORUTA_BASE_URL}{p}")
        else:
            # a veces Moovit pone un URL directo a una línea
            line_urls.append(agency_url)

        for line_url in line_urls:
            if line_url in seen_line_urls:
                continue
            seen_line_urls.add(line_url)

            route = moovit_route_from_line_url(line_url, fallback_operator=agency_name)
            if route:
                routes.append(route)
            time.sleep(0.12)  # cortesía mínima

            if limit and len(routes) >= limit:
                return routes

    return routes


def build_osm_bus_routes() -> List[Dict]:
    print("Descargando relaciones de rutas (OSM)...")
    relations = fetch_route_relations()
    print(f"Relaciones encontradas: {len(relations)}")

    print("Descargando paradas base (OSM)...")
    stop_nodes = fetch_stop_nodes()
    print(f"Paradas base encontradas: {len(stop_nodes)}")

    routes: List[Dict] = []
    failures = 0
    for idx, rel in enumerate(relations, 1):
        rid = int(rel.get("id"))
        tags = rel.get("tags") or {}
        ref = (tags.get("ref") or "").strip()
        name = (tags.get("name") or "").strip()
        operator = (tags.get("operator") or "").strip()
        display_name = (name or ref or f"Ruta {rid}").strip()
        if ref and name and ref.lower() not in name.lower():
            display_name = f"{ref} - {name}"

        try:
            rel_full, line = fetch_relation_line(rid)
        except Exception:
            failures += 1
            print(f"[{idx}/{len(relations)}] timeout/error relation {rid}")
            continue

        if len(line) < 2:
            print(f"[{idx}/{len(relations)}] sin geometría útil relation {rid}")
            continue

        stops = match_stops_to_line(line, stop_nodes, max_dist_m=45.0)
        route_obj = {
            "key": f"osm_{rid}",
            "id_ruta": f"OSM_{rid}",
            "nombre": display_name,
            "tipo": "bus",
            "ref": ref or None,
            "operator": operator or None,
            "fuente": f"OpenStreetMap Overpass ({date.today().isoformat()})",
            "linea": [[round(p[0], 6), round(p[1], 6)] for p in line],
            "paradas": stops,
        }
        routes.append(route_obj)
        print(f"[{idx}/{len(relations)}] ok {display_name} | pts={len(line)} stops={len(stops)}")

    print(f"Rutas OSM generadas: {len(routes)} (fallas: {failures})")
    return routes


def load_existing_base() -> List[Dict]:
    if not BASE_FILE.exists():
        return []
    try:
        with BASE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def merge_routes(*route_lists: Iterable[Dict]) -> List[Dict]:
    merged: List[Dict] = []
    by_id: Dict[str, Dict] = {}

    for routes in route_lists:
        for r in routes:
            rid = str(r.get("id_ruta") or r.get("key") or "")
            if not rid:
                continue
            by_id[rid] = r

    merged = list(by_id.values())
    merged.sort(key=lambda x: (str(x.get("tipo") or ""), str(x.get("nombre") or "")))
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera datos offline de transporte para Monterrey.")
    parser.add_argument("--skip-osm", action="store_true", help="No consulta Overpass; conserva rutas existentes.")
    parser.add_argument("--skip-regio", action="store_true", help="No agrega Regio Ruta desde Moovit.")
    parser.add_argument(
        "--moovit-bus",
        action="store_true",
        help="Agrega rutas de camión desde Moovit (puede tardar).",
    )
    parser.add_argument(
        "--moovit-bus-limit",
        type=int,
        default=0,
        help="Límite de rutas Moovit a descargar (útil para prueba). 0 = sin límite.",
    )
    args = parser.parse_args()

    print("=== Generador de rutas Monterrey ===")
    existing = load_existing_base()
    print(f"Rutas existentes en base local: {len(existing)}")

    osm_routes: List[Dict] = [] if args.skip_osm else build_osm_bus_routes()
    regioruta_routes: List[Dict] = [] if args.skip_regio else build_regioruta_routes()
    print(f"Regio Ruta A-E generadas: {len(regioruta_routes)}")

    moovit_bus_routes: List[Dict] = []
    if args.moovit_bus:
        limit = args.moovit_bus_limit if args.moovit_bus_limit and args.moovit_bus_limit > 0 else None
        print("Descargando rutas de camión desde Moovit (Monterrey)...")
        moovit_bus_routes = build_moovit_bus_routes(limit=limit)
        print(f"Rutas Moovit generadas: {len(moovit_bus_routes)}")
        try:
            with MOOVIT_BUSES_FILE.open("w", encoding="utf-8") as f:
                json.dump(moovit_bus_routes, f, ensure_ascii=False, indent=2)
            print(f"Archivo actualizado: {MOOVIT_BUSES_FILE} ({len(moovit_bus_routes)} rutas)")
        except Exception as e:
            print(f"[WARN] No se pudo escribir {MOOVIT_BUSES_FILE}: {e}")

    merged = merge_routes(existing, osm_routes, regioruta_routes, moovit_bus_routes)

    with BASE_FILE.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    with REGIO_FILE.open("w", encoding="utf-8") as f:
        json.dump(regioruta_routes, f, ensure_ascii=False, indent=2)

    print(f"Archivo actualizado: {BASE_FILE} ({len(merged)} rutas)")
    print(f"Archivo actualizado: {REGIO_FILE} ({len(regioruta_routes)} rutas)")


if __name__ == "__main__":
    main()
