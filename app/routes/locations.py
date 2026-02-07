"""
Locations API - Provides structured city/state data for property forms
"""

from fastapi import APIRouter, HTTPException, Query, status
from typing import List, Optional
import json

router = APIRouter(prefix="/api/locations", tags=["locations"])

# Location structure: state -> list of cities
LOCATIONS_DATA = {
    "Abuja": {
        "state_code": "FCT",
        "cities": [
            {"id": "maitama", "name": "Maitama", "lat": 9.0765, "lng": 7.3986},
            {"id": "wuse", "name": "Wuse", "lat": 9.0833, "lng": 7.5000},
            {"id": "jabi", "name": "Jabi", "lat": 9.0500, "lng": 7.5333},
            {"id": "garki", "name": "Garki", "lat": 9.0667, "lng": 7.5000},
            {"id": "asokoro", "name": "Asokoro", "lat": 9.0333, "lng": 7.5333},
            {"id": "gwarinpa", "name": "Gwarinpa", "lat": 9.0833, "lng": 7.5167},
            {"id": "kubwa", "name": "Kubwa", "lat": 9.0667, "lng": 7.3500},
            {"id": "cdb", "name": "Central Business District", "lat": 9.0500, "lng": 7.5000},
        ]
    },
    "Lagos": {
        "state_code": "Lagos State",
        "cities": [
            {"id": "lekki_phase_1", "name": "Lekki Phase 1", "lat": 6.4611, "lng": 3.5764},
            {"id": "lekki_phase_2", "name": "Lekki Phase 2", "lat": 6.4500, "lng": 3.5667},
            {"id": "ikoyi", "name": "Ikoyi", "lat": 6.4639, "lng": 3.6300},
            {"id": "victoria_island", "name": "Victoria Island", "lat": 6.4269, "lng": 3.4251},
            {"id": "banana_island", "name": "Banana Island", "lat": 6.4272, "lng": 3.4222},
            {"id": "yaba", "name": "Yaba", "lat": 6.5244, "lng": 3.3792},
            {"id": "ikeja", "name": "Ikeja", "lat": 6.5833, "lng": 3.3667},
            {"id": "surulere", "name": "Surulere", "lat": 6.5167, "lng": 3.3500},
            {"id": "lagos_island", "name": "Lagos Island", "lat": 6.4569, "lng": 3.4500},
            {"id": "shomolu", "name": "Shomolu", "lat": 6.5333, "lng": 3.4333},
            {"id": "ajah", "name": "Ajah", "lat": 6.4333, "lng": 3.6333},
            {"id": "epe", "name": "Epe", "lat": 6.5833, "lng": 4.0333},
        ]
    },
    "Port Harcourt": {
        "state_code": "Rivers State",
        "cities": [
            {"id": "elekahia", "name": "Elekahia", "lat": 4.8333, "lng": 7.0500},
            {"id": "old_gra", "name": "Old GRA", "lat": 4.8167, "lng": 7.0500},
            {"id": "gra", "name": "GRA Port Harcourt", "lat": 4.8200, "lng": 7.0600},
            {"id": "rumuokwuta", "name": "Rumuokwuta", "lat": 4.8500, "lng": 7.0333},
            {"id": "rumuogbolu", "name": "Rumuogbolu", "lat": 4.8667, "lng": 7.0667},
            {"id": "trans_amadi", "name": "Trans Amadi", "lat": 4.8667, "lng": 7.0500},
            {"id": "d_line", "name": "D-Line", "lat": 4.8833, "lng": 7.0500},
            {"id": "rumuola", "name": "Rumuola", "lat": 4.8500, "lng": 7.0667},
        ]
    }
}


@router.get("/states", response_model=dict)
async def get_states():
    """
    Get all available states/regions
    """
    try:
        states = [
            {
                "id": state,
                "name": state,
                "state_code": LOCATIONS_DATA[state]["state_code"],
                "cities_count": len(LOCATIONS_DATA[state]["cities"])
            }
            for state in LOCATIONS_DATA.keys()
        ]
        return {
            "success": True,
            "states": sorted(states, key=lambda x: x["name"])
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch states: {str(e)}"
        )


@router.get("/cities", response_model=dict)
async def get_cities(state: Optional[str] = Query(None)):
    """
    Get cities for a specific state
    If state is provided, return cities for that state
    If not provided, return all cities across all states
    """
    try:
        if state:
            if state not in LOCATIONS_DATA:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"State '{state}' not found"
                )
            
            location_data = LOCATIONS_DATA[state]
            return {
                "success": True,
                "state": state,
                "state_code": location_data["state_code"],
                "cities": location_data["cities"]
            }
        else:
            # Return all cities
            all_cities = []
            for state, data in LOCATIONS_DATA.items():
                for city in data["cities"]:
                    city_with_state = {**city, "state": state, "state_code": data["state_code"]}
                    all_cities.append(city_with_state)
            
            return {
                "success": True,
                "cities": sorted(all_cities, key=lambda x: x["name"])
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch cities: {str(e)}"
        )


@router.get("/search", response_model=dict)
async def search_locations(q: Optional[str] = Query(None)):
    """
    Search for cities by name (fuzzy search)
    Returns matching cities with their states
    """
    try:
        if not q or len(q.strip()) < 2:
            return {
                "success": True,
                "results": []
            }
        
        query = q.lower().strip()
        results = []
        
        for state, data in LOCATIONS_DATA.items():
            for city in data["cities"]:
                # Match by city name or ID
                if query in city["name"].lower() or query in city["id"].lower():
                    results.append({
                        **city,
                        "state": state,
                        "state_code": data["state_code"]
                    })
        
        # Sort by relevance (exact match first, then contains)
        exact_matches = [r for r in results if r["name"].lower() == query]
        partial_matches = [r for r in results if r not in exact_matches]
        results = exact_matches + partial_matches
        
        return {
            "success": True,
            "query": q,
            "results": results[:20]  # Limit to 20 results
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )


@router.get("/complete", response_model=dict)
async def get_complete_locations():
    """
    Get complete location hierarchy (states with all their cities)
    Used for initializing form dropdowns
    """
    try:
        locations = {}
        for state, data in LOCATIONS_DATA.items():
            locations[state] = {
                "state_code": data["state_code"],
                "cities": data["cities"]
            }
        
        return {
            "success": True,
            "locations": locations
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch locations: {str(e)}"
        )
