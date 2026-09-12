"""
affiliate_api.py – Universal Affiliate Connector Engine.
Configuration-driven. No hardcoded provider names.
"""

import json
import requests
import time
import hashlib
import hmac
import base64
import uuid
import re
from typing import Dict, Any, List, Optional


# ======================================================================
# 1. HELPER FUNCTIONS
# ======================================================================

def _extract_image_url(item, path_spec):
    """Extract image URL, trying multiple paths in priority order (list or string)."""
    if isinstance(path_spec, list):
        for path in path_spec:
            val = get_nested_value(item, path, "")
            if val and isinstance(val, str) and val.strip():
                return val
        return ""
    return get_nested_value(item, path_spec, "")

def get_nested_value(data: Any, path: str, default: Any = "") -> Any:
    """
    Extract nested value using dot notation.
    Supports wildcard '*' for lists: 'products.*.price' returns list of prices.
    """
    if not path or data is None:
        return default

    try:
        current = data
        # Split path, but preserve '.*.' as special case
        parts = path.split(".")
        i = 0
        while i < len(parts):
            key = parts[i]
            
            if key == "*":
                # Wildcard: map over list
                if not isinstance(current, list):
                    return default
                # Get the rest of the path after '*'
                rest_path = ".".join(parts[i+1:])
                if not rest_path:
                    return current
                # Apply rest_path to each item in the list
                results = []
                for item in current:
                    val = get_nested_value(item, rest_path, default)
                    if val != default:
                        results.append(val)
                return results if results else default
            
            elif isinstance(current, list):
                if key.isdigit():
                    current = current[int(key)]
                else:
                    # Try to find key in first item, but don't auto-map
                    if current and isinstance(current[0], dict) and key in current[0]:
                        # Keep as list of values, not auto-map
                        current = [item.get(key) for item in current]
                    else:
                        return default
            elif isinstance(current, dict):
                current = current.get(key)
                if current is None:
                    return default
            else:
                return default
            i += 1
            
        return current if current is not None else default
    except (KeyError, IndexError, TypeError, ValueError):
        return default


def generate_hmac_signature(
    secret: str,
    params: Dict[str, str],
    method: str = "GET",
    body: Optional[Dict] = None,
    signature_format: str = "concat",
    algorithm: str = "sha256"
) -> str:
    """
    Generate HMAC signature with multiple algorithms and formats.
    """
    # Build the string to sign
    if method.upper() in ["POST", "PUT", "PATCH"] and body:
        sign_str = json.dumps(body, separators=(",", ":"), sort_keys=True)
    else:
        sorted_params = sorted(params.items())
        if signature_format == "concat":
            sign_str = "".join([f"{k}{v}" for k, v in sorted_params])
        elif signature_format == "query":
            sign_str = "&".join([f"{k}={v}" for k, v in sorted_params])
        else:
            sign_str = "".join([f"{k}{v}" for k, v in sorted_params])

    # Choose algorithm
    if algorithm == "sha256":
        return hmac.new(
            secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256
        ).hexdigest().upper()
    elif algorithm == "sha1":
        return hmac.new(
            secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha1
        ).hexdigest().upper()
    elif algorithm == "md5":
        return hmac.new(
            secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.md5
        ).hexdigest().upper()
    elif algorithm == "base64":
        return base64.b64encode(
            hmac.new(
                secret.encode("utf-8"),
                sign_str.encode("utf-8"),
                hashlib.sha256
            ).digest()
        ).decode()
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")


# ======================================================================
# 2. AFFILIATE LINK GENERATORS
# ======================================================================

def generate_affiliate_link(
    product_data: Dict[str, Any],
    provider: Dict[str, Any]
) -> str:
    """
    Generate affiliate link based on provider configuration.
    Supports multiple modes: direct, template, api.
    """
    mode = provider.get("affiliate_link_mode", "direct")
    
    if mode == "direct":
        # API returns affiliate link directly
        return product_data.get("affiliate_link", "")
    
    elif mode == "template":
        # Build from template
        template = provider.get("affiliate_link_template", "")
        if not template:
            return ""
        # Replace placeholders
        result = template
        for key, value in product_data.items():
            result = result.replace(f"{{{key}}}", str(value) if value else "")
        return result
    
    elif mode == "api":
        # Call separate affiliate link API
        # (This would need to be implemented for specific providers)
        print("⚠️ affiliate_link_mode 'api' requires custom implementation")
        return ""
    
    else:
        return product_data.get("affiliate_link", "")


