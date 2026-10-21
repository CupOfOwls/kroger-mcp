"""
Product search and management tools for Kroger MCP server
"""

from typing import Annotated, Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from fastmcp import Context
from fastmcp.utilities.types import Image
import requests

from kroger_api import validation
from kroger_api.errors import (
    APIConnectionError,
    BadRequestError,
    InternalServerError,
    InvalidResponseError,
    KrogerAPIError,
    NotFoundError,
)

from ..errors import KrogerToolError, translate_errors
from .params import Brand, Fulfillment, OptionalLocationId, ProductId, ProductLimit, SearchTerm
from .shared import (
    get_client_credentials_client, 
    get_preferred_location_id,
    resolve_location_id,
    format_currency
)

# Seconds to wait for a product image download
IMAGE_TIMEOUT = 30

# Errors that concern one search of a bulk search. Others, such as a rate
# limit or rejected credentials, would fail every search, so they end the call.
_PER_SEARCH_ERRORS = (BadRequestError, NotFoundError, InternalServerError, InvalidResponseError, APIConnectionError)


class ProductSearch(BaseModel):
    """One search of a bulk_search_products call"""

    model_config = ConfigDict(extra="forbid")

    term: SearchTerm
    limit: ProductLimit = 10
    fulfillment: Fulfillment = None
    brand: Brand = None


# Raw product keys the formatters transform into their own structure.
# Anything outside this set is passed through untouched under
# "additional_info" so new API fields are never silently dropped.
_FORMATTED_KEYS = {
    "productId", "upc", "description", "brand", "categories", "countryOrigin",
    "temperature", "items", "aisleLocations", "images",
    "allergens", "nutritionInformation", "warnings",
}


def _add_extended_attributes(formatted: Dict[str, Any], product: Dict[str, Any]) -> None:
    """Add nutrition/allergen data (Products API 1.3.0+) and pass through
    any remaining fields the formatter does not model."""
    if product.get("allergens"):
        formatted["allergens"] = [
            {
                "name": a.get("name"),
                "level_of_containment": a.get("levelOfContainmentName")
            }
            for a in product["allergens"] if isinstance(a, dict)
        ]

    nutrition = product.get("nutritionInformation")
    if isinstance(nutrition, list):
        nutrition = nutrition[0] if nutrition else None
    if isinstance(nutrition, dict):
        serving = nutrition.get("servingSize") or {}
        serving_unit = serving.get("unitOfMeasure") or {}
        formatted["nutrition"] = {
            "ingredient_statement": nutrition.get("ingredientStatement"),
            "serving_size": (
                f"{serving.get('quantity')} {serving_unit.get('abbreviation') or serving_unit.get('name') or ''}".strip()
                if serving.get("quantity") is not None else None
            ),
            "servings_per_package": (nutrition.get("servingsPerPackage") or {}).get("value"),
            "nutritional_rating": nutrition.get("nutritionalRating"),
            "nutrients": [
                {
                    "name": n.get("displayName") or n.get("description"),
                    "quantity": n.get("quantity"),
                    "unit": (n.get("unitOfMeasure") or {}).get("abbreviation")
                            or (n.get("unitOfMeasure") or {}).get("name"),
                    "percent_daily_intake": n.get("percentDailyIntake")
                }
                for n in nutrition.get("nutrients", []) if isinstance(n, dict)
            ]
        }

    if product.get("warnings"):
        # The API often repeats the same warning text; keep unique lines in order
        seen = set()
        formatted["warnings"] = [
            line for line in str(product["warnings"]).splitlines()
            if line.strip() and not (line in seen or seen.add(line))
        ]

    additional = {
        k: v for k, v in product.items()
        if k not in _FORMATTED_KEYS and v not in (None, "", [], {})
    }
    if additional:
        formatted["additional_info"] = additional


