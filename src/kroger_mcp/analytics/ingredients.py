"""
Bad ingredients detection for product safety filtering.

This module contains a comprehensive list of unhealthy ingredients commonly
found in processed foods, along with detection logic using regex patterns
to avoid false positives.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any


class Severity(str, Enum):
    """Severity levels for flagged ingredients."""
    CRITICAL = "critical"  # Hard warnings - strongly recommend avoiding
    WARNING = "warning"    # Soft warnings - moderate concern
    WATCH = "watch"        # Informational - low concern


@dataclass
class IngredientInfo:
    """Information about a flagged ingredient."""
    key: str              # Unique identifier
    name: str             # Display name
    aliases: List[str]    # Alternative names/spellings
    severity: Severity    # Severity level
    reason: str           # Why it's flagged
    category: str         # Category (preservative, sweetener, etc.)
    exclude_patterns: Optional[List[str]] = None  # Patterns to exclude (e.g., "sugar free")


# Comprehensive list of bad ingredients with severity levels
BAD_INGREDIENTS: List[IngredientInfo] = [
    # ==================== CRITICAL SEVERITY ====================
    # Preservatives linked to serious health concerns
    IngredientInfo(
        key="sodium_nitrite",
        name="Sodium Nitrite",
        aliases=["sodium nitrate", "nitrite", "nitrate", "cured with nitrite"],
        severity=Severity.CRITICAL,
        reason="Linked to increased cancer risk when heated",
        category="preservative",
    ),
    IngredientInfo(
        key="bha",
        name="BHA (Butylated Hydroxyanisole)",
        aliases=["butylated hydroxyanisole", "E320"],
        severity=Severity.CRITICAL,
        reason="Potential carcinogen, endocrine disruptor",
        category="preservative",
    ),
    IngredientInfo(
        key="bht",
        name="BHT (Butylated Hydroxytoluene)",
        aliases=["butylated hydroxytoluene", "E321"],
        severity=Severity.CRITICAL,
        reason="Potential carcinogen",
        category="preservative",
    ),
    IngredientInfo(
        key="potassium_bromate",
        name="Potassium Bromate",
        aliases=["bromate", "bromated flour"],
        severity=Severity.CRITICAL,
        reason="Banned in many countries, potential carcinogen",
        category="preservative",
    ),
    IngredientInfo(
        key="bvo",
        name="Brominated Vegetable Oil",
        aliases=["BVO", "brominated oil"],
        severity=Severity.CRITICAL,
        reason="Neurological and reproductive concerns",
        category="emulsifier",
    ),

    # Artificial sweeteners with significant concerns
    IngredientInfo(
        key="aspartame",
        name="Aspartame",
        aliases=["equal", "nutrasweet", "E951", "APM"],
        severity=Severity.CRITICAL,
        reason="Neurological concerns, potential carcinogen (WHO)",
        category="artificial_sweetener",
    ),

    # Unhealthy fats
    IngredientInfo(
        key="trans_fat",
        name="Trans Fat / Partially Hydrogenated Oil",
        aliases=[
            "partially hydrogenated", "PHO", "trans fat",
            "partially hydrogenated oil", "hydrogenated vegetable oil"
        ],
        severity=Severity.CRITICAL,
        reason="Heart disease, stroke risk",
        category="fat",
    ),

    # High fructose corn syrup
    IngredientInfo(
        key="hfcs",
        name="High Fructose Corn Syrup",
        aliases=["HFCS", "corn syrup high fructose", "glucose-fructose syrup"],
        severity=Severity.CRITICAL,
        reason="Linked to obesity, diabetes, metabolic syndrome",
        category="sweetener",
    ),

    # Hydrolyzed protein (contains free glutamate)
    IngredientInfo(
        key="hydrolyzed_protein",
        name="Hydrolyzed Protein",
        aliases=[
            "hydrolyzed vegetable protein", "HVP",
            "hydrolyzed soy protein", "hydrolyzed plant protein",
            "hydrolyzed yeast", "protein hydrolysate",
            "hydrolyzed wheat protein", "hydrolyzed corn protein"
        ],
        severity=Severity.CRITICAL,
        reason="Contains free glutamate, excitotoxin, headaches",
        category="flavor_enhancer",
    ),

    # Sulfites
    IngredientInfo(
        key="sulfites",
        name="Sulfites",
        aliases=[
            "sodium sulfite", "sodium bisulfite", "sodium metabisulfite",
            "potassium bisulfite", "potassium metabisulfite", "sulfur dioxide",
            "E220", "E221", "E222", "E223", "E224", "E225", "E226", "E227", "E228"
        ],
        severity=Severity.CRITICAL,
        reason="Severe allergic reactions, asthma trigger, banned on fresh produce",
        category="preservative",
    ),
    IngredientInfo(
        key="propyl_gallate",
        name="Propyl Gallate",
        aliases=["E310", "propyl 3,4,5-trihydroxybenzoate"],
        severity=Severity.CRITICAL,
        reason="Potential carcinogen, endocrine disruptor",
        category="preservative",
    ),
    IngredientInfo(
        key="interesterified_fat",
        name="Interesterified Fat",
        aliases=["interesterified oil", "interesterified vegetable oil"],
        severity=Severity.CRITICAL,
        reason="May raise blood sugar, heart disease concerns",
        category="fat",
    ),
    IngredientInfo(
        key="olestra",
        name="Olestra",
        aliases=["olean"],
        severity=Severity.CRITICAL,
        reason="Causes digestive issues, blocks vitamin absorption",
        category="fat_substitute",
    ),

    # ==================== WARNING SEVERITY ====================
    # Artificial colors
    IngredientInfo(
        key="red_40",
        name="Red 40 (Allura Red)",
        aliases=["allura red", "FD&C red 40", "E129", "red dye 40", "red #40", "red 40"],
        severity=Severity.WARNING,
        reason="Behavioral effects in children, potential carcinogen",
        category="artificial_color",
    ),
    IngredientInfo(
        key="red_3",
        name="Red 3 (Erythrosine)",
        aliases=["erythrosine", "FD&C red 3", "E127", "red dye 3", "red #3"],
        severity=Severity.WARNING,
        reason="Thyroid tumors in animals, banned in cosmetics",
        category="artificial_color",
    ),
    IngredientInfo(
        key="yellow_5",
        name="Yellow 5 (Tartrazine)",
        aliases=["tartrazine", "FD&C yellow 5", "E102", "yellow dye 5", "yellow #5", "yellow 5"],
        severity=Severity.WARNING,
        reason="Behavioral effects, allergic reactions",
        category="artificial_color",
    ),
    IngredientInfo(
        key="yellow_6",
        name="Yellow 6 (Sunset Yellow)",
        aliases=["sunset yellow", "FD&C yellow 6", "E110", "yellow dye 6", "yellow #6", "yellow 6"],
        severity=Severity.WARNING,
        reason="Behavioral effects in children",
        category="artificial_color",
    ),
    IngredientInfo(
        key="blue_1",
        name="Blue 1 (Brilliant Blue)",
        aliases=["brilliant blue", "FD&C blue 1", "E133", "blue dye 1", "blue #1", "blue 1"],
        severity=Severity.WARNING,
        reason="Potential neurotoxin",
        category="artificial_color",
    ),
    IngredientInfo(
        key="blue_2",
        name="Blue 2 (Indigo Carmine)",
        aliases=["indigo carmine", "FD&C blue 2", "E132", "blue dye 2", "blue #2"],
        severity=Severity.WARNING,
        reason="Brain tumors in animals",
        category="artificial_color",
    ),
    IngredientInfo(
        key="green_3",
        name="Green 3 (Fast Green)",
        aliases=["fast green", "FD&C green 3", "E143", "green dye 3", "green #3"],
        severity=Severity.WARNING,
        reason="Bladder tumors in animals",
        category="artificial_color",
    ),
    IngredientInfo(
        key="citrus_red_2",
        name="Citrus Red 2",
        aliases=["E121", "citrus red no. 2"],
        severity=Severity.WARNING,
        reason="Potential carcinogen, only allowed on orange peels",
        category="artificial_color",
    ),
    IngredientInfo(
        key="orange_b",
        name="Orange B",
        aliases=["FD&C orange B"],
        severity=Severity.WARNING,
        reason="Limited use approved, potential carcinogen",
        category="artificial_color",
    ),

    # Other artificial sweeteners
    IngredientInfo(
        key="sucralose",
        name="Sucralose",
        aliases=["splenda", "E955"],
        severity=Severity.WARNING,
        reason="Gut microbiome disruption, insulin response",
        category="artificial_sweetener",
    ),
    IngredientInfo(
        key="acesulfame_k",
        name="Acesulfame-K",
        aliases=["acesulfame potassium", "ace-k", "E950", "acesulfame"],
        severity=Severity.WARNING,
        reason="Limited long-term safety data, contains methylene chloride",
        category="artificial_sweetener",
    ),
    IngredientInfo(
        key="saccharin",
        name="Saccharin",
        aliases=["sweet'n low", "E954"],
        severity=Severity.WARNING,
        reason="Historical cancer concerns",
        category="artificial_sweetener",
    ),

    # Preservatives (moderate concern)
    IngredientInfo(
        key="tbhq",
        name="TBHQ (Tertiary Butylhydroquinone)",
        aliases=["tertiary butylhydroquinone", "E319"],
        severity=Severity.WARNING,
        reason="Potential carcinogen at high doses",
        category="preservative",
    ),
    IngredientInfo(
        key="sodium_benzoate",
        name="Sodium Benzoate",
        aliases=["benzoate", "E211"],
        severity=Severity.WARNING,
        reason="Forms benzene with vitamin C, hyperactivity",
        category="preservative",
    ),
    IngredientInfo(
        key="potassium_sorbate",
        name="Potassium Sorbate",
        aliases=["sorbate", "E202"],
        severity=Severity.WARNING,
        reason="Potential DNA damage, allergic reactions",
        category="preservative",
    ),

    # Emulsifiers
    IngredientInfo(
        key="carrageenan",
        name="Carrageenan",
        aliases=["E407", "irish moss extract"],
        severity=Severity.WARNING,
        reason="Inflammation, gut issues",
        category="emulsifier",
    ),
    IngredientInfo(
        key="polysorbate_80",
        name="Polysorbate 80",
        aliases=["polysorbate 60", "E433", "E432", "tween 80"],
        severity=Severity.WARNING,
        reason="Gut barrier disruption, inflammation",
        category="emulsifier",
    ),

    # Other additives
    IngredientInfo(
        key="azodicarbonamide",
        name="Azodicarbonamide",
        aliases=["E927", "ADA", "azo"],
        severity=Severity.WARNING,
        reason="Banned in EU and Australia, respiratory issues",
        category="dough_conditioner",
    ),
    IngredientInfo(
        key="titanium_dioxide",
        name="Titanium Dioxide",
        aliases=["E171", "TiO2"],
        severity=Severity.WARNING,
        reason="Nanoparticle concerns, banned in EU food",
        category="whitening_agent",
    ),
    IngredientInfo(
        key="diacetyl",
        name="Diacetyl",
        aliases=["butanedione"],
        severity=Severity.WARNING,
        reason="Respiratory issues (popcorn lung)",
        category="flavoring",
    ),

    # Aluminum compounds
    IngredientInfo(
        key="sodium_aluminum_phosphate",
        name="Sodium Aluminum Phosphate",
        aliases=["SALP", "E541", "aluminum phosphate"],
        severity=Severity.WARNING,
        reason="Aluminum accumulation concerns, neurotoxicity",
        category="leavening_agent",
    ),
    IngredientInfo(
        key="sodium_aluminum_sulfate",
        name="Sodium Aluminum Sulfate",
        aliases=["SAS", "aluminum sulfate"],
        severity=Severity.WARNING,
        reason="Aluminum accumulation, neurological concerns",
        category="leavening_agent",
    ),

    # Additional preservatives and additives
    IngredientInfo(
        key="calcium_disodium_edta",
        name="Calcium Disodium EDTA",
        aliases=["EDTA", "E385", "disodium EDTA", "edetic acid"],
        severity=Severity.WARNING,
        reason="May affect mineral absorption, synthetic chelating agent",
        category="preservative",
    ),
    IngredientInfo(
        key="calcium_propionate",
        name="Calcium Propionate",
        aliases=["E282", "propionate", "sodium propionate"],
        severity=Severity.WARNING,
        reason="Linked to behavioral issues in children, irritability",
        category="preservative",
    ),
    IngredientInfo(
        key="sodium_erythorbate",
        name="Sodium Erythorbate",
        aliases=["E316", "erythorbate"],
        severity=Severity.WARNING,
        reason="Synthetic preservative, may cause headaches",
        category="preservative",
    ),

    # Dough conditioners and emulsifiers
    IngredientInfo(
        key="datem",
        name="DATEM",
        aliases=[
            "diacetyl tartaric acid esters of monoglycerides",
            "E472e", "diacetyl tartaric acid ester"
        ],
        severity=Severity.WARNING,
        reason="Synthetic emulsifier, limited safety data",
        category="dough_conditioner",
    ),
    IngredientInfo(
        key="sodium_stearoyl_lactylate",
        name="Sodium Stearoyl Lactylate",
        aliases=["SSL", "E481", "calcium stearoyl lactylate", "E482"],
        severity=Severity.WARNING,
        reason="Synthetic emulsifier, may cause digestive issues",
        category="emulsifier",
    ),

    # Anti-foaming and processing aids
    IngredientInfo(
        key="dimethylpolysiloxane",
        name="Dimethylpolysiloxane",
        aliases=["E900", "PDMS", "silicone", "dimethicone"],
        severity=Severity.WARNING,
        reason="Industrial chemical used as anti-foaming agent",
        category="processing_aid",
    ),

    # Artificial flavors
    IngredientInfo(
        key="artificial_flavor",
        name="Artificial Flavor",
        aliases=["artificial flavors", "artificial flavoring", "artificially flavored"],
        severity=Severity.WARNING,
        reason="Synthetic chemicals, lack of transparency, potential allergens",
        category="flavoring",
    ),

    # Neotame (newer artificial sweetener)
    IngredientInfo(
        key="neotame",
        name="Neotame",
        aliases=["E961"],
        severity=Severity.WARNING,
        reason="Similar to aspartame but more potent, limited long-term data",
        category="artificial_sweetener",
    ),

    # Advantame
    IngredientInfo(
        key="advantame",
        name="Advantame",
        aliases=["E969"],
        severity=Severity.WARNING,
        reason="Derived from aspartame, extremely limited safety data",
        category="artificial_sweetener",
    ),

    # ==================== WATCH SEVERITY ====================
    IngredientInfo(
        key="natural_flavors",
        name="Natural Flavors",
        aliases=["natural flavor", "natural flavoring"],
        severity=Severity.WATCH,
        reason="Often contains MSG derivatives, lack of transparency",
        category="flavoring",
    ),
    IngredientInfo(
        key="caramel_color",
        name="Caramel Color",
        aliases=["E150c", "E150d", "caramel colour"],
        severity=Severity.WATCH,
        reason="Class III/IV may contain 4-MEI (carcinogen)",
        category="artificial_color",
    ),
    IngredientInfo(
        key="autolyzed_yeast",
        name="Autolyzed Yeast Extract",
        aliases=["autolyzed yeast", "yeast extract"],
        severity=Severity.WATCH,
        reason="Contains free glutamate (hidden MSG)",
        category="flavor_enhancer",
    ),
    IngredientInfo(
        key="propylene_glycol",
        name="Propylene Glycol",
        aliases=["E1520", "PG"],
        severity=Severity.WATCH,
        reason="Synthetic, industrial uses",
        category="solvent",
    ),
    IngredientInfo(
        key="sodium_phosphate",
        name="Sodium Phosphate",
        aliases=["phosphate", "E339", "trisodium phosphate", "disodium phosphate"],
        severity=Severity.WATCH,
        reason="Kidney concerns in excess",
        category="preservative",
    ),

    # Refined/processed ingredients
    IngredientInfo(
        key="maltodextrin",
        name="Maltodextrin",
        aliases=["corn maltodextrin", "rice maltodextrin"],
        severity=Severity.WATCH,
        reason="High glycemic index, blood sugar spikes",
        category="filler",
    ),
    IngredientInfo(
        key="corn_syrup",
        name="Corn Syrup",
        aliases=["glucose syrup", "corn syrup solids"],
        severity=Severity.WATCH,
        reason="Highly processed sugar, blood sugar impact",
        category="sweetener",
        exclude_patterns=["high fructose corn syrup", "hfcs"],
    ),
    IngredientInfo(
        key="modified_food_starch",
        name="Modified Food Starch",
        aliases=["modified corn starch", "modified starch", "modified tapioca starch"],
        severity=Severity.WATCH,
        reason="Chemically processed, low nutritional value",
        category="thickener",
    ),
    IngredientInfo(
        key="bleached_flour",
        name="Bleached Flour",
        aliases=["bleached wheat flour", "bleached enriched flour"],
        severity=Severity.WATCH,
        reason="Chemical bleaching agents, stripped nutrients",
        category="flour",
    ),

    # Thickeners and stabilizers
    IngredientInfo(
        key="cellulose",
        name="Cellulose",
        aliases=[
            "powdered cellulose", "microcrystalline cellulose",
            "cellulose gum", "cellulose gel", "E460", "E461", "E466"
        ],
        severity=Severity.WATCH,
        reason="Wood pulp filler, no nutritional value",
        category="filler",
    ),
    IngredientInfo(
        key="silicon_dioxide",
        name="Silicon Dioxide",
        aliases=["E551", "silica", "anti-caking agent"],
        severity=Severity.WATCH,
        reason="Industrial anti-caking agent, indigestible",
        category="anti_caking",
    ),
    IngredientInfo(
        key="magnesium_stearate",
        name="Magnesium Stearate",
        aliases=["E572", "stearic acid magnesium salt"],
        severity=Severity.WATCH,
        reason="Processing aid, may affect nutrient absorption",
        category="processing_aid",
    ),

    # Soy derivatives
    IngredientInfo(
        key="soy_lecithin",
        name="Soy Lecithin",
        aliases=["lecithin", "E322"],
        severity=Severity.WATCH,
        reason="Often from GMO soy, allergen for some",
        category="emulsifier",
    ),
    IngredientInfo(
        key="soy_protein_isolate",
        name="Soy Protein Isolate",
        aliases=["isolated soy protein", "soy protein concentrate"],
        severity=Severity.WATCH,
        reason="Highly processed, may contain hexane residues",
        category="protein",
    ),

    # Gums (can cause digestive issues for sensitive individuals)
    IngredientInfo(
        key="xanthan_gum",
        name="Xanthan Gum",
        aliases=["E415"],
        severity=Severity.WATCH,
        reason="May cause digestive issues in some people",
        category="thickener",
    ),
    IngredientInfo(
        key="guar_gum",
        name="Guar Gum",
        aliases=["E412"],
        severity=Severity.WATCH,
        reason="May cause bloating and gas in sensitive individuals",
        category="thickener",
    ),

    # Palm oil
    IngredientInfo(
        key="palm_oil",
        name="Palm Oil",
        aliases=["palm kernel oil", "palmitate", "palm fruit oil"],
        severity=Severity.WATCH,
        reason="High in saturated fat, environmental concerns",
        category="fat",
    ),

    # Dextrose and processed sugars
    IngredientInfo(
        key="dextrose",
        name="Dextrose",
        aliases=["glucose", "grape sugar"],
        severity=Severity.WATCH,
        reason="Refined sugar, rapid blood sugar spike",
        category="sweetener",
    ),
]


def _compile_ingredient_patterns() -> Dict[str, re.Pattern]:
    """
    Pre-compile regex patterns for all ingredients.

    Uses word boundaries and negative lookbehind/lookahead to avoid
    false positives like "sugar free" matching "sugar".
    """
    patterns = {}

    for ingredient in BAD_INGREDIENTS:
        # Combine main name with aliases
        all_terms = [ingredient.name.lower()] + [a.lower() for a in ingredient.aliases]

        # Build pattern with word boundaries
        escaped_terms = [re.escape(term) for term in all_terms]
        base_pattern = r'\b(' + '|'.join(escaped_terms) + r')\b'

        # Note: exclude_patterns are checked separately in check_product_safety()
        # rather than being built into the regex pattern

        patterns[ingredient.key] = re.compile(base_pattern, re.IGNORECASE)

    return patterns


# Pre-compiled patterns for performance
_INGREDIENT_PATTERNS = _compile_ingredient_patterns()


@dataclass
class IngredientMatch:
    """A single matched bad ingredient."""
    ingredient_key: str
    ingredient_name: str
    severity: Severity
    reason: str
    category: str
    matched_text: str


@dataclass
class SafetyResult:
    """Result of checking a product for bad ingredients."""
    has_concerns: bool
    highest_severity: Optional[Severity]
    matches: List[IngredientMatch]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "has_concerns": self.has_concerns,
            "highest_severity": self.highest_severity.value if self.highest_severity else None,
            "flagged_ingredients": [
                {
                    "ingredient": m.ingredient_name,
                    "severity": m.severity.value,
                    "reason": m.reason,
                    "category": m.category,
                    "matched_text": m.matched_text,
                }
                for m in self.matches
            ]
        }


def check_product_safety(
    description: str,
    brand: Optional[str] = None,
    categories: Optional[List[str]] = None,
    disabled_ingredients: Optional[set] = None,
) -> SafetyResult:
    """
    Check a product for bad ingredients based on its description.

    Args:
        description: Product description/name to scan
        brand: Brand name (not scanned to avoid false positives)
        categories: Product categories (for context, not currently used)
        disabled_ingredients: Set of ingredient keys to skip

    Returns:
        SafetyResult with all matched ingredients
    """
    if not description:
        return SafetyResult(has_concerns=False, highest_severity=None, matches=[])

    text = description.lower()
    matches: List[IngredientMatch] = []
    disabled = disabled_ingredients or set()

    for ingredient in BAD_INGREDIENTS:
        # Skip if user disabled this ingredient check
        if ingredient.key in disabled:
            continue

        pattern = _INGREDIENT_PATTERNS.get(ingredient.key)
        if not pattern:
            continue

        match = pattern.search(text)
        if match:
            # Check exclusion patterns
            if ingredient.exclude_patterns:
                skip = False
                for excl in ingredient.exclude_patterns:
                    if excl.lower() in text:
                        skip = True
                        break
                if skip:
                    continue

            matches.append(IngredientMatch(
                ingredient_key=ingredient.key,
                ingredient_name=ingredient.name,
                severity=ingredient.severity,
                reason=ingredient.reason,
                category=ingredient.category,
                matched_text=match.group(0),
            ))

    # Determine highest severity
    highest_severity = None
    if matches:
        severity_order = [Severity.CRITICAL, Severity.WARNING, Severity.WATCH]
        for sev in severity_order:
            if any(m.severity == sev for m in matches):
                highest_severity = sev
                break

    return SafetyResult(
        has_concerns=len(matches) > 0,
        highest_severity=highest_severity,
        matches=matches,
    )


def get_ingredient_by_key(key: str) -> Optional[IngredientInfo]:
    """Get ingredient info by its key."""
    for ing in BAD_INGREDIENTS:
        if ing.key == key:
            return ing
    return None


def get_all_ingredients() -> List[Dict[str, Any]]:
    """Get all bad ingredients as a list of dictionaries."""
    return [
        {
            "key": ing.key,
            "name": ing.name,
            "aliases": ing.aliases,
            "severity": ing.severity.value,
            "reason": ing.reason,
            "category": ing.category,
        }
        for ing in BAD_INGREDIENTS
    ]


def get_ingredients_by_severity(severity: Severity) -> List[Dict[str, Any]]:
    """Get ingredients filtered by severity level."""
    return [
        {
            "key": ing.key,
            "name": ing.name,
            "aliases": ing.aliases,
            "severity": ing.severity.value,
            "reason": ing.reason,
            "category": ing.category,
        }
        for ing in BAD_INGREDIENTS
        if ing.severity == severity
    ]


def get_ingredients_by_category(category: str) -> List[Dict[str, Any]]:
    """Get ingredients filtered by category."""
    return [
        {
            "key": ing.key,
            "name": ing.name,
            "aliases": ing.aliases,
            "severity": ing.severity.value,
            "reason": ing.reason,
            "category": ing.category,
        }
        for ing in BAD_INGREDIENTS
        if ing.category == category
    ]


def get_categories() -> List[str]:
    """Get all unique ingredient categories."""
    return sorted(set(ing.category for ing in BAD_INGREDIENTS))
