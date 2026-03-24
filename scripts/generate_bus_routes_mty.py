#!/usr/bin/env python3
"""
Genera static/data/base_datos_rutas_mty.json a partir de OpenStreetMap (Overpass).

Fuente:
- https://overpass-api.de/api/interpreter
- Datos OSM route=bus en el área metropolitana de Monterrey.
"""

from __future__ import annotations

import json
import math
import re
from collections import OrderedDict
from pathlib import Path

import requests

# south, west, north, east (Monterrey + zona metropolitana)
BBOX = (25.30, -100.80, 26.10, -99.90)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def safe_id(text: str | None) -> str:
    value = (text or "").lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")[:80] or "sin_id"


def is_stop_role(role: str | None) -> bool:
    r = (role or "").lower()
    return ("stop" in r) or ("platform" in r)


def dedupe_points(points: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    last = None
    for lat, lng in points:
        key = (round(lat, 7), round(lng, 7))
        if key != last:
            out.append([lat, lng])
            last = key
    return out


def poly_length_m(points: list[list[float]]) -> float:
    if len(points) < 2:
        return 0.0

    r = 6_371_000.0

    def rad(v: float) -> float:
        return v * math.pi / 180.0

    dist = 0.0
    for i in range(1, len(points)):
        lat1, lng1 = points[i - 1]
        lat2, lng2 = points[i]
        dlat = rad(lat2 - lat1)
        dlng = rad(lng2 - lng1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.sin(dlng / 2) ** 2
        )
        dist += 2 * r * math.asin(math.sqrt(a))
    return dist


def fetch_bus_relations() -> dict:
    query = f"""
    [out:json][timeout:240];
    (
      relation["type"="route"]["route"="bus"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
    );
    out body;
    >;
    out body geom;
    """
    response = requests.post(OVERPASS_URL, data=query, timeout=300)
    response.raise_for_status()
    return response.json()


def build_routes(data: dict) -> list[dict]:
    relations = [e for e in data.get("elements", []) if e.get("type") == "relation"]
    ways = {e["id"]: e for e in data.get("elements", []) if e.get("type") == "way"}
    nodes = {e["id"]: e for e in data.get("elements", []) if e.get("type") == "node"}

    raw: list[dict] = []
    for rel in relations:
        tags = rel.get("tags", {})
        name = norm(tags.get("name"))
        ref = norm(tags.get("ref"))
        if not name and not ref:
            continue
        if "prueba" in name.lower():
            continue

        line: list[list[float]] = []
        stops: list[dict] = []

        for member in rel.get("members", []):
            mtype = member.get("type")
            if mtype == "way":
                way = ways.get(member.get("ref"))
                if not way:
                    continue
                for pt in way.get("geometry") or []:
                    lat = pt.get("lat")
                    lon = pt.get("lon")
                    if lat is None or lon is None:
                        continue
                    line.append([float(lat), float(lon)])
            elif mtype == "node" and is_stop_role(member.get("role")):
                node = nodes.get(member.get("ref"))
                if not node:
                    continue
                lat = node.get("lat")
                lon = node.get("lon")
                if lat is None or lon is None:
                    continue
                nname = norm((node.get("tags") or {}).get("name")) or f"Parada {len(stops)+1}"
                stops.append(
                    {
                        "nombre": nname,
                        "lat": float(lat),
                        "lng": float(lon),
                        "orden": len(stops) + 1,
                    }
                )

        line = dedupe_points(line)
        if len(line) < 2:
            continue
        if poly_length_m(line) < 150:
            continue

        display = name or (f"Ruta {ref}" if ref else "Ruta de autobús")
        key = safe_id(ref or display)
        raw.append(
            {
                "key": key,
                "id_ruta": f"BUS_{key}",
                "nombre": display,
                "tipo": "bus",
                "ref": ref or None,
                "fuente": f"https://www.openstreetmap.org/relation/{rel['id']}",
                "linea": line,
                "paradas": stops,
            }
        )

    # Dedup por key (quedarse con el registro más completo)
    best = OrderedDict()
    for route in raw:
        score = len(route["linea"]) + (len(route["paradas"]) * 3)
        current = best.get(route["key"])
        if not current or score > current[0]:
            best[route["key"]] = (score, route)

    routes = [v[1] for v in best.values()]
    routes.sort(key=lambda x: (x.get("ref") or "", x["nombre"]))
    return routes


def main() -> None:
    data = fetch_bus_relations()
    routes = build_routes(data)
    out = Path("static/data/base_datos_rutas_mty.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(routes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Rutas guardadas: {len(routes)} -> {out}")


if __name__ == "__main__":
    main()

