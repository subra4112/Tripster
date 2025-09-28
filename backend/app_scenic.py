from fastapi import FastAPI
from pydantic import BaseModel
from typing import TypedDict, Dict, List, Tuple
from langgraph.graph import StateGraph
import os, math, time, requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --------- STATE ---------
class TripState(TypedDict, total=False):
    origin: str
    destination: str
    routes: List[Dict]
    places_by_route: Dict[str, List[Dict]]
    scenic_scores: Dict[str, float]
    explanation: str

# --------- SAFE REQUEST HELPERS ---------
def safe_post(url: str, headers: Dict, json: Dict) -> Dict:
    try:
        r = requests.post(url, headers=headers, json=json, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

def safe_get(url: str, params: Dict) -> Dict:
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

# --------- MOCK DATA (if no API key) ---------
def mock_routes(origin: str, destination: str) -> List[Dict]:
    return [
        {
            "id": "fastest",
            "label": "Fastest",
            "polyline": {"encodedPolyline": "}_seFf|`uPd@w@`A_BvB}C"},
            "distanceMeters": 190000,
            "durationSeconds": 7200,
            "summary": "I-17 N",
        },
        {
            "id": "scenic",
            "label": "Scenic",
            "polyline": {"encodedPolyline": "o`seFz{`uPp@jAb@l@"},
            "distanceMeters": 210000,
            "durationSeconds": 8400,
            "summary": "State Rte 179 through red rocks",
        },
    ]

def mock_places() -> List[Dict]:
    return [
        {"name": "Oak Creek Canyon Vista", "types": ["park"], "rating": 4.7},
        {"name": "Red Rock State Park", "types": ["park"], "rating": 4.8},
    ]

# --------- ROUTE AGENT ---------
def get_routes(state: TripState) -> TripState:
    if not GOOGLE_API_KEY:
        state["routes"] = mock_routes(state["origin"], state["destination"])
        return state
    
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": (
            "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline,"
            "routes.description,routes.routeLabels"
        ),
    }
    body = {
        "origin": {"address": state["origin"]},
        "destination": {"address": state["destination"]},
        "computeAlternativeRoutes": True,
        "travelMode": "DRIVE",
    }
    resp = safe_post(url, headers, body)
    state["routes"] = resp.get("routes", []) or mock_routes(state["origin"], state["destination"])
    return state

# --------- PLACES AGENT ---------
def get_places(state: TripState) -> TripState:
    places_by_route = {}
    for r in state.get("routes", []):
        if not GOOGLE_API_KEY:
            places_by_route[r["id"]] = mock_places()
        else:
            params = {
                "location": "34.8697,-111.7609",
                "radius": 4000,
                "type": "park",
                "key": GOOGLE_API_KEY,
            }
            data = safe_get("https://maps.googleapis.com/maps/api/place/nearbysearch/json", params)
            places_by_route[r["id"]] = data.get("results", [])
    state["places_by_route"] = places_by_route
    return state

# --------- SCENIC AGENT ---------
def scenic_score(state: TripState) -> TripState:
    scores = {}
    for r in state.get("routes", []):
        places = state.get("places_by_route", {}).get(r["id"], [])
        parks = sum(1 for p in places if "park" in p.get("types", []))
        water = sum(1 for p in places if "natural_feature" in p.get("types", []))
        attractions = sum(1 for p in places if "tourist_attraction" in p.get("types", []))
        avg_rating = sum(p.get("rating", 0) for p in places) / max(1, len(places))
        score = 0.4*parks + 0.3*water + 0.2*attractions + 0.5*avg_rating
        scores[r["id"]] = round(min(10.0, score), 2)
    state["scenic_scores"] = scores
    return state

# --------- EXPLAIN AGENT (LLM) ---------
def explain_with_gemini(state: TripState) -> TripState:
    routes = state.get("routes", [])
    scenic_scores = state.get("scenic_scores", {})
    places_by_route = state.get("places_by_route", {})

    if not routes:
        state["explanation"] = "No routes available."
        return state
    
    top = max(routes, key=lambda r: scenic_scores.get(r["id"], 0))
    highlights = ", ".join(p.get("name", "") for p in places_by_route.get(top["id"], [])[:3]) or "parks and landmarks"
    score = scenic_scores.get(top["id"], 0)

    prompt = f"""You are Tripster, a travel guide.
The route '{top.get('label','Scenic')}' scores {score}/10.
It passes highlights like {highlights}.
Explain in 2–3 friendly sentences why this route is scenic."""

    if not GEMINI_API_KEY:
        state["explanation"] = f"This route scores {score}/10 with highlights: {highlights}."
        return state

    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(f"{url}?key={GEMINI_API_KEY}", headers=headers, json=payload, timeout=15)
        data = resp.json()
        state["explanation"] = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    except Exception:
        state["explanation"] = f"This route scores {score}/10 with highlights: {highlights}."
    return state

# --------- LANGGRAPH ---------
graph = StateGraph(TripState)
graph.add_node("RouteAgent", get_routes)
graph.add_node("PlacesAgent", get_places)
graph.add_node("ScenicAgent", scenic_score)
graph.add_node("ExplainAgent", explain_with_gemini)
graph.add_edge("RouteAgent", "PlacesAgent")
graph.add_edge("PlacesAgent", "ScenicAgent")
graph.add_edge("ScenicAgent", "ExplainAgent")
graph.set_entry_point("RouteAgent")
graph.set_finish_point("ExplainAgent")
app_graph = graph.compile()

# --------- FASTAPI ---------
class ScenicRequest(BaseModel):
    origin: str
    destination: str

app = FastAPI(title="Tripster Scenic API")

@app.post("/scenic")
def scenic_trip(req: ScenicRequest):
    result = app_graph.invoke({"origin": req.origin, "destination": req.destination})
    routes = [
        {
            "id": r["id"],
            "label": r.get("label", "Route"),
            "polyline": r["polyline"]["encodedPolyline"],
            "scenicScore": result.get("scenic_scores", {}).get(r["id"], 0),
        }
        for r in result.get("routes", [])
    ]
    top = max(routes, key=lambda x: x["scenicScore"], default=None)
    return {
        "routes": routes,
        "scores": result.get("scenic_scores", {}),
        "explanation": result.get("explanation", ""),
        "topScenicRouteId": top["id"] if top else None,
        "timestamp": int(time.time()),
    }
