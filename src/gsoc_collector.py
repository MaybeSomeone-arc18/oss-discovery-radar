import requests
import time
from src.config import GSOC_YEARS
from src.database import save_organization, save_gsoc_project, init_db

def fetch_gsoc_organizations():
    print("Starting GSoC Historical Collector from api.gsocorganizations.dev...")
    init_db()
    
    headers = {
        "User-Agent": "OSS-Discovery-Radar/2.0"
    }

    for year in GSOC_YEARS:
        print(f"Fetching GSoC data for year {year}...")
        url = f"https://api.gsocorganizations.dev/{year}.json"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                print(f"  [!] Failed to fetch {year} (Status: {response.status_code}). Maybe data is unavailable for this year.")
                continue
            
            data = response.json()
            orgs = data.get('organizations', [])
            if not isinstance(orgs, list):
                print(f"  [!] Unexpected data format for {year}.")
                continue
                
            print(f"  Found {len(orgs)} organizations for {year}. Saving to database...")
            
            projects_count = 0
            for org in orgs:
                # The public API provides 'name' but sometimes no distinct 'slug'. 
                # We can generate a slug from the name if 'slug' doesn't exist, or use url as slug fallback.
                # Looking at sample response, there is no explicit slug. The URL or a slugified name works.
                # Actually, the API response has 'projects_url' which usually ends in /org_slug.
                # Or we can just use the name as slug. Let's create a basic slug from the name.
                raw_name = org.get('name', '')
                if not raw_name:
                    continue
                
                slug = org.get('slug')
                if not slug:
                    slug = raw_name.lower().replace(' ', '-').replace('/', '-')
                    
                website = org.get('url', '')
                save_organization(slug, raw_name, website, year)
                
                # Projects
                projects = org.get('projects', [])
                for proj in projects:
                    title = proj.get('title')
                    if not title:
                        continue
                        
                    techs = proj.get('technologies', [])
                    techs_str = ",".join(techs) if isinstance(techs, list) else str(techs)
                    
                    save_gsoc_project(
                        org_slug=slug,
                        year=year,
                        title=title,
                        description=proj.get('description'),
                        short_description=proj.get('short_description'),
                        contributor=proj.get('student_name'),
                        url=proj.get('project_url'),
                        code_url=proj.get('code_url'),
                        technologies=techs_str
                    )
                    projects_count += 1
            
            print(f"  Saved {projects_count} projects for {year}.")
            
        except Exception as e:
            print(f"  [!] Error fetching data for {year}: {e}")
        
        # Be polite to the API
        time.sleep(1)
        
    print("GSoC Historical Data collection completed.")
