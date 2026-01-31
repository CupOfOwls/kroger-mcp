"""
Product search and management tools for Kroger MCP server
"""

import asyncio
from typing import Dict, Any, Optional, Literal, List
from pydantic import Field
from fastmcp import Context, Image
import requests

from .shared import (
    get_client_credentials_client,
    get_preferred_location_id,
    format_currency
)
from ..analytics.favorites import get_all_favorite_product_ids


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
        search_term: str | List[str] = Field(
            description="Search term or list of terms (e.g., 'milk' or ['milk', 'bread'])"
        ),
        location_id: Optional[str] = None,
        limit: int = Field(
            default=10, ge=1, le=50, description="Results per term (1-50)"
        ),
        fulfillment: Optional[Literal["csp", "delivery", "pickup"]] = None,
        brand: Optional[str] = None,
        prioritize_favorites: bool = Field(
            default=True, description="Boost favorite items to top of results"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Search for products at a Kroger store. Accepts single term or list of terms.

        When multiple terms are provided, searches execute in parallel for efficiency.
        Each product includes an 'is_favorite' field.

        Args:
            search_term: Single term ("milk") or list (["milk", "bread", "eggs"])
            location_id: Store location ID (uses preferred if not provided)
            limit: Results per search term (1-50)
            fulfillment: Filter by fulfillment (csp, delivery, pickup)
            brand: Filter by brand name
            prioritize_favorites: Boost favorites to top (default: True)

        Returns:
            Single term: {success, count, data: [...]}
            Multiple terms: {success, results: {term: {count, data}, ...}}
        """
        # Use preferred location if none provided
        if not location_id:
            location_id = get_preferred_location_id()
            if not location_id:
                return {
                    "success": False,
                    "error": "No location_id provided and no preferred location set. "
                    "Use set_preferred_location first.",
                }

        # Normalize to list
        terms = [search_term] if isinstance(search_term, str) else search_term
        is_batch = len(terms) > 1

        if len(terms) > 10:
            return {
                "success": False,
                "error": f"Too many search terms ({len(terms)}). Maximum is 10.",
            }

        if ctx:
            if is_batch:
                await ctx.info(f"Searching {len(terms)} terms at location {location_id}")
            else:
                await ctx.info(f"Searching for '{terms[0]}' at location {location_id}")

        client = get_client_credentials_client()

        # Get favorite IDs once
        favorite_ids = set()
        if prioritize_favorites:
            try:
                favorite_ids = get_all_favorite_product_ids()
            except Exception:
                pass

        def format_product(product: Dict) -> Dict:
            """Format a single product."""
            fp = {
                "product_id": product.get("productId"),
                "upc": product.get("upc"),
                "description": product.get("description"),
                "brand": product.get("brand"),
                "categories": product.get("categories", []),
                "country_origin": product.get("countryOrigin"),
                "temperature": product.get("temperature", {}),
            }

            if "items" in product and product["items"]:
                item = product["items"][0]
                fp["item"] = {
                    "size": item.get("size"),
                    "sold_by": item.get("soldBy"),
                    "inventory": item.get("inventory", {}),
                    "fulfillment": item.get("fulfillment", {}),
                }
                if "price" in item:
                    price = item["price"]
                    fp["pricing"] = {
                        "regular_price": price.get("regular"),
                        "sale_price": price.get("promo"),
                        "regular_per_unit": price.get("regularPerUnitEstimate"),
                        "formatted_regular": format_currency(price.get("regular")),
                        "formatted_sale": format_currency(price.get("promo")),
                        "on_sale": price.get("promo") is not None
                        and price.get("promo") < price.get("regular", float("inf")),
                    }

            if "aisleLocations" in product:
                fp["aisle_locations"] = [
                    {
                        "description": a.get("description"),
                        "number": a.get("number"),
                        "side": a.get("side"),
                        "shelf_number": a.get("shelfNumber"),
                    }
                    for a in product["aisleLocations"]
                ]

            if "images" in product and product["images"]:
                fp["images"] = [
                    {
                        "perspective": img.get("perspective"),
                        "url": img["sizes"][0].get("url") if img.get("sizes") else None,
                        "size": img["sizes"][0].get("size") if img.get("sizes") else None,
                    }
                    for img in product["images"]
                    if img.get("sizes")
                ]

            return fp

        def mark_and_sort_favorites(products: List[Dict]) -> tuple[List[Dict], int]:
            """Mark favorites and sort them to top."""
            fav_count = 0
            for p in products:
                is_fav = p.get("product_id") in favorite_ids
                p["is_favorite"] = is_fav
                if is_fav:
                    fav_count += 1

            if prioritize_favorites and fav_count > 0:
                favs = [p for p in products if p["is_favorite"]]
                non_favs = [p for p in products if not p["is_favorite"]]
                products = favs + non_favs

            return products, fav_count

        async def search_single(term: str) -> tuple[str, Dict[str, Any]]:
            """Search for a single term."""
            try:
                products = client.product.search_products(
                    term=term,
                    location_id=location_id,
                    limit=limit,
                    fulfillment=fulfillment,
                    brand=brand,
                )

                if not products or "data" not in products or not products["data"]:
                    return (term, {"count": 0, "favorites_count": 0, "data": []})

                formatted = [format_product(p) for p in products["data"]]
                formatted, fav_count = mark_and_sort_favorites(formatted)

                return (
                    term,
                    {"count": len(formatted), "favorites_count": fav_count, "data": formatted},
                )
            except Exception as e:
                return (term, {"error": str(e), "count": 0, "data": []})

        try:
            # Execute searches (parallel if batch)
            tasks = [search_single(t) for t in terms]
            results_list = await asyncio.gather(*tasks)

            if is_batch:
                # Batch mode: return grouped results
                results = {}
                errors = {}
                total_results = 0
                total_favorites = 0

                for term, result in results_list:
                    if "error" in result:
                        errors[term] = result["error"]
                    else:
                        results[term] = result
                        total_results += result["count"]
                        total_favorites += result["favorites_count"]

                if ctx:
                    await ctx.info(
                        f"Found {total_results} products ({total_favorites} favorites)"
                    )

                return {
                    "success": len(errors) < len(terms),
                    "location_id": location_id,
                    "terms_searched": len(terms),
                    "total_results": total_results,
                    "total_favorites": total_favorites,
                    "results": results,
                    "errors": errors if errors else None,
                }
            else:
                # Single mode: return flat response (backwards compatible)
                term, result = results_list[0]
                if "error" in result:
                    return {"success": False, "error": result["error"], "data": []}

                if ctx:
                    await ctx.info(
                        f"Found {result['count']} products ({result['favorites_count']} favorites)"
                    )

                return {
                    "success": True,
                    "search_params": {
                        "search_term": term,
                        "location_id": location_id,
                        "limit": limit,
                        "fulfillment": fulfillment,
                        "brand": brand,
                        "prioritize_favorites": prioritize_favorites,
                    },
                    "count": result["count"],
                    "favorites_count": result["favorites_count"],
                    "data": result["data"],
                }

        except Exception as e:
            if ctx:
                await ctx.error(f"Error searching products: {str(e)}")
            return {"success": False, "error": str(e), "data": []}

    @mcp.tool()
    async def get_product_details(
        product_id: str | List[str] = Field(
            description="Product ID or list of IDs (e.g., '001' or ['001', '002'])"
        ),
        location_id: Optional[str] = None,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Get detailed information about products. Accepts single ID or list.

        When multiple IDs are provided, fetches execute in parallel.

        Args:
            product_id: Single ID ("001") or list (["001", "002", "003"])
            location_id: Store location ID (uses preferred if not provided)

        Returns:
            Single ID: {success, product_id, description, pricing, ...}
            Multiple IDs: {success, results: {id: {...}, ...}, errors: {...}}
        """
        # Use preferred location if none provided
        if not location_id:
            location_id = get_preferred_location_id()
            if not location_id:
                return {
                    "success": False,
                    "error": "No location_id provided and no preferred location set. "
                    "Use set_preferred_location first.",
                }

        # Normalize to list
        ids = [product_id] if isinstance(product_id, str) else product_id
        is_batch = len(ids) > 1

        if len(ids) > 20:
            return {
                "success": False,
                "error": f"Too many product IDs ({len(ids)}). Maximum is 20.",
            }

        if ctx:
            if is_batch:
                await ctx.info(f"Getting details for {len(ids)} products")
            else:
                await ctx.info(f"Getting details for product {ids[0]}")

        client = get_client_credentials_client()

        def format_details(product: Dict) -> Dict:
            """Format product details."""
            result = {
                "product_id": product.get("productId"),
                "upc": product.get("upc"),
                "description": product.get("description"),
                "brand": product.get("brand"),
                "categories": product.get("categories", []),
                "country_origin": product.get("countryOrigin"),
                "temperature": product.get("temperature", {}),
                "location_id": location_id,
            }

            if "items" in product and product["items"]:
                item = product["items"][0]
                result["item_details"] = {
                    "size": item.get("size"),
                    "sold_by": item.get("soldBy"),
                    "inventory": item.get("inventory", {}),
                    "fulfillment": item.get("fulfillment", {}),
                }
                if "price" in item:
                    price = item["price"]
                    result["pricing"] = {
                        "regular_price": price.get("regular"),
                        "sale_price": price.get("promo"),
                        "regular_per_unit": price.get("regularPerUnitEstimate"),
                        "formatted_regular": format_currency(price.get("regular")),
                        "formatted_sale": format_currency(price.get("promo")),
                        "on_sale": price.get("promo") is not None
                        and price.get("promo") < price.get("regular", float("inf")),
                        "savings": (
                            price.get("regular", 0)
                            - price.get("promo", price.get("regular", 0))
                            if price.get("promo")
                            else 0
                        ),
                    }

            if "aisleLocations" in product:
                result["aisle_locations"] = [
                    {
                        "description": a.get("description"),
                        "aisle_number": a.get("number"),
                        "side": a.get("side"),
                        "shelf_number": a.get("shelfNumber"),
                    }
                    for a in product["aisleLocations"]
                ]

            if "images" in product and product["images"]:
                result["images"] = [
                    {
                        "perspective": img.get("perspective"),
                        "sizes": [
                            {"size": s.get("size"), "url": s.get("url")}
                            for s in img.get("sizes", [])
                        ],
                    }
                    for img in product["images"]
                ]

            return result

        async def fetch_single(pid: str) -> tuple[str, Dict[str, Any]]:
            """Fetch details for a single product."""
            try:
                product_details = client.product.get_product(
                    product_id=pid, location_id=location_id
                )
                if not product_details or "data" not in product_details:
                    return (pid, {"error": f"Product {pid} not found"})
                return (pid, format_details(product_details["data"]))
            except Exception as e:
                return (pid, {"error": str(e)})

        try:
            tasks = [fetch_single(pid) for pid in ids]
            results_list = await asyncio.gather(*tasks)

            if is_batch:
                # Batch mode: return grouped results
                results = {}
                errors = {}
                for pid, result in results_list:
                    if "error" in result:
                        errors[pid] = result["error"]
                    else:
                        results[pid] = result

                if ctx:
                    await ctx.info(
                        f"Retrieved {len(results)} products, {len(errors)} errors"
                    )

                return {
                    "success": len(errors) < len(ids),
                    "location_id": location_id,
                    "count": len(results),
                    "results": results,
                    "errors": errors if errors else None,
                }
            else:
                # Single mode: return flat response (backwards compatible)
                pid, result = results_list[0]
                if "error" in result:
                    return {"success": False, "message": result["error"]}
                return {"success": True, **result}

        except Exception as e:
            if ctx:
                await ctx.error(f"Error getting product details: {str(e)}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def search_products_by_id(
        product_id: str,
        location_id: Optional[str] = None,
        prioritize_favorites: bool = Field(
            default=True, description="Boost favorite items to top of results"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Search for products by their specific product ID.

        Each product includes an 'is_favorite' field indicating if it's
        in any of your favorite lists.

        Args:
            product_id: The product ID to search for
            location_id: Store location ID (uses preferred location if not provided)
            prioritize_favorites: Boost favorite items to top of results (default: True)

        Returns:
            Dictionary containing matching products with favorite status
        """
        # Use preferred location if none provided
        if not location_id:
            location_id = get_preferred_location_id()
            if not location_id:
                return {
                    "success": False,
                    "error": "No location_id provided and no preferred location set. "
                    "Use set_preferred_location first.",
                }

        if ctx:
            await ctx.info(
                f"Searching for products with ID '{product_id}' at location {location_id}"
            )

        client = get_client_credentials_client()

        try:
            products = client.product.search_products(
                product_id=product_id, location_id=location_id
            )

            if not products or "data" not in products or not products["data"]:
                return {
                    "success": False,
                    "message": f"No products found with ID '{product_id}'",
                    "data": [],
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
                }

                if (
                    "items" in product
                    and product["items"]
                    and "price" in product["items"][0]
                ):
                    price = product["items"][0]["price"]
                    formatted_product["pricing"] = {
                        "regular_price": price.get("regular"),
                        "sale_price": price.get("promo"),
                        "formatted_regular": format_currency(price.get("regular")),
                        "formatted_sale": format_currency(price.get("promo")),
                    }

                formatted_products.append(formatted_product)

            # Get favorite product IDs
            favorite_ids = set()
            if prioritize_favorites:
                try:
                    favorite_ids = get_all_favorite_product_ids()
                except Exception:
                    pass

            # Mark and sort favorites
            favorites_count = 0
            for product in formatted_products:
                is_fav = product.get("product_id") in favorite_ids
                product["is_favorite"] = is_fav
                if is_fav:
                    favorites_count += 1

            if prioritize_favorites and favorites_count > 0:
                favorite_products = [p for p in formatted_products if p["is_favorite"]]
                non_favorite_products = [
                    p for p in formatted_products if not p["is_favorite"]
                ]
                formatted_products = favorite_products + non_favorite_products

            if ctx:
                await ctx.info(
                    f"Found {len(formatted_products)} products ({favorites_count} favorites)"
                )

            return {
                "success": True,
                "search_params": {
                    "product_id": product_id,
                    "location_id": location_id,
                    "prioritize_favorites": prioritize_favorites,
                },
                "count": len(formatted_products),
                "favorites_count": favorites_count,
                "data": formatted_products,
            }

        except Exception as e:
            if ctx:
                await ctx.error(f"Error searching products by ID: {str(e)}")
            return {"success": False, "error": str(e), "data": []}
