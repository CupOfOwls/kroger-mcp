"""
Chain and department information tools for Kroger MCP server
"""

from typing import Dict, Any
from fastmcp import Context

from .shared import get_client_credentials_client


def register_tools(mcp):
    """Register information-related tools with the FastMCP server"""
    
    @mcp.tool()
    async def list_chains(ctx: Context = None) -> Dict[str, Any]:
        """
        Get a list of all Kroger-owned chains.
        
        Returns:
            Dictionary containing chain information
        """
        if ctx:
            await ctx.info("Getting list of Kroger chains")
        
        client = get_client_credentials_client()
        
        try:
            chains = client.location.list_chains()
            
            if not chains or "data" not in chains or not chains["data"]:
                return {
                    "success": False,
                    "message": "No chains found",
                    "data": []
                }
            
            # Format chain data
            formatted_chains = [
                {
                    "name": chain.get("name"),
                    "division_numbers": chain.get("divisionNumbers", [])
                }
                for chain in chains["data"]
            ]
            
            if ctx:
                await ctx.info(f"Found {len(formatted_chains)} chains")
            
            return {
                "success": True,
                "count": len(formatted_chains),
                "data": formatted_chains
            }
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error listing chains: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "data": []
            }

    @mcp.tool()
    async def get_chain_details(
        chain_name: str,
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
        
        try:
            chain_details = client.location.get_chain(chain_name)
            
            if not chain_details or "data" not in chain_details:
                return {
                    "success": False,
                    "message": f"Chain '{chain_name}' not found"
                }
            
            chain = chain_details["data"]
            
            return {
                "success": True,
                "name": chain.get("name"),
                "division_numbers": chain.get("divisionNumbers", [])
            }
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error getting chain details: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    @mcp.tool()
    async def check_chain_exists(
        chain_name: str,
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
        
        try:
            exists = client.location.chain_exists(chain_name)
            
            return {
                "success": True,
                "chain_name": chain_name,
                "exists": exists,
                "message": f"Chain '{chain_name}' {'exists' if exists else 'does not exist'}"
            }
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error checking chain existence: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    @mcp.tool()
    async def list_departments(ctx: Context = None) -> Dict[str, Any]:
        """
        Get a list of all available departments in Kroger stores.
        
        Returns:
            Dictionary containing department information
        """
        if ctx:
            await ctx.info("Getting list of departments")
        
        client = get_client_credentials_client()
        
        try:
            departments = client.location.list_departments()
            
            if not departments or "data" not in departments or not departments["data"]:
                return {
                    "success": False,
                    "message": "No departments found",
                    "data": []
                }
            
            # Format department data
            formatted_departments = [
                {
                    "department_id": dept.get("departmentId"),
                    "name": dept.get("name")
                }
                for dept in departments["data"]
            ]
            
            if ctx:
                await ctx.info(f"Found {len(formatted_departments)} departments")
            
            return {
                "success": True,
                "count": len(formatted_departments),
                "data": formatted_departments
            }
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error listing departments: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "data": []
            }

    @mcp.tool()
    async def get_department_details(
        department_id: str,
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
        
        try:
            dept_details = client.location.get_department(department_id)
            
            if not dept_details or "data" not in dept_details:
                return {
                    "success": False,
                    "message": f"Department '{department_id}' not found"
                }
            
            dept = dept_details["data"]
            
            return {
                "success": True,
                "department_id": dept.get("departmentId"),
                "name": dept.get("name")
            }
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error getting department details: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    @mcp.tool()
    async def check_department_exists(
        department_id: str,
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
        
        try:
            exists = client.location.department_exists(department_id)
            
            return {
                "success": True,
                "department_id": department_id,
                "exists": exists,
                "message": f"Department '{department_id}' {'exists' if exists else 'does not exist'}"
            }
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error checking department existence: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
