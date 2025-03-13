"""
Basis klassen voor scrapers - deze definieert de interface die elke scraper moet implementeren.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Union, Tuple


@dataclass
class ProductInfo:
    """Generieke productinformatie, onafhankelijk van de bron."""
    id: str
    name: str
    price: float
    old_price: Optional[float] = None
    image_url: str = ""
    product_url: str = ""
    discount_amount: Optional[float] = None
    discount_percentage: Optional[float] = None
    recommended_price: Optional[float] = None
    additional_info: Dict[str, Any] = None


class BaseScraper(ABC):
    """Basis klasse voor alle scrapers."""
    
    @abstractmethod
    def convert_url_to_api_url(self, url: str) -> str:
        """Converteert een normale productpagina URL naar een API URL."""
        pass
    
    @abstractmethod
    def extract_products_from_response(self, response_data: Any) -> List[ProductInfo]:
        """Extraheert productinformatie uit de API response."""
        pass
    
    @abstractmethod
    def get_products(self, url: str, params: Dict[str, Any] = None) -> List[ProductInfo]:
        """Haalt producten op van de API en verwerkt ze tot ProductInfo objecten."""
        pass
    
    @abstractmethod
    def execute_paginated_query(self, url: str) -> Tuple[List[ProductInfo], bool, int, Optional[str], Optional[int]]:
        """
        Voert een gepagineerde query uit, inclusief automatisch doorbladeren waar nodig.
        
        Args:
            url: De basis URL voor de query (web of API)
            
        Returns:
            Tuple met:
            - Lijst met ProductInfo objecten
            - Boolean die aangeeft of de query succesvol was
            - Totaal aantal gevonden producten
            - Error message (indien aanwezig)
            - Response status code (indien aanwezig)
        """
        pass