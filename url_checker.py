#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import json
import logging
from typing import Dict, Any

from scrapers.lidl import LidlScraper

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def display_product_info(product, index):
    """
    Toont informatie over een product in een geformatteerde manier.
    """
    print(f"{index}. Product ID: {product.id}")
    print(f"   Naam: {product.name}")
    
    # Prijs informatie
    print(f"   Huidige prijs: €{product.price:.2f}" if product.price else "   Huidige prijs: Onbekend")
    
    # Korting informatie
    if product.old_price:
        discount_info = ""
        if product.discount_amount and product.discount_percentage:
            discount_info = f" (Korting: €{product.discount_amount:.2f}, {product.discount_percentage:.1f}%)"
        print(f"   Oude prijs: €{product.old_price:.2f}{discount_info}")
    else:
        print("   Oude prijs: Niet beschikbaar")
    
    # Extra informatie
    if product.additional_info and product.additional_info.get('brand'):
        print(f"   Merk: {product.additional_info['brand']}")
    
    print()

def select_scraper(url):
    """
    Selecteert de juiste scraper op basis van de URL.
    In de toekomst kan dit worden uitgebreid met extra scrapers voor andere winkels.
    """
    if "lidl.nl" in url:
        return LidlScraper()
    else:
        raise ValueError(f"Geen geschikte scraper gevonden voor URL: {url}")

def main():
    parser = argparse.ArgumentParser(description='URL checker voor webwinkels')
    parser.add_argument('url', help='De URL om te controleren')
    parser.add_argument('--detail', '-d', type=int, help='Toon details voor product nummer')
    parser.add_argument('--offset', '-o', type=int, default=0, help='Offset voor paginering')
    parser.add_argument('--fetchsize', '-f', type=int, default=48, help='Aantal resultaten per pagina')
    parser.add_argument('--dump', action='store_true', help='Dump alle product data als JSON')
    
    args = parser.parse_args()
    
    try:
        # Kies de juiste scraper op basis van de URL
        scraper = select_scraper(args.url)
        
        # Parameters opbouwen voor de scraper
        params: Dict[str, Any] = {
            'offset': args.offset,
            'fetchsize': args.fetchsize
        }
        
        # Toon de API URL (voor debug doeleinden)
        api_url = scraper.convert_url_to_api_url(args.url)
        print(f"API URL: {api_url}\n")
        
        # Haal producten op
        products = scraper.get_products(args.url, params)
        
        if not products:
            print("Geen producten gevonden.")
            return
            
        print(f"Gevonden producten: {len(products)}\n")
        
        # Als detail is opgegeven, toon alleen dat product
        if args.detail is not None:
            if 0 <= args.detail < len(products):
                selected_product = products[args.detail]
                print(f"Details voor product {args.detail}:\n")
                
                if args.dump:
                    # Dump alle informatie als JSON
                    # We moeten het ProductInfo object naar een dict converteren
                    product_dict = vars(selected_product)
                    print(json.dumps(product_dict, indent=2, default=str))
                else:
                    # Toon gedetailleerde productinformatie
                    display_product_info(selected_product, args.detail)
                    print(f"Product URL: {selected_product.product_url}")
                    print(f"Afbeelding: {selected_product.image_url}")
                    
                    if selected_product.additional_info:
                        print("\nExtra informatie:")
                        for key, value in selected_product.additional_info.items():
                            if value:
                                print(f"  {key}: {value}")
            else:
                print(f"Fout: geen product gevonden met index {args.detail}")
            return
        
        # Anders loop door alle items en toon basisinformatie
        if args.dump:
            # Dump alle producten als JSON
            products_list = [vars(p) for p in products]
            print(json.dumps(products_list, indent=2, default=str))
        else:
            for i, product in enumerate(products):
                display_product_info(product, i)
    
    except ValueError as e:
        print(f"Fout: {e}")
    except Exception as e:
        logger.exception(f"Onverwachte fout: {e}")
        print(f"Er is een fout opgetreden: {e}")

if __name__ == "__main__":
    main()