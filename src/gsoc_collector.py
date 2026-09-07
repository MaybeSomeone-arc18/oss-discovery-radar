import requests
import time
from src.config import GSOC_YEARS
from src.database import save_organization, init_db

def fetch_gsoc_organizations():
    print("Starting GSoC Historical Collector...")
    init_db()
    
    headers = {
        "User-Agent": "OSS-Discovery-Radar/1.0"
    }

    for year in GSOC_YEARS:
        print(f"Fetching GSoC organizations for year {year}...")
        url = f"https://summerofcode.withgoogle.com/api/program/{year}/organizations/"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                print(f"  [!] Failed to fetch {year} (Status: {response.status_code}). Maybe data is unavailable or API changed.")
                continue
            
            orgs = response.json()
            if not isinstance(orgs, list):
                print(f"  [!] Unexpected data format for {year}.")
                continue
                
            print(f"  Found {len(orgs)} organizations for {year}. Saving to database...")
            
            for org in orgs:
                slug = org.get('slug')
                name = org.get('name')
                website = org.get('website_url')
                
                if slug and name:
                    save_organization(slug, name, website, year)
            
        except Exception as e:
            print(f"  [!] Error fetching data for {year}: {e}")
        
        # Be polite to the API
        time.sleep(1)
        
    print("GSoC Historical Data collection completed.")