def _format_product(product: Dict[str, Any], include_images: bool = True) -> Dict[str, Any]:
    """Format a raw Kroger product into a consistent structure."""
    formatted = {
        "product_id": product.get("productId"),
        "upc": product.get("upc"),
        "description": product.get("description"),
        "brand": product.get("brand"),
        "categories": product.get("categories", []),
        "country_origin": product.get("countryOrigin"),
        "temperature": product.get("temperature", {})
    }

    if "items" in product and product["items"]:
        item = product["items"][0]
        formatted["item"] = {
            "size": item.get("size"),
            "sold_by": item.get("soldBy"),
            "inventory": item.get("inventory", {}),
            "fulfillment": item.get("fulfillment", {})
        }

        if "price" in item:
            price = item["price"]
            formatted["pricing"] = {
                "regular_price": price.get("regular"),
                "sale_price": price.get("promo"),
                "regular_per_unit": price.get("regularPerUnitEstimate"),
                "formatted_regular": format_currency(price.get("regular")),
                "formatted_sale": format_currency(price.get("promo")),
                "on_sale": price.get("promo") is not None and price.get("promo") < price.get("regular", float('inf'))
            }

    if "aisleLocations" in product:
        formatted["aisle_locations"] = [
            {
                "description": aisle.get("description"),
                "number": aisle.get("number"),
                "side": aisle.get("side"),
                "shelf_number": aisle.get("shelfNumber")
            }
            for aisle in product["aisleLocations"]
        ]

    if include_images and "images" in product and product["images"]:
        formatted["images"] = [
            {
                "perspective": img.get("perspective"),
                "url": img["sizes"][0].get("url") if img.get("sizes") else None,
                "size": img["sizes"][0].get("size") if img.get("sizes") else None
            }
            for img in product["images"]
            if img.get("sizes")
        ]

    _add_extended_attributes(formatted, product)

    return formatted


def _api_warnings(response: Optional[Dict[str, Any]]) -> Optional[List[str]]:
    """Warnings the Products API puts in meta.warnings, such as product IDs it did not find"""
    meta = (response or {}).get("meta") or {}
    return meta.get("warnings") or None


def _check_location_exists(client, location_id: str) -> None:
    """Explain an empty product result that comes from an unknown store

    The Products API answers a search at a locationId that does not exist
    with an empty result instead of an error.

    Raises:
        KrogerToolError: not_found, if no store has this location ID
    """
    try:
        exists = client.location.location_exists(location_id)
    except KrogerAPIError:
        # The check only explains an empty result, which stands without it
        return
    if not exists:
        raise KrogerToolError(
            "not_found",
            f"No store has locationId {location_id}. The Kroger Products API returns an empty result, "
            f"not an error, for a location that does not exist.",
            next_step=(
                "Find a valid location_id with search_locations. If this is the preferred location, "
                "replace it with set_preferred_location."
            ),
            details={"location_id": location_id},
        )


