"""
Parameter types shared by the tools

The constraints come from kroger_api.validation, which documents the values
the Kroger API accepts. Declaring them in the tool signatures puts them in each
tool's input schema, and FastMCP rejects a call that breaks them before the
tool runs.
"""

from typing import Annotated, Literal, Optional

from pydantic import Field

from kroger_api import validation

LocationId = Annotated[str, Field(
    pattern=validation.LOCATION_ID_PATTERN,
    description="8-character store locationId, for example 01400513. Get one from search_locations.",
)]

OptionalLocationId = Annotated[Optional[str], Field(
    pattern=validation.LOCATION_ID_PATTERN,
    description=(
        "8-character store locationId, for example 01400513. "
        "Defaults to the preferred location set with set_preferred_location."
    ),
)]

ProductId = Annotated[str, Field(
    pattern=validation.PRODUCT_ID_PATTERN,
    description="13-digit productId or UPC, for example 0001111041700. Get one from search_products.",
)]

DepartmentId = Annotated[str, Field(
    pattern=validation.DEPARTMENT_ID_PATTERN,
    description="2-character department ID. Get one from list_departments.",
)]

ZipCode = Annotated[Optional[str], Field(
    pattern=validation.ZIP_CODE_PATTERN,
    description="5-digit ZIP code. ZIP+4 is not accepted. Defaults to the user's ZIP code (see get_user_zip_code).",
)]

SearchTerm = Annotated[str, Field(
    min_length=validation.PRODUCT_TERM_MIN_LENGTH,
    description=(
        f"Product search term, for example 'milk' or 'organic apples'. At least "
        f"{validation.PRODUCT_TERM_MIN_LENGTH} characters and at most {validation.PRODUCT_TERM_MAX_WORDS} "
        f"words separated by single spaces."
    ),
)]

ProductLimit = Annotated[int, Field(
    ge=validation.PRODUCT_LIMIT_MIN,
    le=validation.PRODUCT_LIMIT_MAX,
    description=f"Number of results to return ({validation.PRODUCT_LIMIT_MIN}-{validation.PRODUCT_LIMIT_MAX})",
)]

# Literal values cannot be built from validation.FULFILLMENT_TYPES at runtime;
# test_literal_parameters_match_kroger_api checks that the two stay the same.
Fulfillment = Annotated[Optional[Literal["ais", "csp", "dth", "sth"]], Field(
    description=(
        "Only return products available by this fulfillment method: ais (available in store), "
        "csp (curbside pickup), dth (delivery to home), sth (ship to home)"
    ),
)]

Brand = Annotated[Optional[str], Field(
    min_length=1,
    description="Only return products of this brand. Case-sensitive, for example 'Kroger'.",
)]

Modality = Annotated[Literal["PICKUP", "DELIVERY"], Field(
    description="How the order will be fulfilled: PICKUP or DELIVERY (uppercase)",
)]

Quantity = Annotated[int, Field(ge=1, description="Quantity to add, 1 or more")]
