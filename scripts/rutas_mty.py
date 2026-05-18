# -*- coding: utf-8 -*-
"""
Pre-procesamiento offline de rutas y paradas de transporte público en Monterrey, NL.

Requiere:
  pip install osmnx geopandas pandas shapely scipy

Salida:
  static/data/base_datos_rutas_mty.json
"""

import json
import os
import warnings

import osmnx as ox
from shapely.geometry import LineString
from scipy.spatial import cKDTree


def obtener_datos_transporte(lugar="Monterrey, Nuevo Leon, Mexico"):
    print(f"1) Descargando datos de {lugar}...")

    # Paradas (nodos)
    print("   - Buscando paradas de autobús (highway=bus_stop)...")
    tags_paradas = {"highway": "bus_stop"}
    gdf_paradas = ox.features_from_place(lugar, tags_paradas)
    gdf_paradas = gdf_paradas[gdf_paradas.geom_type == "Point"]

    # Rutas (relaciones route=bus)
    print("   - Buscando trazado de rutas (route=bus)...")
    tags_rutas = {"route": "bus"}
    gdf_rutas = ox.features_from_place(lugar, tags_rutas)
    gdf_rutas = gdf_rutas[gdf_rutas.geom_type.isin(["LineString", "MultiLineString"])]

    return gdf_paradas, gdf_rutas


def asociar_paradas_a_rutas(gdf_paradas, gdf_rutas, distancia_maxima=30):
    print("2) Asociando paradas a rutas (buffer + proyección)...")

    # Proyección métrica para medir en metros
    rutas_proj = ox.project_gdf(gdf_rutas)
    paradas_proj = ox.project_gdf(gdf_paradas, to_crs=rutas_proj.crs)

    # KDTree para acelerar búsquedas
    stop_coords = list(zip(paradas_proj.geometry.x, paradas_proj.geometry.y))
    stop_tree = cKDTree(stop_coords)

    lista_final = []

    for row in rutas_proj.itertuples():
        geom = row.geometry
        if geom.type == "MultiLineString":
            geom = LineString([pt for line in geom.geoms for pt in line.coords])

        buffer_geom = geom.buffer(distancia_maxima)
        minx, miny, maxx, maxy = buffer_geom.bounds

        # Candidatos por bounding box
        candidates = stop_tree.query_ball_point(
            [(minx, miny), (maxx, maxy)], r=max(maxx - minx, maxy - miny)
        )
        candidates = set(candidates[0] + candidates[1]) if candidates else set()
        if not candidates:
            continue

        stops = paradas_proj.iloc[list(candidates)]
        near = stops[stops.geometry.within(buffer_geom)].copy()
        if near.empty:
            continue

        # Ordenar paradas según su distancia sobre la línea
        near["distancia_inicio"] = near.geometry.apply(lambda p: geom.project(p))
        near = near.sort_values("distancia_inicio")

        # Construir lista de paradas con orden
        paradas_json = []
        for i, stop in enumerate(near.itertuples(), start=1):
            # Convertir coordenadas a lat/lon
            p_geo = ox.projection.project_geometry(
                stop.geometry, crs=paradas_proj.crs, to_latlong=True
            )
            # p_geo[0] es geometry (x=lon, y=lat)
            paradas_json.append({
                "orden": i,
                "nombre": getattr(stop, "name", None) or getattr(stop, "ref", None) or f"Parada {i}",
                "lat": float(p_geo[0].y),
                "lng": float(p_geo[0].x),
            })

        # Datos de ruta
        route_id = str(getattr(row, "osmid", None) or getattr(row, "id", None) or row.Index)
        route_name = getattr(row, "name", None) or getattr(row, "ref", None) or f"Ruta {route_id}"

        # Extraer geometría en lat/lon para dibujar la ruta
        geom_geo = ox.projection.project_geometry(geom, crs=rutas_proj.crs, to_latlong=True)[0]
        coords = [[float(lat), float(lng)] for lng, lat in geom_geo.coords]

        lista_final.append({
            "id_ruta": route_id,
            "nombre": route_name,
            "paradas": paradas_json,
            "linea": coords,
        })

    return lista_final


def main():
    warnings.filterwarnings("ignore", category=UserWarning)

    ox.settings.timeout = 180
    ox.settings.use_cache = True

    lugar = "Monterrey, Nuevo Leon, Mexico"
    output_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "static",
        "data",
        "base_datos_rutas_mty.json",
    )
    output_path = os.path.abspath(output_path)

    paradas, rutas = obtener_datos_transporte(lugar)
    if paradas.empty:
        raise RuntimeError("No se encontraron paradas (bus_stop).")
    if rutas.empty:
        raise RuntimeError("No se encontraron rutas (route=bus).")

    resultado = asociar_paradas_a_rutas(paradas, rutas, distancia_maxima=30)
    if not resultado:
        raise RuntimeError("No se pudieron asociar paradas a rutas.")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Archivo generado: {output_path}")
    print(f"   Rutas exportadas: {len(resultado)}")


if __name__ == "__main__":
    main()
