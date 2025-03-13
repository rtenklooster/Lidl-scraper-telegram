"""
Lidl-specifieke scraper implementatie.
"""
import re
import json
from typing import List, Dict, Any, Optional, Tuple
import logging

from scrapers.base import BaseScraper, ProductInfo
from requester import LidlRequester

logger = logging.getLogger(__name__)


class LidlScraper(BaseScraper):
    """Scraper voor Lidl-producten."""
    
    def __init__(self):
        """Initialiseer de Lidl scraper."""
        self.requester = LidlRequester()
        self.default_fetch_size = 48
    
    def convert_url_to_api(self, url: str) -> str:
        """
        Converteert een gewone Lidl URL naar een API URL.
        """
        # Controleer of de URL al "api" bevat om dubbele api te voorkomen
        if "/q/api/" in url:
            api_url = url  # URL bevat al 'api', niet opnieuw toevoegen
        else:
            # Voeg 'api/' toe na 'q/' als dat nog niet gedaan is
            api_url = re.sub(r"www\.lidl\.nl/q/", "www.lidl.nl/q/api/", url)
            
            # Als de structuur anders is, controleer of we nog geen 'q/api/' hebben
            if "/q/api/" not in api_url:
                # Voeg 'q/api/' toe na de domeinnaam
                api_url = re.sub(r"www\.lidl\.nl/", "www.lidl.nl/q/api/", url)
        
        # Controleer of de URL al query parameters heeft
        if '?' in api_url:
            # Parameters zijn al aanwezig, voeg ontbrekende toe
            if "fetchsize=" not in api_url:
                api_url += "&fetchsize=48"
            if "locale=" not in api_url:
                api_url += "&locale=nl_NL"
            if "assortment=" not in api_url:
                api_url += "&assortment=NL"
            if "version=" not in api_url:
                api_url += "&version=2.1.0"
            if "idsOnly=" not in api_url:
                api_url += "&idsOnly=false"
            if "productsOnly=" not in api_url:
                api_url += "&productsOnly=true"
        else:
            # Geen parameters, voeg ze toe
            api_url += "?fetchsize=48&locale=nl_NL&assortment=NL&version=2.1.0&idsOnly=false&productsOnly=true"
        
        # Log de omgezette URL voor debug doeleinden
        logger.debug(f"Converted URL: {url} -> {api_url}")
        
        return api_url
    
    # Alias voor backwards compatibility
    convert_url_to_api_url = convert_url_to_api

    def get_fetch_size(self, url: str) -> int:
        """
        Bepaal de fetchsize uit een URL of gebruik de standaardwaarde.
        
        Args:
            url: De URL om de fetchsize uit te halen
            
        Returns:
            int: De fetchsize waarde
        """
        fetch_match = re.search(r"fetchsize=(\d+)", url)
        if fetch_match:
            return int(fetch_match.group(1))
        return self.default_fetch_size
    
    def execute_paginated_query(self, url: str) -> Tuple[List[ProductInfo], bool, int, Optional[str], Optional[int]]:
        """
        Voert een gepagineerde query uit, hanteert automatisch offset en fetchsize.
        
        Args:
            url: De basis URL (API of web) voor de query
            
        Returns:
            Tuple met:
            - Lijst met ProductInfo objecten
            - Boolean die aangeeft of de query succesvol was
            - Totaal aantal gevonden producten
            - Error message (indien aanwezig)
            - Response status code (indien aanwezig)
        """
        api_url = self.convert_url_to_api(url)
        fetch_size = self.get_fetch_size(api_url)
        
        offset = 0
        more_results = True
        all_products = []
        success = False
        error_message = None
        response_status = None
        
        while more_results:
            # Parameters voor deze pagina
            current_api_url = api_url
            
            # Pas offset parameter toe
            if "offset=" in current_api_url:
                current_api_url = re.sub(r"offset=\d+", f"offset={offset}", current_api_url)
            else:
                separator = '&' if '?' in current_api_url else '?'
                current_api_url += f"{separator}offset={offset}"
            
            logger.info(f"Querying with offset {offset}: {current_api_url}")
            
            # Haal producten op
            products = self.get_products(current_api_url)
            
            if products is None or len(products) == 0:
                # Als products None is, ging er iets mis
                logger.error(f"Failed to get products for URL {current_api_url}")
                
                if self.requester.last_response:
                    response_status = self.requester.last_response.status_code
                    error_message = f"Status code: {response_status}"
                else:
                    error_message = "No response received"
                
                break
            
            products_found = len(products)
            all_products.extend(products)
            
            if products_found > 0:
                success = True  # Als we minstens één product vonden, is de query succesvol
            
            # Als we minder producten kregen dan de fetchsize,
            # zijn er waarschijnlijk geen meer
            if products_found < fetch_size:
                more_results = False
            else:
                # Verhoog offset voor de volgende pagina
                offset += fetch_size
        
        return all_products, success, len(all_products), error_message, response_status
    
    def extract_products_from_response(self, response_data: Dict[str, Any]) -> List[ProductInfo]:
        """
        Extraheert productinformatie uit de Lidl API response.
        """
        products = []
        items = []
        
        # Bepaal waar de items zitten in de JSON structuur
        if isinstance(response_data, dict):
            # Zoek naar de producten in de response
            if "items" in response_data:
                items = response_data["items"]
            elif "products" in response_data:
                items = response_data["products"]
            elif "results" in response_data and "products" in response_data["results"]:
                items = response_data["results"]["products"]
        elif isinstance(response_data, list):
            # De response is al een lijst producten
            items = response_data
            
        for item in items:
            product = self._parse_product_item(item)
            if product:
                products.append(product)
                
        return products
    
    def _parse_product_item(self, item: Dict[str, Any]) -> Optional[ProductInfo]:
        """
        Verwerkt een enkel product-item uit de API response.
        """
        try:
            # Basisgegevens
            product_id = item.get('code', item.get('id', 'N/A'))
            name = item.get('label', item.get('name', 'N/A'))
            
            # Prijsinformatie
            price = None
            old_price = None
            recommended_price = None
            discount_amount = None
            discount_percentage = None
            
            # Probeer gridbox structuur voor prijsinfo
            if 'gridbox' in item and 'data' in item['gridbox'] and 'price' in item['gridbox']['data']:
                price_data = item['gridbox']['data']['price']
                price = price_data.get('price', 0.0)
                old_price = price_data.get('oldPrice', None)
                
                # De oldPrice gebruiken als recommended_price
                if old_price and old_price > 0:
                    recommended_price = old_price
                    
                    # Bereken de korting als er een oude prijs is die hoger is dan de huidige prijs
                    if price < old_price:
                        discount_amount = old_price - price
                        discount_percentage = (discount_amount / old_price) * 100
            
            # Fallback naar oudere structuur
            elif 'price' in item:
                price = item['price'].get('price', 0.0)
                old_price = item['price'].get('oldPrice', None)
                
                # De oldPrice gebruiken als recommended_price
                if old_price and old_price > 0:
                    recommended_price = old_price
                    
                    # Bereken de korting als er een oude prijs is die hoger is dan de huidige prijs
                    if price < old_price:
                        discount_amount = old_price - price
                        discount_percentage = (discount_amount / old_price) * 100
            
            # Afbeelding URL
            image_url = item.get('mouseoverImage', 'N/A')
            if not image_url or image_url == 'N/A':
                # Probeer beeld uit gridbox te halen
                if 'gridbox' in item and 'data' in item['gridbox']:
                    image_url = item['gridbox']['data'].get('image', 'N/A')
            
            # Product URL
            product_url = f"https://www.lidl.nl{item.get('canonicalUrl', 'N/A')}"
            # Als canonicalUrl niet bestaat, probeer uit gridbox te halen
            if product_url.endswith('N/A') and 'gridbox' in item and 'data' in item['gridbox']:
                canonical_path = item['gridbox']['data'].get('canonicalPath', '')
                if canonical_path:
                    product_url = f"https://www.lidl.nl{canonical_path}"
            
            # Extra informatie die specifiek is voor Lidl
            additional_info = {
                'brand': None,
                'fullTitle': None,
                'category': None
            }
            
            if 'gridbox' in item and 'data' in item['gridbox']:
                grid_data = item['gridbox']['data']
                if 'brand' in grid_data:
                    additional_info['brand'] = grid_data['brand'].get('name')
                additional_info['fullTitle'] = grid_data.get('fullTitle')
                additional_info['category'] = grid_data.get('category')
            
            # Maak een ProductInfo object
            return ProductInfo(
                id=product_id,
                name=name,
                price=price or 0.0,
                old_price=old_price,
                image_url=image_url,
                product_url=product_url,
                discount_amount=discount_amount,
                discount_percentage=discount_percentage,
                recommended_price=recommended_price,
                additional_info=additional_info
            )
        
        except Exception as e:
            logger.exception(f"Error parsing product item: {e}")
            return None
    
    def get_products(self, url: str, params: Dict[str, Any] = None) -> List[ProductInfo]:
        """
        Haalt producten op van Lidl API en verwerkt ze tot ProductInfo objecten.
        
        Args:
            url: De URL van de webpagina of API endpoint
            params: Extra parameters zoals offset, fetchsize, etc.
            
        Returns:
            Lijst met ProductInfo objecten
        """
        api_url = url
        if not api_url.startswith("http"):
            # Als de url niet met http begint, is het waarschijnlijk geen API URL
            api_url = self.convert_url_to_api(url)
        
        # Pas parameters toe zoals offset en fetchsize indien nodig
        if params:
            for key, value in params.items():
                if key == 'offset' and 'offset=' in api_url:
                    api_url = re.sub(r"offset=\d+", f"offset={value}", api_url)
                elif key == 'offset' and 'offset=' not in api_url:
                    separator = '&' if '?' in api_url else '?'
                    api_url += f"{separator}offset={value}"
                elif key == 'fetchsize' and 'fetchsize=' in api_url:
                    api_url = re.sub(r"fetchsize=\d+", f"fetchsize={value}", api_url)
                elif key == 'fetchsize' and 'fetchsize=' not in api_url:
                    separator = '&' if '?' in api_url else '?'
                    api_url += f"{separator}fetchsize={value}"
        
        # Maak de request
        response = self.requester.get(api_url)
        
        if not response or response.status_code != 200:
            logger.error(f"Failed to get data from {api_url}: {response.status_code if response else 'No response'}")
            return []
        
        try:
            data = response.json()
            return self.extract_products_from_response(data)
        except json.JSONDecodeError as e:
            logger.exception(f"Failed to parse JSON: {e}")
            return []
        except Exception as e:
            logger.exception(f"Error getting products: {e}")
            return []