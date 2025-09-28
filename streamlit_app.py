import os
import json
import requests
import streamlit as st
import pydeck as pdk
import polyline as poly

API_URL = os.getenv("SCENIC_API_URL", "http://127.0.0.1:8000/scenic")

st.set_page_config(page_title="Tripster Scenic Tester", layout="wide")
st.title("Tripster Scenic Route Tester")

with st.sidebar:
    st.header("Trip Input")
    origin = st.text_input("Origin", "Phoenix, AZ")
    destination = st.text_input("Destination", "Sedona, AZ")
    scenic_mode = st.selectbox(
        "Scenic Mode",
        ["balanced", "nature", "water", "desert", "city"],
        index=0,
    )
    go = st.button("Plan Scenic Trip")


def route_to_path_features(route, color):
    try:
        pts = poly.decode(route.get("polyline", ""))
    except Exception:
        pts = []
    if not pts:
        return []
    return [
        {
            "path": [[lon, lat] for lat, lon in pts],
            "color": color,
            "id": route.get("id", "route"),
        }
    ]


def center_from_routes(routes):
    for r in routes:
        try:
            pts = poly.decode(r.get("polyline", ""))
            if pts:
                lat, lon = pts[len(pts) // 2]
                return lat, lon
        except Exception:
            continue
    return 34.85, -111.76


if go:
    with st.spinner("Calling Scenic API..."):
        try:
            payload = {"origin": origin, "destination": destination, "scenicMode": scenic_mode}
            r = requests.post(API_URL, json=payload, timeout=60)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            st.error(f"API call failed: {e}")
            st.stop()

    col_map, col_info = st.columns([2, 1])

    with col_info:
        st.subheader("Scores")
        st.json(data.get("scores", {}))
        st.subheader("Top Scenic Route")
        st.write(data.get("topScenicRouteId"))
        st.subheader("Explanation")
        st.write(data.get("explanation", ""))
        st.subheader("POIs (first route)")
        pois_by_route = data.get("poisByRoute", {})
        routes = data.get("routes", [])
        first_id = routes[0]["id"] if routes else None
        st.json(pois_by_route.get(first_id, [])[:10])

    with col_map:
        st.subheader("Routes")
        routes = data.get("routes", [])
        color_map = {
            "fastest": [66, 133, 244, 200],   # blue
            "scenic": [52, 168, 83, 220],     # green
        }
        fallback_colors = [
            [255, 165, 0, 200],
            [106, 90, 205, 200],
            [220, 20, 60, 200],
            [0, 206, 209, 200],
        ]
        layers = []
        for idx, route in enumerate(routes):
            col = color_map.get(route.get("id"), fallback_colors[idx % len(fallback_colors)])
            features = route_to_path_features(route, col)
            if features:
                layers.append(
                    pdk.Layer(
                        "PathLayer",
                        data=features,
                        get_path="path",
                        get_color="color",
                        width_scale=1,
                        width_min_pixels=5 if route.get("id") == data.get("topScenicRouteId") else 3,
                        pickable=True,
                    )
                )

        lat, lon = center_from_routes(routes)
        view_state = pdk.ViewState(latitude=lat, longitude=lon, zoom=8)
        st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view_state, tooltip={"text": "{id}"}))

