"""
Location management tools for Kroger MCP server
"""

from typing import Annotated, Any, Dict, Optional
from pydantic import Field
from fastmcp import Context

from kroger_api import validation
from kroger_api.errors import InvalidParameterError, NotFoundError

from ..errors import KrogerToolError, translate_errors
from .params import LocationId, ZipCode
from .shared import (
    DEFAULT_ZIP_CODE,
    get_client_credentials_client, 
    get_configured_zip_code,
    get_preferred_location_id, 
    set_preferred_location_id,
)


def _default_zip_code() -> str:
    """KROGER_USER_ZIP_CODE, else the built-in default

    Raises:
        KrogerToolError: configuration_error, if KROGER_USER_ZIP_CODE is not a 5-digit ZIP code
    """
    configured = get_configured_zip_code()
    if configured is None:
        return DEFAULT_ZIP_CODE
    try:
        return validation.zip_code(configured, param="KROGER_USER_ZIP_CODE")
    except InvalidParameterError as e:
        raise KrogerToolError(
            "configuration_error",
            f"The KROGER_USER_ZIP_CODE setting is invalid: {e.requirement}.",
            next_step=(
                "Pass zip_code explicitly, or correct KROGER_USER_ZIP_CODE in this MCP server's configuration "
                "and restart the server."
            ),
            details={"setting": "KROGER_USER_ZIP_CODE", "value": configured},
        ) from e


def _location_data(response: Optional[Dict[str, Any]], location_id: str) -> Dict[str, Any]:
    """The data object of a get_location response

    Raises:
        KrogerToolError: unexpected_response, if the response has no data object
    """
    data = (response or {}).get("data")
    if not isinstance(data, dict):
        raise KrogerToolError(
            "unexpected_response",
            f"The Kroger Locations API answered without data for location {location_id}.",
            details={"response_body": response},
        )
    return data


