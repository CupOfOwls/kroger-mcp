"""
Location management tools for Kroger MCP server
"""

from typing import Dict, List, Any, Optional
from pydantic import Field
from fastmcp import Context

from .shared import (
    get_client_credentials_client, 
    get_preferred_location_id, 
    set_preferred_location_id,
    get_default_zip_code
)


def register_tools(mcp):
    """Register location-related tools with the FastMCP server"""
    
    @mcp.tool()
    async def search_locations(
        zip_code: Optional[str] = None,
        radius_in_miles: int = Field(default=10, ge=1, le=100, description="Search radius in miles (1-100)"),
        limit: int = Field(default=10, ge=1, le=200, description="Number of results to return (1-200)"),
        chain: Optional[str] = None,
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
            zip_code = get_default_zip_code()
        
        client = get_client_credentials_client()
        
        try:
            locations = client.location.search_locations(
                zip_code=zip_code,
                radius_in_miles=radius_in_miles,
                limit=limit,
                chain=chain
            )
            
            if not locations or "data" not in locations or not locations["data"]:
                return {
                    "success": False,
                    "message": f"No locations found near zip code {zip_code}",
                    "data": []
                }
            
            # Format location data for easier consumption
            formatted_locations = []
            for loc in locations["data"]:
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
            
            return {
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
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error searching locations: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "data": []
            }

    @mcp.tool()
    async def get_user_zip_code() -> Dict[str, Any]:
        """
        Returns user zip code, it is anticipated that by exposing this to the LLM it will choose to use it
        rather than generating a zip code based on system data.

        Args: 
            N/A
        Returns:
            Dictionary containing user Zip Code
        """
        zip_code = get_default_zip_code()
        # And thats literally it!
        user_zip_dict = {"user_zip_code": zip_code}
        return user_zip_dict


    @mcp.tool()
    async def get_location_details(
        location_id: str,
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
        
        try:
            location_details = client.location.get_location(location_id)
            
            if not location_details or "data" not in location_details:
                return {
                    "success": False,
                    "message": f"Location {location_id} not found"
                }
            
            loc = location_details["data"]
            
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
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error getting location details: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    @mcp.tool()
    async def set_preferred_location(
        location_id: str,
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
        
        # Verify the location exists
        client = get_client_credentials_client()
        
        try:
            exists = client.location.location_exists(location_id)
            if not exists:
                return {
                    "success": False,
                    "error": f"Location {location_id} does not exist"
                }
            
            # Get location details for confirmation
            location_details = client.location.get_location(location_id)
            loc_data = location_details.get("data", {})
            
            set_preferred_location_id(location_id)
            
            if ctx:
                await ctx.info(f"Preferred location set to {loc_data.get('name', location_id)}")
            
            return {
                "success": True,
                "preferred_location_id": location_id,
                "location_name": loc_data.get("name"),
                "message": f"Preferred location set to {loc_data.get('name', location_id)}"
            }
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error setting preferred location: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    @mcp.tool()
    async def get_preferred_location(ctx: Context = None) -> Dict[str, Any]:
        """
        Get the currently set preferred store location.
        
        Returns:
            Dictionary containing the preferred location information
        """
        preferred_location_id = get_preferred_location_id()
        
        if not preferred_location_id:
            return {
                "success": False,
                "message": "No preferred location set. Use set_preferred_location to set one."
            }
        
        if ctx:
            await ctx.info(f"Getting preferred location details for {preferred_location_id}")
        
        # Get location details
        client = get_client_credentials_client()
        
        try:
            location_details = client.location.get_location(preferred_location_id)
            loc_data = location_details.get("data", {})
            
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
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error getting preferred location details: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "preferred_location_id": preferred_location_id
            }

    @mcp.tool()
    async def check_location_exists(
        location_id: str,
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
        
        try:
            exists = client.location.location_exists(location_id)
            
            return {
                "success": True,
                "location_id": location_id,
                "exists": exists,
                "message": f"Location {location_id} {'exists' if exists else 'does not exist'}"
            }
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error checking location existence: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
