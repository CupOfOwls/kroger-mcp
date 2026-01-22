"""
Product search and management tools for Kroger MCP server
"""

from typing import Dict, Any, Optional, Literal
from pydantic import Field
from fastmcp import Context, Image
import requests

from .shared import (
    get_client_credentials_client, 
    get_preferred_location_id,
    format_currency
)


def register_tools(mcp):
    """Register product-related tools with the FastMCP server"""
    
    @mcp.tool()
    async def get_product_images(
        product_id: str,
        perspective: str = "front",
        location_id: Optional[str] = None,
        ctx: Context = None
    ) -> Image:
        """
        Get an image for a specific product from the requested perspective.
        
        Use get_product_details first to see what perspectives are available (typically "front", "back", "left", "right").
        
        Args:
            product_id: The unique product identifier
            perspective: The image perspective to retrieve (default: "front")
            location_id: Store location ID (uses preferred if not provided)
        
        Returns:
            The product image from the requested perspective
        """
        # Use preferred location if none provided
        if not location_id:
            location_id = get_preferred_location_id()
            if not location_id:
                return {
                    "success": False,
                    "error": "No location_id provided and no preferred location set. Use set_preferred_location first."
                }
        
        if ctx:
            await ctx.info(f"Fetching images for product {product_id} at location {location_id}")
        
        client = get_client_credentials_client()
        
        try:
            # Get product details to extract image URLs
            product_details = client.product.get_product(
                product_id=product_id,
                location_id=location_id
            )
            
            if not product_details or "data" not in product_details:
                return {
                    "success": False,
                    "message": f"Product {product_id} not found"
                }
            
            product = product_details["data"]
            
            # Check if images are available
            if "images" not in product or not product["images"]:
                return {
                    "success": False,
                    "message": f"No images available for product {product_id}"
                }
            
            # Find the requested perspective image
            perspective_image = None
            available_perspectives = []
            
            for img_data in product["images"]:
                img_perspective = img_data.get("perspective", "unknown")
                available_perspectives.append(img_perspective)
                
                # Skip if not the requested perspective
                if img_perspective != perspective:
                    continue
                    
                if not img_data.get("sizes"):
                    continue
                
                # Find the best image size (prefer large, fallback to xlarge or other available)
                img_url = None
                size_preference = ["large", "xlarge", "medium", "small", "thumbnail"]
                
                # Create a map of available sizes for quick lookup
                available_sizes = {size.get("size"): size.get("url") for size in img_data.get("sizes", []) if size.get("size") and size.get("url")}
                
                # Select best size based on preference order
                for size in size_preference:
                    if size in available_sizes:
                        img_url = available_sizes[size]
                        break
                
                if img_url:
                    try:
                        if ctx:
                            await ctx.info(f"Downloading {perspective} image from {img_url}")
                        
                        # Download image
                        response = requests.get(img_url)
                        response.raise_for_status()
                        
                        # Create Image object
                        perspective_image = Image(
                            data=response.content,
                            format="jpeg"  # Kroger images are typically JPEG
                        )
                        break
                    except Exception as e:
                        if ctx:
                            await ctx.warning(f"Failed to download {perspective} image: {str(e)}")
            
            # If the requested perspective wasn't found
            if not perspective_image:
                available_str = ", ".join(available_perspectives) if available_perspectives else "none"
                return {
                    "success": False,
                    "message": f"No image found for perspective '{perspective}'. Available perspectives: {available_str}"
                }
            
            return perspective_image
        
        except Exception as e:
            if ctx:
                await ctx.error(f"Error getting product images: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    @mcp.tool()
    async def search_products(
        search_term: str,
        location_id: Optional[str] = None,
        limit: int = Field(default=10, ge=1, le=50, description="Number of results to return (1-50)"),
        fulfillment: Optional[Literal["csp", "delivery", "pickup"]] = None,
        brand: Optional[str] = None,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Search for products at a Kroger store.
        
        Args:
            search_term: Product search term (e.g., "milk", "bread", "organic apples")
            location_id: Store location ID (uses preferred location if not provided)
            limit: Number of results to return (1-50)
            fulfillment: Filter by fulfillment method (csp=curbside pickup, delivery, pickup)
            brand: Filter by brand name
        
        Returns:
            Dictionary containing product search results
        """
        # Use preferred location if none provided
        if not location_id:
            location_id = get_preferred_location_id()
            if not location_id:
                return {
                    "success": False,
                    "error": "No location_id provided and no preferred location set. Use set_preferred_location first."
                }
        
        if ctx:
            await ctx.info(f"Searching for '{search_term}' at location {location_id}")
        
        client = get_client_credentials_client()
        
        try:
            products = client.product.search_products(
                term=search_term,
                location_id=location_id,
                limit=limit,
                fulfillment=fulfillment,
                brand=brand
            )
            
            if not products or "data" not in products or not products["data"]:
                return {
                    "success": False,
                    "message": f"No products found matching '{search_term}'",
                    "data": []
                }
            
            # Format product data
            formatted_products = []
            for product in products["data"]:
                formatted_product = {
                    "product_id": product.get("productId"),
                    "upc": product.get("upc"),
                    "description": product.get("description"),
                    "brand": product.get("brand"),
                    "categories": product.get("categories", []),
                    "country_origin": product.get("countryOrigin"),
                    "temperature": product.get("temperature", {})
                }
                
                # Add item information (size, price, etc.)
                if "items" in product and product["items"]:
                    item = product["items"][0]
                    formatted_product["item"] = {
                        "size": item.get("size"),
                        "sold_by": item.get("soldBy"),
                        "inventory": item.get("inventory", {}),
                        "fulfillment": item.get("fulfillment", {})
                    }
                    
                    # Add pricing information
                    if "price" in item:
                        price = item["price"]
                        formatted_product["pricing"] = {
                            "regular_price": price.get("regular"),
                            "sale_price": price.get("promo"),
                            "regular_per_unit": price.get("regularPerUnitEstimate"),
                            "formatted_regular": format_currency(price.get("regular")),
                            "formatted_sale": format_currency(price.get("promo")),
                            "on_sale": price.get("promo") is not None and price.get("promo") < price.get("regular", float('inf'))
                        }
                
                # Add aisle information
                if "aisleLocations" in product:
                    formatted_product["aisle_locations"] = [
                        {
                            "description": aisle.get("description"),
                            "number": aisle.get("number"),
                            "side": aisle.get("side"),
                            "shelf_number": aisle.get("shelfNumber")
                        }
                        for aisle in product["aisleLocations"]
                    ]
                
                # Add image information
                if "images" in product and product["images"]:
                    formatted_product["images"] = [
                        {
                            "perspective": img.get("perspective"),
                            "url": img["sizes"][0].get("url") if img.get("sizes") else None,
                            "size": img["sizes"][0].get("size") if img.get("sizes") else None
                        }
                        for img in product["images"]
                        if img.get("sizes")
                    ]
                
                formatted_products.append(formatted_product)
            
            if ctx:
                await ctx.info(f"Found {len(formatted_products)} products")
            
            return {
                "success": True,
                "search_params": {
                    "search_term": search_term,
                    "location_id": location_id,
                    "limit": limit,
                    "fulfillment": fulfillment,
                    "brand": brand
                },
                "count": len(formatted_products),
                "data": formatted_products
            }
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error searching products: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "data": []
            }

    @mcp.tool()
    async def get_product_details(
        product_id: str,
        location_id: Optional[str] = None,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get detailed information about a specific product.
        
        Args:
            product_id: The unique product identifier
            location_id: Store location ID for pricing/availability (uses preferred if not provided)
        
        Returns:
            Dictionary containing detailed product information
        """
        # Use preferred location if none provided
        if not location_id:
            location_id = get_preferred_location_id()
            if not location_id:
                return {
                    "success": False,
                    "error": "No location_id provided and no preferred location set. Use set_preferred_location first."
                }
        
        if ctx:
            await ctx.info(f"Getting details for product {product_id} at location {location_id}")
        
        client = get_client_credentials_client()
        
        try:
            product_details = client.product.get_product(
                product_id=product_id,
                location_id=location_id
            )
            
            if not product_details or "data" not in product_details:
                return {
                    "success": False,
                    "message": f"Product {product_id} not found"
                }
            
            product = product_details["data"]
            
            # Format the detailed product information
            result = {
                "success": True,
                "product_id": product.get("productId"),
                "upc": product.get("upc"),
                "description": product.get("description"),
                "brand": product.get("brand"),
                "categories": product.get("categories", []),
                "country_origin": product.get("countryOrigin"),
                "temperature": product.get("temperature", {}),
                "location_id": location_id
            }
            
            # Add detailed item information
            if "items" in product and product["items"]:
                item = product["items"][0]
                result["item_details"] = {
                    "size": item.get("size"),
                    "sold_by": item.get("soldBy"),
                    "inventory": item.get("inventory", {}),
                    "fulfillment": item.get("fulfillment", {})
                }
                
                # Add detailed pricing
                if "price" in item:
                    price = item["price"]
                    result["pricing"] = {
                        "regular_price": price.get("regular"),
                        "sale_price": price.get("promo"),
                        "regular_per_unit": price.get("regularPerUnitEstimate"),
                        "formatted_regular": format_currency(price.get("regular")),
                        "formatted_sale": format_currency(price.get("promo")),
                        "on_sale": price.get("promo") is not None and price.get("promo") < price.get("regular", float('inf')),
                        "savings": price.get("regular", 0) - price.get("promo", price.get("regular", 0)) if price.get("promo") else 0
                    }
            
            # Add aisle locations
            if "aisleLocations" in product:
                result["aisle_locations"] = [
                    {
                        "description": aisle.get("description"),
                        "aisle_number": aisle.get("number"),
                        "side": aisle.get("side"),
                        "shelf_number": aisle.get("shelfNumber")
                    }
                    for aisle in product["aisleLocations"]
                ]
            
            # Add images
            if "images" in product and product["images"]:
                result["images"] = [
                    {
                        "perspective": img.get("perspective"),
                        "sizes": [
                            {
                                "size": size.get("size"),
                                "url": size.get("url")
                            }
                            for size in img.get("sizes", [])
                        ]
                    }
                    for img in product["images"]
                ]
            
            return result
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error getting product details: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    @mcp.tool()
    async def search_products_by_id(
        product_id: str,
        location_id: Optional[str] = None,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Search for products by their specific product ID.
        
        Args:
            product_id: The product ID to search for
            location_id: Store location ID (uses preferred location if not provided)
        
        Returns:
            Dictionary containing matching products
        """
        # Use preferred location if none provided
        if not location_id:
            location_id = get_preferred_location_id()
            if not location_id:
                return {
                    "success": False,
                    "error": "No location_id provided and no preferred location set. Use set_preferred_location first."
                }
        
        if ctx:
            await ctx.info(f"Searching for products with ID '{product_id}' at location {location_id}")
        
        client = get_client_credentials_client()
        
        try:
            products = client.product.search_products(
                product_id=product_id,
                location_id=location_id
            )
            
            if not products or "data" not in products or not products["data"]:
                return {
                    "success": False,
                    "message": f"No products found with ID '{product_id}'",
                    "data": []
                }
            
            # Format product data (similar to search_products but simpler)
            formatted_products = []
            for product in products["data"]:
                formatted_product = {
                    "product_id": product.get("productId"),
                    "upc": product.get("upc"),
                    "description": product.get("description"),
                    "brand": product.get("brand"),
                    "categories": product.get("categories", [])
                }
                
                # Add basic pricing if available
                if "items" in product and product["items"] and "price" in product["items"][0]:
                    price = product["items"][0]["price"]
                    formatted_product["pricing"] = {
                        "regular_price": price.get("regular"),
                        "sale_price": price.get("promo"),
                        "formatted_regular": format_currency(price.get("regular")),
                        "formatted_sale": format_currency(price.get("promo"))
                    }
                
                formatted_products.append(formatted_product)
            
            if ctx:
                await ctx.info(f"Found {len(formatted_products)} products with ID '{product_id}'")
            
            return {
                "success": True,
                "search_params": {
                    "product_id": product_id,
                    "location_id": location_id
                },
                "count": len(formatted_products),
                "data": formatted_products
            }
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error searching products by ID: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "data": []
            }