def register_tools(mcp):
    """Register location-related tools with the FastMCP server"""
    
    @mcp.tool()
    @translate_errors
    async def search_locations(
        zip_code: ZipCode = None,
        radius_in_miles: Annotated[int, Field(ge=1, le=100, description="Search radius in miles (1-100)")] = 10,
        limit: Annotated[int, Field(ge=1, le=200, description="Number of results to return (1-200)")] = 10,
        chain: Annotated[Optional[str], Field(min_length=1, description="Only return stores of this chain, for example Kroger. See list_chains.")] = None,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Search for Kroger store locations near a zip code.
        
        Args:
            zip_code: Zip code to search near (uses environment default if not provided)
            radius_in_miles: Search radius in miles (1-100)
            limit: Number of results to return (1-200)
            chain: Filter by specific chain name
        
        Returns:
            Dictionary containing location search results
        """
        if ctx:
            await ctx.info(f"Searching for Kroger locations near {zip_code or 'default zip code'}")
        
        if not zip_code:
            # If Claude isn't provided with a zip code, he will sometimes generate one.
            # Which is why get_user_zip_code() is provided as a tool, to ensure Claude uses the
            # default zip code provided in the env.
            zip_code = _default_zip_code()
        
        client = get_client_credentials_client()
        
        locations = client.location.search_locations(
            zip_code=zip_code,
            radius_in_miles=radius_in_miles,
            limit=limit,
            chain=chain
        )
        
        # Format location data for easier consumption
        formatted_locations = []
        for loc in (locations or {}).get("data") or []:
            address = loc.get("address", {})
            formatted_loc = {
                "location_id": loc.get("locationId"),
                "name": loc.get("name"),
                "chain": loc.get("chain"),
                "phone": loc.get("phone"),
                "address": {
                    "street": address.get("addressLine1", ""),
                    "city": address.get("city", ""),
                    "state": address.get("state", ""),
                    "zip_code": address.get("zipCode", "")
                },
                "full_address": f"{address.get('addressLine1', '')}, {address.get('city', '')}, {address.get('state', '')} {address.get('zipCode', '')}",
                "coordinates": loc.get("geolocation", {}),
                "departments": [dept.get("name") for dept in loc.get("departments", [])],
                "department_count": len(loc.get("departments", []))
            }
            
            # Add hours info if available
            if "hours" in loc and "monday" in loc["hours"]:
                monday = loc["hours"]["monday"]
                if monday.get("open24", False):
                    formatted_loc["hours_monday"] = "Open 24 hours"
                elif "open" in monday and "close" in monday:
                    formatted_loc["hours_monday"] = f"{monday['open']} - {monday['close']}"
                else:
                    formatted_loc["hours_monday"] = "Hours not available"
            
            formatted_locations.append(formatted_loc)
        
        if ctx:
            await ctx.info(f"Found {len(formatted_locations)} locations")
        
        result = {
            "success": True,
            "search_params": {
                "zip_code": zip_code,
                "radius_miles": radius_in_miles,
                "limit": limit,
                "chain": chain
            },
            "count": len(formatted_locations),
            "data": formatted_locations
        }
        if not formatted_locations:
            result["message"] = (
                f"No locations found within {radius_in_miles} miles of zip code {zip_code}"
                + (f" for chain '{chain}'" if chain else "")
                + ". Try a larger radius_in_miles or another zip code."
            )
        return result

    @mcp.tool()
    @translate_errors
    async def get_user_zip_code() -> Dict[str, Any]:
        """
        Returns user zip code, it is anticipated that by exposing this to the LLM it will choose to use it
        rather than generating a zip code based on system data.

        Args: 
            N/A
        Returns:
            Dictionary containing user Zip Code
        """
        configured = get_configured_zip_code()
        if configured is None:
            return {
                "user_zip_code": DEFAULT_ZIP_CODE,
                "configured": False,
                "message": (
                    f"KROGER_USER_ZIP_CODE is not set, so {DEFAULT_ZIP_CODE} is a placeholder, not the "
                    "user's ZIP code. Ask the user for their ZIP code."
                )
            }
        return {"user_zip_code": _default_zip_code(), "configured": True}


    @mcp.tool()
    @translate_errors
    async def get_location_details(
        location_id: LocationId,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get detailed information about a specific Kroger store location.
        
        Args:
            location_id: The unique identifier for the store location
        
        Returns:
            Dictionary containing detailed location information
        """
        if ctx:
            await ctx.info(f"Getting details for location {location_id}")
        
        client = get_client_credentials_client()
        
        # An unknown location raises NotFoundError
        loc = _location_data(client.location.get_location(location_id), location_id)
            
        # Format department information
        departments = []
        for dept in loc.get("departments", []):
            dept_info = {
                "department_id": dept.get("departmentId"),
                "name": dept.get("name"),
                "phone": dept.get("phone")
            }
            
            # Add department hours
            if "hours" in dept and "monday" in dept["hours"]:
                monday = dept["hours"]["monday"]
                if monday.get("open24", False):
                    dept_info["hours_monday"] = "Open 24 hours"
                elif "open" in monday and "close" in monday:
                    dept_info["hours_monday"] = f"{monday['open']} - {monday['close']}"
            
            departments.append(dept_info)
        
        # Format the response
        address = loc.get("address", {})
        result = {
            "success": True,
            "location_id": loc.get("locationId"),
            "name": loc.get("name"),
            "chain": loc.get("chain"),
            "phone": loc.get("phone"),
            "address": {
                "street": address.get("addressLine1", ""),
                "street2": address.get("addressLine2", ""),
                "city": address.get("city", ""),
                "state": address.get("state", ""),
                "zip_code": address.get("zipCode", "")
            },
            "coordinates": loc.get("geolocation", {}),
            "departments": departments,
            "department_count": len(departments)
        }
        
        return result

    @mcp.tool()
    @translate_errors
    async def set_preferred_location(
        location_id: LocationId,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Set a preferred store location for future operations.
        
        Args:
            location_id: The unique identifier for the store location
        
        Returns:
            Dictionary confirming the preferred location has been set
        """
        if ctx:
            await ctx.info(f"Setting preferred location to {location_id}")
        
        # Verify the location exists: an unknown location raises NotFoundError
        client = get_client_credentials_client()
        loc_data = _location_data(client.location.get_location(location_id), location_id)
        
        set_preferred_location_id(location_id)
        
        if ctx:
            await ctx.info(f"Preferred location set to {loc_data.get('name', location_id)}")
        
        return {
            "success": True,
            "preferred_location_id": location_id,
            "location_name": loc_data.get("name"),
            "message": f"Preferred location set to {loc_data.get('name', location_id)}"
        }

    @mcp.tool()
    @translate_errors
    async def get_preferred_location(ctx: Context = None) -> Dict[str, Any]:
        """
        Get the currently set preferred store location.

        No preferred location is a normal result (preferred_location_id null),
        not an error.
        
        Returns:
            Dictionary containing the preferred location information
        """
        preferred_location_id = get_preferred_location_id()
        
        if not preferred_location_id:
            return {
                "success": True,
                "preferred_location_id": None,
                "message": "No preferred location set. Use set_preferred_location to set one."
            }
        
        if ctx:
            await ctx.info(f"Getting preferred location details for {preferred_location_id}")
        
        client = get_client_credentials_client()
        
        try:
            location_details = client.location.get_location(preferred_location_id)
        except NotFoundError as e:
            raise KrogerToolError(
                "not_found",
                f"The saved preferred location {preferred_location_id} no longer exists.",
                next_step="Find a store with search_locations and save it with set_preferred_location.",
                details={"preferred_location_id": preferred_location_id, "correlation_id": e.correlation_id},
            ) from e
        loc_data = _location_data(location_details, preferred_location_id)
        
        return {
            "success": True,
            "preferred_location_id": preferred_location_id,
            "location_details": {
                "name": loc_data.get("name"),
                "chain": loc_data.get("chain"),
                "phone": loc_data.get("phone"),
                "address": loc_data.get("address", {})
            }
        }

    @mcp.tool()
    @translate_errors
    async def check_location_exists(
        location_id: LocationId,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Check if a location exists in the Kroger system.
        
        Args:
            location_id: The unique identifier for the store location
        
        Returns:
            Dictionary indicating whether the location exists
        """
        if ctx:
            await ctx.info(f"Checking if location {location_id} exists")
        
        client = get_client_credentials_client()
        exists = client.location.location_exists(location_id)
        
        return {
            "success": True,
            "location_id": location_id,
            "exists": exists,
            "message": f"Location {location_id} {'exists' if exists else 'does not exist'}"
        }
