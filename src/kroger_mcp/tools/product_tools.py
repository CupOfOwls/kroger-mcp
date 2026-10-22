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
    BadRequestError,
    InternalServerError,
    InvalidParameterError,
    InvalidResponseError,
    KrogerAPIError,
    NotFoundError,
)

from ..errors import KrogerToolError, translate_errors
from .params import Brand, Fulfillment, OptionalLocationId, ProductId, ProductLimit, SearchTerm
from .shared import (
    get_client_credentials_client, 
    get_preferred_location_id,
    log_to_client,
    resolve_location_id,
    format_currency,
    response_data,
)

# Seconds to wait for a product image download
IMAGE_TIMEOUT = 30

# Errors that concern one search of a bulk search, so the other searches still
# run. Any other error, such as a rate limit, rejected credentials, or a
# network failure, would fail every later search too, so it stops the
# remaining searches.
_PER_SEARCH_ERRORS = (InvalidParameterError, BadRequestError, NotFoundError, InternalServerError, InvalidResponseError)


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


def _format_pricing(price: Dict[str, Any]) -> Dict[str, Any]:
    regular, promo = price.get("regular"), price.get("promo")
    # The API leaves out promo, or sends 0, when the item is not on sale
    on_sale = bool(promo) and regular is not None and promo < regular
    return {
        "regular_price": regular,
        "sale_price": promo,
        "regular_per_unit": price.get("regularPerUnitEstimate"),
        "formatted_regular": format_currency(regular),
        "formatted_sale": format_currency(promo),
        "on_sale": on_sale,
        "savings": round(regular - promo, 2) if on_sale else 0,
    }


def _format_product(product: Dict[str, Any], all_image_sizes: bool = False) -> Dict[str, Any]:
    """Format a raw Kroger product into the structure every product tool returns

    Args:
        product: A product from the Products API
        all_image_sizes: List every size of each image, not only the first
    """
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

        if isinstance(item.get("price"), dict):
            formatted["pricing"] = _format_pricing(item["price"])

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

    if all_image_sizes and product.get("images"):
        formatted["images"] = [
            {
                "perspective": img.get("perspective"),
                "sizes": [{"size": size.get("size"), "url": size.get("url")} for size in img.get("sizes", [])]
            }
            for img in product["images"]
        ]
    elif product.get("images"):
        formatted["images"] = [
            {
                "perspective": img.get("perspective"),
                "url": img["sizes"][0].get("url"),
                "size": img["sizes"][0].get("size")
            }
            for img in product["images"]
            if img.get("sizes")
        ]

    _add_extended_attributes(formatted, product)

    return formatted


