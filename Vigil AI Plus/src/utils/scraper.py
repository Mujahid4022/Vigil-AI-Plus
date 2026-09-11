"""
scraper.py - Highly resilient product scraper for Pakistani e-commerce sites.
Optimized for Shopify stores (Sapphire, Maria.B, J., Limelight) and custom frontends.
"""

import requests
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse


def extract_product_from_url(url, session):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }

    try:
        response = session.get(url, timeout=15, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")

        # 1. Product Name
        product_name = None
        og_title = soup.find("meta", property="og:title")
        h1 = soup.find("h1")
        html_title = soup.find("title")

        if og_title and og_title.get("content"):
            product_name = og_title["content"]
        elif h1:
            product_name = h1.get_text(strip=True)
        elif html_title:
            product_name = html_title.get_text(strip=True)

        if product_name:
            if " - " in product_name:
                product_name = product_name.split(" - ")[0]
            product_name = product_name[:120].strip()
        else:
            product_name = "Exclusive Brand Deal"

        # 2. Price (Fixed & Verified)
        price = None
        meta_price = soup.find("meta", property="product:price:amount") or soup.find("meta", property="og:price:amount")
        
        if meta_price and meta_price.get("content"):
            raw_text = str(meta_price["content"])
            clean_num = re.sub(r"[^\d,]", "", raw_text)
            try:
                num_value = int(clean_num.replace(",", ""))
                price = f"Rs. {num_value:,}"
            except ValueError:
                price = f"Rs. {raw_text}"

        if not price:
            price_regex = re.compile(r"(Rs\.|PKR|Rs)\s?([\d,]+\.?\d*)", re.IGNORECASE)
            for tag in soup.find_all(["span", "div", "p"], class_=re.compile(r"price|money|amount|current|sale", re.IGNORECASE)):
                txt = tag.get_text(strip=True)
                match = price_regex.search(txt)
                if match:
                    num_str = match.group(2).replace(",", "")
                    if "." in num_str:
                        num_str = num_str.split(".")[0]
                    if num_str.isdigit():
                        price = f"Rs. {int(num_str):,}"
                        break
                elif txt.replace(",", "").replace(".", "").replace(" ", "").isdigit():
                    clean_num = txt.split(".")[0].strip().replace(",", "")
                    if clean_num.isdigit():
                        price = f"Rs. {int(clean_num):,}"
                        break

        price = price if price else "Check Price on Site"

        # 3. Image URL (Fixed Regex Bug)
        image_url = None
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            img_src = og_image["content"]
            if img_src.startswith("//"):
                image_url = "https:" + img_src
            elif img_src.startswith("/"):
                image_url = urljoin(url, img_src)
            else:
                image_url = img_src
        else:
            img_tag = soup.find("img", {"src": re.compile(r"\.(jpg|jpeg|png|webp)", re.IGNORECASE)})
            if img_tag and img_tag.get("src"):
                img_src = img_tag["src"]
                if img_src.startswith("//"):
                    img_src = "https:" + img_src
                elif not img_src.startswith("http"):
                    img_src = urljoin(url, img_src)
                image_url = img_src

        # 4. Description
        detail = None
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            detail = og_desc["content"].strip()
        else:
            desc_block = soup.find("div", class_=re.compile(r"description|details|summary", re.IGNORECASE))
            if desc_block:
                first_p = desc_block.find("p")
                if first_p:
                    detail = first_p.get_text(strip=True)
            if not detail:
                first_p = soup.find("p")
                if first_p:
                    detail = first_p.get_text(strip=True)

        if detail and len(detail) > 120:
            detail = detail[:120] + "..."
        elif not detail:
            detail = "Tap the link below to view sizes and availability options."

        # 5. Seller
        domain = urlparse(url).netloc.replace("www.", "")
        seller = domain.split(".")[0].upper() if domain else "ONLINE STORE"

        return {
            "product": product_name,
            "price": price,
            "image_url": image_url,
            "link": url,
            "detail": detail,
            "seller": seller,
        }
    except Exception as e:
        print(f"⚠️ Error scraping product data from {url}: {e}")
        return None


def scrape_deals(url):
    """
    Scrapes a homepage, finds a valid product link immediately, and extracts data.
    Now with advanced link filtering to skip sizing charts and static pages.
    """
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = session.get(url, timeout=15, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")

        target_product_url = None
        parsed_home = urlparse(url)

        skip_patterns = re.compile(
            r"/(size-chart|sizing|guide|gift-card|info|help|faq|about|contact|terms|privacy|return|shipping)/",
            re.IGNORECASE
        )
        product_patterns = re.compile(
            r"/products?/|/items?/|/shop/[a-zA-Z0-9_-]+|/collections/[a-zA-Z0-9_-]+/products?/",
            re.IGNORECASE
        )

        for a_tag in soup.find_all("a", href=True):
            raw_href = a_tag["href"].split("?")[0]

            if skip_patterns.search(raw_href):
                continue

            if product_patterns.search(raw_href):
                full_url = urljoin(url, raw_href)
                if urlparse(full_url).netloc == parsed_home.netloc and full_url != url:
                    target_product_url = full_url
                    break

        if target_product_url:
            print(f"🔗 Found a valid item link! Scraping target: {target_product_url}")
            return extract_product_from_url(target_product_url, session)

        print("⚠️ No direct item pattern match on page. Attempting root scrape...")
        return extract_product_from_url(url, session)

    except Exception as e:
        print(f"⚠️ Fatal scrape disruption at {url}: {e}")
        return {
            "product": "New Brand Clearance Deal Update!",
            "price": "Check Best Pricing Online",
            "image_url": None,
            "link": url,
            "detail": "Seasonal discounts are active now. Visit site to claim.",
            "seller": "Brand Store",
        }


def generate_facebook_message(data):
    """
    Takes the structured scraped dict data and returns a perfectly formatted 
    marketing post for your Facebook Page automation engine.
    """
    if not data:
        return "⚠️ Error compiling search engine updates."
        
    post_template = f"""🔥 NEW BRAND SALE DETECTED! 🇵🇰

⚡ Brand: {data['seller']}
👗 Item: {data['product']}
💰 Price: {data['price']}

📝 Info: {data['detail']}

🛍️ Shop this direct product page instantly before sizes sell out:
🔗 {data['link']}

#SaleAlertPakistan #OnlineDeals #ShoppingBots"""
    return post_template


# ======================================================================
# WRAPPER FUNCTION FOR ENGINE 1 & ENGINE 2
# ======================================================================
def scrape_url(url):
    """
    Universal wrapper used by Engine 1 (Poetry) and Engine 2 (Deals).
    Accepts a URL, scrapes it using the new logic, and returns a clean text string
    that the AI can process.
    """
    print(f"📡 Scraping URL: {url}")
    
    # Use the new scraping logic
    result = scrape_deals(url)
    
    # If scraping failed or returned a fallback, return a fallback message
    if not result or not isinstance(result, dict):
        return "No product data found on this page."
    
    # Format the dict into the plain text string that the engines expect
    text = f"Product: {result.get('product', 'Unknown')}\n"
    text += f"Price: {result.get('price', 'N/A')}\n"
    text += f"Description: {result.get('detail', '')}\n"
    text += f"Seller: {result.get('seller', 'Unknown')}\n"
    text += f"Link: {result.get('link', url)}"
    
    return text


# ==========================================
# RUNTIME CHECK
# ==========================================
if __name__ == "__main__":
    # Test on a reliable Pakistani fashion store
    test_url = "https://pk.sapphireonline.com.pk"
    print(f"Testing scraper on: {test_url}")
    
    # Test both functions
    result_dict = scrape_deals(test_url)
    print("\n--- RAW JSON DATA ---")
    print(result_dict)
    
    result_text = scrape_url(test_url)
    print("\n--- SCRAPE_URL TEXT OUTPUT (for Engines) ---")
    print(result_text)
    
    print("\n--- FACEBOOK POST RENDER ---")
    print(generate_facebook_message(result_dict))