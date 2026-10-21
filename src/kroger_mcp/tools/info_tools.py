"""
Chain and department information tools for Kroger MCP server
"""

from typing import Annotated, Any, Dict, Optional
from pydantic import Field
from fastmcp import Context

from ..errors import KrogerToolError, translate_errors
from .params import DepartmentId
from .shared import get_client_credentials_client

ChainName = Annotated[str, Field(min_length=1, description="Chain name, for example Kroger or Ralphs. See list_chains.")]


def _data(response: Optional[Dict[str, Any]], what: str, expected: type) -> Any:
    """The data member of a Locations API response

    Raises:
        KrogerToolError: unexpected_response, if it is missing or has the wrong type
    """
    data = (response or {}).get("data")
    if not isinstance(data, expected):
        raise KrogerToolError(
            "unexpected_response",
            f"The Kroger Locations API answered without the {what} data it documents.",
            details={"response_body": response},
        )
    return data


def register_tools(mcp):
    """Register information-related tools with the FastMCP server"""
    
    @mcp.tool()
    @translate_errors
    async def list_chains(ctx: Context = None) -> Dict[str, Any]:
        """
        Get a list of all Kroger-owned chains.
        
        Returns:
            Dictionary containing chain information
        """
        if ctx:
            await ctx.info("Getting list of Kroger chains")
        
        client = get_client_credentials_client()
        chains = _data(client.location.list_chains(), "chain list", list)
        
        # Format chain data
        formatted_chains = [
            {
                "name": chain.get("name"),
                "division_numbers": chain.get("divisionNumbers", [])
            }
            for chain in chains
        ]
        
        if ctx:
            await ctx.info(f"Found {len(formatted_chains)} chains")
        
        return {
            "success": True,
            "count": len(formatted_chains),
            "data": formatted_chains
        }

    @mcp.tool()
    @translate_errors
    async def get_chain_details(
        chain_name: ChainName,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get detailed information about a specific Kroger chain.
        
        Args:
            chain_name: Name of the chain to get details for
        
        Returns:
            Dictionary containing chain details
        """
        if ctx:
            await ctx.info(f"Getting details for chain: {chain_name}")
        
        client = get_client_credentials_client()
        # An unknown chain raises NotFoundError
        chain = _data(client.location.get_chain(chain_name), f"'{chain_name}' chain", dict)
        
        return {
            "success": True,
            "name": chain.get("name"),
            "division_numbers": chain.get("divisionNumbers", [])
        }

    @mcp.tool()
    @translate_errors
    async def check_chain_exists(
        chain_name: ChainName,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Check if a chain exists in the Kroger system.
        
        Args:
            chain_name: Name of the chain to check
        
        Returns:
            Dictionary indicating whether the chain exists
        """
        if ctx:
            await ctx.info(f"Checking if chain '{chain_name}' exists")
        
        client = get_client_credentials_client()
        exists = client.location.chain_exists(chain_name)
        
        return {
            "success": True,
            "chain_name": chain_name,
            "exists": exists,
            "message": f"Chain '{chain_name}' {'exists' if exists else 'does not exist'}"
        }

    @mcp.tool()
    @translate_errors
    async def list_departments(ctx: Context = None) -> Dict[str, Any]:
        """
        Get a list of all available departments in Kroger stores.
        
        Returns:
            Dictionary containing department information
        """
        if ctx:
            await ctx.info("Getting list of departments")
        
        client = get_client_credentials_client()
        departments = _data(client.location.list_departments(), "department list", list)
        
        # Format department data
        formatted_departments = [
            {
                "department_id": dept.get("departmentId"),
                "name": dept.get("name")
            }
            for dept in departments
        ]
        
        if ctx:
            await ctx.info(f"Found {len(formatted_departments)} departments")
        
        return {
            "success": True,
            "count": len(formatted_departments),
            "data": formatted_departments
        }

    @mcp.tool()
    @translate_errors
    async def get_department_details(
        department_id: DepartmentId,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get detailed information about a specific department.
        
        Args:
            department_id: The unique identifier for the department
        
        Returns:
            Dictionary containing department details
        """
        if ctx:
            await ctx.info(f"Getting details for department: {department_id}")
        
        client = get_client_credentials_client()
        # An unknown department raises NotFoundError
        dept = _data(client.location.get_department(department_id), f"'{department_id}' department", dict)
        
        return {
            "success": True,
            "department_id": dept.get("departmentId"),
            "name": dept.get("name")
        }

    @mcp.tool()
    @translate_errors
    async def check_department_exists(
        department_id: DepartmentId,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Check if a department exists in the Kroger system.
        
        Args:
            department_id: The department ID to check
        
        Returns:
            Dictionary indicating whether the department exists
        """
        if ctx:
            await ctx.info(f"Checking if department '{department_id}' exists")
        
        client = get_client_credentials_client()
        exists = client.location.department_exists(department_id)
        
        return {
            "success": True,
            "department_id": department_id,
            "exists": exists,
            "message": f"Department '{department_id}' {'exists' if exists else 'does not exist'}"
        }