# ======================================================================
# 3. UNIVERSAL API CALLER
# ======================================================================

def call_generic_api(provider: Dict[str, Any], search_term: str, page_no: int = 1) -> List[Dict[str, Any]]:
    """
    Universal API caller.
    All configuration comes from the provider dict.
    """

    # --- 3a. Basic configuration ---
    base_url = provider.get("base_url")
    if not base_url:
        print("❌ No base_url configured.")
        return []

    method = provider.get("method", "GET").upper()
    search_param = provider.get("search_param", "q")
    auth_type = provider.get("auth_type", "none").lower()
    response_path = provider.get("response_path", "")
    field_mapping = provider.get("field_mapping", {})
    product_list_path = provider.get("product_list_path", "")  # Path to the list of products

    # --- 3b. Build headers ---
    headers = provider.get("headers", {}).copy()
    api_key = provider.get("api_key", "")
    api_secret = provider.get("api_secret", "")
    auth_prefix = provider.get("auth_prefix", "")
    auth_header = provider.get("auth_header", "Authorization")

    if auth_type == "header":
        headers[auth_header] = f"{auth_prefix}{api_key}"
    elif auth_type == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_type == "basic":
        credentials = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"
    elif auth_type == "query":
        # Query params will handle this
        pass

    # --- 3c. Build query params and body ---
    query_params = provider.get("query_params", {}).copy()
    # Inject page number for pagination
    query_params["page_no"] = str(page_no)
    body_data = provider.get("body_data", {}).copy()
    search_in_body = provider.get("search_in_body", False)
    add_api_key_to_query = provider.get("add_api_key_to_query", False)

    if search_in_body:
        body_data[search_param] = search_term
    else:
        query_params[search_param] = search_term

    # Add API key to query if configured
    if add_api_key_to_query and auth_type != "header":
        query_params[provider.get("api_key_param", "api_key")] = api_key

    # Add static params
    for key, value in provider.get("static_params", {}).items():
        query_params[key] = value

    # --- 3d. Handle HMAC Signature (if required) ---
    if auth_type == "signature":
        # Generate timestamp and nonce BEFORE signing
        timestamp = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4()).replace("-", "")[:16]
        
        # Add timestamp and nonce to params
        if provider.get("add_timestamp", True):
            query_params["timestamp"] = timestamp
        if provider.get("add_nonce", False):
            query_params["nonce"] = nonce

        # Now generate signature with ALL params included
        signature_algorithm = provider.get("signature_algorithm", "sha256")
        signature_format = provider.get("signature_format", "concat")
        signature_in = provider.get("signature_in", "params")
        signature_param = provider.get("signature_param", "sign")

        # Determine if we have a body to sign (for POST/PUT/PATCH)
        has_body = method.upper() in ["POST", "PUT", "PATCH"] and body_data

        signature = generate_hmac_signature(
            secret=api_secret,
            params=query_params,
            method=method,
            body=body_data if has_body else None,
            signature_format=signature_format,
            algorithm=signature_algorithm
        )

        # Add signature where configured
        if signature_in == "params":
            query_params[signature_param] = signature
        else:  # header
            headers[provider.get("signature_header", "X-Signature")] = signature

    # --- 3e. Execute request ---
    try:
        if method == "GET":
            response = requests.get(
                base_url,
                params=query_params,
                headers=headers,
                timeout=provider.get("timeout", 15)
            )
        else:
            response = requests.request(
                method=method,
                url=base_url,
                params=query_params if query_params else None,
                json=body_data if body_data else None,
                headers=headers,
                timeout=provider.get("timeout", 15)
            )

        if response.status_code not in [200, 201]:
            print(f"❌ API returned {response.status_code}: {response.text[:200]}")
            return []

        data = response.json()
        
        # ===== DEBUG: Print full response for troubleshooting =====
        print(f"📝 Full API response (first 1000 chars):")
        print(json.dumps(data, indent=2))
        print("=" * 60)
        # ========================================================

    except requests.exceptions.Timeout:
        print("❌ Request timed out.")
        return []
    except Exception as e:
        print(f"❌ Request error: {e}")
        return []

    # --- 3f. Extract products ---
    raw_products = get_nested_value(data, response_path)
    if not raw_products:
        print(f"❌ No products found at path '{response_path}'.")
        return []

    if not isinstance(raw_products, list):
        raw_products = [raw_products] if raw_products else []

    # --- 3g. Map to internal format ---
    default_mapping = {
        "product_id": "id",
        "name": "name",
        "price": "price",
        "currency": "currency",
        "description": "description",
        "image_url": "image_url",
        "product_url": "product_url",
        "affiliate_link": "affiliate_link",
        "category": "category",
        "brand": "brand",
        "availability": "availability",
        "rating": "rating",
        "review_count": "review_count",
    }
    mapping = {**default_mapping, **field_mapping}

    products = []
    for item in raw_products:
        print(f"🔍 RAW ITEM: price={item.get('app_sale_price')}, currency={item.get('currency_code')}")
        if not isinstance(item, dict):
            continue
    
        # Extract default product data
        product = {
            "product_id": get_nested_value(item, mapping.get("product_id", "id"), ""),
            "name": get_nested_value(item, mapping.get("name", "name"), "Product"),
            "price": get_nested_value(item, mapping.get("price", "price"), "N/A"),
            "currency": get_nested_value(item, mapping.get("currency", "currency"), "USD"),
            "description": get_nested_value(item, mapping.get("description", "description"), "")[:500],
            "image_url": _extract_image_url(item, mapping.get("image_url", "image_url")),
            "product_url": get_nested_value(item, mapping.get("product_url", "product_url"), ""),
            "category": get_nested_value(item, mapping.get("category", "category"), ""),
            "brand": get_nested_value(item, mapping.get("brand", "brand"), ""),
            "availability": get_nested_value(item, mapping.get("availability", "availability"), ""),
            "rating": get_nested_value(item, mapping.get("rating", "rating"), ""),
            "review_count": get_nested_value(item, mapping.get("review_count", "review_count"), ""),
        }

        # ===== NEW: Extract extra fields from field_mapping =====
        default_keys = set(default_mapping.keys())
        for key, path in field_mapping.items():
            if key not in default_keys:
                product[key] = get_nested_value(item, path, "")

        # Fix AliExpress images (use a proxy)
        if product.get("image_url") and "aliexpress-media.com" in product["image_url"]:
            import urllib.parse
            product["image_url"] = f"https://images.weserv.nl/?url={urllib.parse.quote(product['image_url'])}"
    
        # Generate affiliate link
        product["affiliate_link"] = generate_affiliate_link(product, provider)
        print(f"🧪 MAPPED PRODUCT: {product}")

        print(
            f"🖼️ Product image: "
            f"{product.get('name', '')[:50]} -> "
            f"{product.get('image_url', '')}"
        )
    
        products.append(product)

    print(f"✅ Found {len(products)} products.")
    return products


# ======================================================================
# 4. MAIN ROUTER
# ======================================================================

def search_products(provider: Dict[str, Any], search_term: str, page_no: int = 1) -> List[Dict[str, Any]]:
    """
    Entry point – routes to the generic API caller if base_url is set.
    No hardcoded provider names. Everything comes from the config.
    Supports pagination via page_no.
    """
    print(f"🔍 Provider: {provider.get('nickname', 'Unknown')}")
    print(f"🔍 Search term: '{search_term}'")
    print(f"📄 Page number: {page_no}")

    if provider.get("base_url"):
        return call_generic_api(provider, search_term, page_no)
    else:
        print("❌ No base_url configured. Add it in the UI.")
        return []