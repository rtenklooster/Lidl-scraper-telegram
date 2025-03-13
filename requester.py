import requests
import logging
import ua_generator

logger = logging.getLogger(__name__)

class LidlRequester:
    def __init__(self, max_retries=3):
        self.max_retries = max_retries
        self.session = requests.Session()
        self.last_response = None
        self.set_user_agent()

    def set_user_agent(self):
        """Genereer en zet een nieuwe User-Agent."""
        ua = str(ua_generator.generate())
        self.session.headers.update({"User-Agent": ua})
        logger.info(f"Generated User-Agent: {ua}")

    def get(self, url, params=None):
        """Voer een GET-request uit met herhaalde pogingen."""
        for attempt in range(self.max_retries):
            self.set_user_agent()
            try:
                response = self.session.get(url, params=params)
                # Bewaar laatste response voor foutanalyse
                self.last_response = response
                
                if response.status_code == 200:
                    return response
                logger.warning(
                    f"GET {url} attempt {attempt+1}/{self.max_retries} failed: {response.status_code}"
                )
            except requests.RequestException as e:
                logger.error(f"GET {url} attempt {attempt+1}/{self.max_retries} error: {e}")
                self.last_response = None
        logger.error(f"Max retries ({self.max_retries}) reached for GET {url}")
        return None

    def post(self, url, data=None):
        """Voer een POST-request uit."""
        self.set_user_agent()
        try:
            response = self.session.post(url, data=data)
            # Bewaar laatste response voor foutanalyse
            self.last_response = response
            
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            logger.error(f"POST {url} error: {e}")
            return None