def register_tools(mcp):
    """Register product-related tools with the FastMCP server"""
    
    @mcp.tool()
    @translate_errors
    async def get_product_images(
        product_id: ProductId,
        perspective: Annotated[str, Field(min_length=1)] = "front",
        location_id: OptionalLocationId = None,
        ctx: Context = None
    ) -> Image:
        """
        Get an image for a specific product from the requested perspective.
        
        Use get_product_details first to see what perspectives are available (typically "front", "back", "left", "right").
        
        Args:
            product_id: The unique product identifier
            perspective: The image perspective to retrieve (default: "front")
            location_id: Store location ID (uses preferred if not provided; images are the same at every store)
        
        Returns:
            The product image from the requested perspective
        """
        # Images do not depend on the store, so a location is optional
        location_id = location_id or get_preferred_location_id()
        
        if ctx:
            await ctx.info(f"Fetching images for product {product_id} at location {location_id}")
        
        client = get_client_credentials_client()
        
        # Get product details to extract image URLs (an unknown product raises NotFoundError)
        product_details = client.product.get_product(
            product_id=product_id,
            location_id=location_id
        )
        product = (product_details or {}).get("data")
        if not isinstance(product, dict):
            raise KrogerToolError(
                "unexpected_response",
                f"The Kroger Products API answered without data for product {product_id}.",
                details={"response_body": product_details},
            )
        
        images = product.get("images") or []
        if not images:
            raise KrogerToolError(
                "no_images",
                f"Product {product_id} has no images.",
                details={"product_id": product_id},
            )
        
        available_perspectives = [img.get("perspective", "unknown") for img in images]
        img_data = next((img for img in images if img.get("perspective") == perspective and img.get("sizes")), None)
        if img_data is None:
            raise KrogerToolError(
                "invalid_parameter",
                f"Product {product_id} has no '{perspective}' image. Available perspectives: "
                f"{', '.join(available_perspectives)}",
                next_step="Call get_product_images again with one of the available perspectives.",
                details={"param": "perspective", "value": perspective, "available_perspectives": available_perspectives},
            )
        
        # Find the best image size (prefer large, fallback to xlarge or other available)
        size_preference = ["large", "xlarge", "medium", "small", "thumbnail"]
        available_sizes = {size.get("size"): size.get("url") for size in img_data["sizes"] if size.get("size") and size.get("url")}
        img_url = next((available_sizes[size] for size in size_preference if size in available_sizes), None)
        if img_url is None:
            # Sizes outside the preference list are still usable
            img_url = next(iter(available_sizes.values()), None)
        if img_url is None:
            raise KrogerToolError(
                "no_images",
                f"The '{perspective}' image of product {product_id} has no download URL.",
                details={"product_id": product_id, "perspective": perspective},
            )
        
        if ctx:
            await ctx.info(f"Downloading {perspective} image from {img_url}")
        
        try:
            response = requests.get(img_url, timeout=IMAGE_TIMEOUT)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None
            raise KrogerToolError(
                "image_download_failed",
                f"Could not download the {perspective} image of product {product_id} from {img_url}: {e}",
                next_step="Retry once. If it fails again, give the user the image URL instead.",
                details={"url": img_url, "status_code": status_code},
            ) from e
        
        # Kroger images are typically JPEG
        return Image(data=response.content, format="jpeg")
    
    @mcp.tool()
    @translate_errors
    async def search_products(
        search_term: SearchTerm,
        location_id: OptionalLocationId = None,
        limit: ProductLimit = 10,
        fulfillment: Fulfillment = None,
        brand: Brand = None,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Search for products at a Kroger store.
        
        Args:
            search_term: Product search term (e.g., "milk", "bread", "organic apples"); 3+ characters, at most 8 words
            location_id: Store location ID (uses preferred location if not provided)
            limit: Number of results to return (1-50)
            fulfillment: Filter by fulfillment method: ais (available in store), csp (curbside pickup),
                dth (delivery to home), sth (ship to home)
            brand: Filter by brand name (case-sensitive)
        
        Returns:
            Dictionary containing product search results
        """
        validation.search_term(search_term, param="search_term")
        location_id = resolve_location_id(location_id)
        
        if ctx:
            await ctx.info(f"Searching for '{search_term}' at location {location_id}")
        
        client = get_client_credentials_client()
        
        products = client.product.search_products(
            term=search_term,
            location_id=location_id,
            limit=limit,
            fulfillment=fulfillment,
            brand=brand
        )
        
        formatted_products = [_format_product(p) for p in (products or {}).get("data") or []]
        if not formatted_products:
            _check_location_exists(client, location_id)

        if ctx:
            await ctx.info(f"Found {len(formatted_products)} products")
        
        result = {
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
        if not formatted_products:
            result["message"] = f"No products found matching '{search_term}' at location {location_id}"
        warnings = _api_warnings(products)
        if warnings:
            result["api_warnings"] = warnings
        return result

    @mcp.tool()
    @translate_errors
    async def bulk_search_products(
        searches: Annotated[List[ProductSearch], Field(min_length=1, max_length=25)],
        location_id: OptionalLocationId = None,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Search for multiple products in a single tool call to reduce round-trips.

        Args:
            searches: List of search queries (1-25). Each item should have:
                      - term: The search term (e.g., "milk", "bread"); 3+ characters, at most 8 words
                      - limit: Number of results per search (1-50, default: 10)
                      - fulfillment: Optional fulfillment filter ("ais", "csp", "dth", "sth")
                      - brand: Optional brand filter (case-sensitive)
            location_id: Store location ID applied to all searches (uses preferred if not provided)

        Returns:
            Dictionary containing results for each search term. A search that fails
            has success false and an error object; the call fails only if every
            search fails.
        """
        # Check every term before sending any request
        for index, search in enumerate(searches):
            validation.search_term(search.term, param=f"searches[{index}].term")
        location_id = resolve_location_id(location_id)

        if ctx:
            await ctx.info(f"Running {len(searches)} product searches at location {location_id}")

        client = get_client_credentials_client()
        results = []

        for search in searches:
            if ctx:
                await ctx.info(f"Searching for '{search.term}'")

            try:
                products = client.product.search_products(
                    term=search.term,
                    location_id=location_id,
                    limit=search.limit,
                    fulfillment=search.fulfillment,
                    brand=search.brand
                )
            except _PER_SEARCH_ERRORS as e:
                if ctx:
                    await ctx.warning(f"Error searching for '{search.term}': {e.message.splitlines()[0]}")
                results.append({
                    "term": search.term,
                    "success": False,
                    "error": KrogerToolError.from_api_error(e).to_dict(),
                    "data": []
                })
                continue

            formatted_products = [_format_product(p) for p in (products or {}).get("data") or []]
            result = {
                "term": search.term,
                "success": True,
                "count": len(formatted_products),
                "data": formatted_products
            }
            if not formatted_products:
                result["message"] = f"No products found matching '{search.term}'"
            warnings = _api_warnings(products)
            if warnings:
                result["api_warnings"] = warnings
            results.append(result)

        total_found = sum(r.get("count", 0) for r in results)
        successful = sum(1 for r in results if r.get("success"))

        if successful == 0:
            first_error = results[0]["error"]
            raise KrogerToolError(
                "all_searches_failed",
                f"All {len(results)} searches failed. The first error was:\n{first_error['message']}",
                next_step=first_error.get("next_step"),
                details={"results": results},
            )
        if total_found == 0:
            _check_location_exists(client, location_id)

        if ctx:
            await ctx.info(f"Completed {len(searches)} searches: {successful} successful, {total_found} total products found")

        return {
            "success": True,
            "location_id": location_id,
            "searches_completed": len(results),
            "searches_successful": successful,
            "total_products_found": total_found,
            "results": results
        }

    @mcp.tool()
    @translate_errors
    async def get_product_details(
        product_id: ProductId,
        location_id: OptionalLocationId = None,
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
        location_id = resolve_location_id(location_id)
        
        if ctx:
            await ctx.info(f"Getting details for product {product_id} at location {location_id}")
        
        client = get_client_credentials_client()
        
        # An unknown product raises NotFoundError
        product_details = client.product.get_product(
            product_id=product_id,
            location_id=location_id
        )
        
        product = (product_details or {}).get("data")
        if not isinstance(product, dict):
            raise KrogerToolError(
                "unexpected_response",
                f"The Kroger Products API answered without data for product {product_id}.",
                details={"response_body": product_details},
            )
            
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

        _add_extended_attributes(result, product)

        return result

    @mcp.tool()
    @translate_errors
    async def search_products_by_id(
        product_id: ProductId,
        location_id: OptionalLocationId = None,
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
        location_id = resolve_location_id(location_id)
        
        if ctx:
            await ctx.info(f"Searching for products with ID '{product_id}' at location {location_id}")
        
        client = get_client_credentials_client()
        
        products = client.product.search_products(
            product_id=product_id,
            location_id=location_id
        )
        
        formatted_products = [_format_product(p) for p in (products or {}).get("data") or []]
        if not formatted_products:
            _check_location_exists(client, location_id)
        
        if ctx:
            await ctx.info(f"Found {len(formatted_products)} products with ID '{product_id}'")
        
        result = {
            "success": True,
            "search_params": {
                "product_id": product_id,
                "location_id": location_id
            },
            "count": len(formatted_products),
            "data": formatted_products
        }
        if not formatted_products:
            result["message"] = f"No products found with ID '{product_id}'"
        warnings = _api_warnings(products)
        if warnings:
            result["api_warnings"] = warnings
        return result