def _search_results(response: Optional[Dict[str, Any]], result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Add a product search's formatted products and API warnings to result, and return the products

    The Products API puts warnings, such as product IDs it did not find, in
    meta.warnings.
    """
    products = [_format_product(p) for p in (response or {}).get("data") or []]
    result["count"] = len(products)
    result["data"] = products
    warnings = ((response or {}).get("meta") or {}).get("warnings")
    if warnings:
        result["api_warnings"] = warnings
    return products


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
    def get_product_images(
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
        
        log_to_client(ctx, f"Fetching images for product {product_id} at location {location_id}")
        
        client = get_client_credentials_client()
        
        # Get product details to extract image URLs (an unknown product raises NotFoundError)
        product = response_data(
            client.product.get_product(product_id=product_id, location_id=location_id),
            dict, "Products", f"data for product {product_id}",
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
        
        log_to_client(ctx, f"Downloading {perspective} image from {img_url}")
        
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
    def search_products(
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
        
        log_to_client(ctx, f"Searching for '{search_term}' at location {location_id}")
        
        client = get_client_credentials_client()
        
        products = client.product.search_products(
            term=search_term,
            location_id=location_id,
            limit=limit,
            fulfillment=fulfillment,
            brand=brand
        )
        
        result = {
            "success": True,
            "search_params": {
                "search_term": search_term,
                "location_id": location_id,
                "limit": limit,
                "fulfillment": fulfillment,
                "brand": brand
            },
        }
        if not _search_results(products, result):
            _check_location_exists(client, location_id)
            result["message"] = f"No products found matching '{search_term}' at location {location_id}"

        log_to_client(ctx, f"Found {result['count']} products")
        return result

    @mcp.tool()
    @translate_errors
    def bulk_search_products(
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
            has success false and an error object. An error that would fail every
            later search too, such as a rate limit or a network failure, stops the
            remaining searches: they have success false and searched false. The
            call fails only if no search succeeded.
        """
        # Check every term and brand before sending any request
        for index, search in enumerate(searches):
            validation.search_term(search.term, param=f"searches[{index}].term")
            if search.brand is not None:
                validation.check_non_empty(f"searches[{index}].brand", search.brand)
        location_id = resolve_location_id(location_id)

        log_to_client(ctx, f"Running {len(searches)} product searches at location {location_id}")

        client = get_client_credentials_client()
        results = []
        stopped_by: Optional[KrogerAPIError] = None

        for search in searches:
            if stopped_by is not None:
                results.append({"term": search.term, "success": False, "searched": False, "data": []})
                continue
            log_to_client(ctx, f"Searching for '{search.term}'")

            try:
                products = client.product.search_products(
                    term=search.term,
                    location_id=location_id,
                    limit=search.limit,
                    fulfillment=search.fulfillment,
                    brand=search.brand
                )
            except KrogerAPIError as e:
                if not isinstance(e, _PER_SEARCH_ERRORS):
                    stopped_by = e
                log_to_client(ctx, f"Error searching for '{search.term}': {e.message.splitlines()[0]}", level="warning")
                results.append({
                    "term": search.term,
                    "success": False,
                    "error": KrogerToolError.from_api_error(e).to_dict(),
                    "data": []
                })
                continue

            result = {"term": search.term, "success": True}
            if not _search_results(products, result):
                result["message"] = f"No products found matching '{search.term}'"
            results.append(result)

        total_found = sum(r.get("count", 0) for r in results)
        successful = sum(1 for r in results if r.get("success"))

        if successful == 0:
            if stopped_by is not None:
                # The error that stopped the searches, such as a rate limit, is the one to act on
                error = KrogerToolError.from_api_error(stopped_by)
                error.details["results"] = results
                raise error from stopped_by
            raise KrogerToolError(
                "all_searches_failed",
                f"All {len(results)} searches failed. The first error was:\n{results[0]['error']['message']}",
                next_step=results[0]["error"].get("next_step"),
                details={"results": results},
            )
        if total_found == 0:
            _check_location_exists(client, location_id)

        log_to_client(ctx, f"Completed {len(searches)} searches: {successful} successful, {total_found} total products found")

        response = {
            "success": True,
            "location_id": location_id,
            "searches_completed": sum(1 for r in results if r.get("searched", True)),
            "searches_successful": successful,
            "total_products_found": total_found,
            "results": results
        }
        if stopped_by is not None:
            error = KrogerToolError.from_api_error(stopped_by)
            response["stopped_early"] = {
                "message": f"The remaining searches were not run: {stopped_by.message.splitlines()[0]}",
                "error_type": error.error_type,
                "next_step": error.next_step,
            }
        return response

    @mcp.tool()
    @translate_errors
    def get_product_details(
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
        
        log_to_client(ctx, f"Getting details for product {product_id} at location {location_id}")
        
        client = get_client_credentials_client()
        
        # An unknown product raises NotFoundError
        product = response_data(
            client.product.get_product(product_id=product_id, location_id=location_id),
            dict, "Products", f"data for product {product_id}",
        )
        return {"success": True, **_format_product(product, all_image_sizes=True), "location_id": location_id}

    @mcp.tool()
    @translate_errors
    def search_products_by_id(
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
        
        log_to_client(ctx, f"Searching for products with ID '{product_id}' at location {location_id}")
        
        client = get_client_credentials_client()
        
        products = client.product.search_products(
            product_id=product_id,
            location_id=location_id
        )
        
        result = {
            "success": True,
            "search_params": {
                "product_id": product_id,
                "location_id": location_id
            },
        }
        if not _search_results(products, result):
            _check_location_exists(client, location_id)
            result["message"] = f"No products found with ID '{product_id}'"
        
        log_to_client(ctx, f"Found {result['count']} products with ID '{product_id}'")
        return result
