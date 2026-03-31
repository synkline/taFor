import requests
from bs4 import BeautifulSoup
import re
import datetime
import time
import random
import os

class OgimetScraper:
    def __init__(self):
        self.base_url = "https://www.ogimet.com/display_metars2.php"

    def fetch_data(self, station_code):
        now = datetime.datetime.utcnow()
        start = now - datetime.timedelta(hours=24)                    
        
        params = {
            'lang': 'en',
            'lugar': station_code,
            'tipo': 'ALL',
            'ord': 'REV',
            'nil': 'SI',
            'fmt': 'html',
            'ano': start.year,
            'mes': start.month,
            'day': start.day,
            'hora': start.hour,
            'anof': now.year,
            'mesf': now.month,
            'dayf': now.day,
            'horaf': now.hour,
            'minf': now.minute,
            'send': 'send'
        }

        print(f"[Ogimet] Fetching data for {station_code}...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            response = requests.get(self.base_url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
        except requests.RequestException as e:
            return {"error": f"Network error: {e}"}

        soup = BeautifulSoup(response.content, 'lxml')
        
        tables = soup.find_all('table')
                                      
        tables = soup.find_all('table')
        metar_list = []
        
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 3:
                                                                   
                    date_text = cols[1].get_text(strip=True)
                                                       
                    content_text = cols[2].get_text(strip=True)
                    
                    if "METAR" in content_text or "SPECI" in content_text:
                        metar_data = self._parse_metar_row(cols)
                        if metar_data:
                            metar_list.append(metar_data)
        
        if metar_list:
            latest = metar_list[0]
            latest['station'] = station_code                            
            latest['history'] = {m['dt']: m for m in metar_list}                                     
            return latest
        
        with open(os.path.join(os.getcwd(), "debug_ogimet.html"), "w", encoding="utf-8") as f:
            f.write(soup.prettify())
            
        return {"error": "No valid METAR data rows found. HTML dumped to debug_ogimet.html"}

    def _parse_metar_row(self, cols):
        try:
            date_text = cols[1].get_text(strip=True).replace("->", "").strip()                   
            metar_text = cols[2].get_text(" ", strip=True)
            
            try:
                dt = datetime.datetime.strptime(date_text, "%d/%m/%Y %H:%M")
            except ValueError:
                return None

            vis_match = re.search(r'\b(\d{4})\b|\b(CAVOK)\b', metar_text)
            vis_val = "N/A"
            if vis_match:
                vis_val = vis_match.group(1) if vis_match.group(1) else vis_match.group(2)
            
            clouds = re.findall(r'\b((?:FEW|SCT|BKN|OVC)\d{3})\b|\b(NSC|SKC)\b', metar_text)
            cloud_str = "N/A"
            
            if clouds:
                                                                                       
                c_list = [c[0] if c[0] else c[1] for c in clouds if c[0] or c[1]]
                cloud_str = " ".join(c_list)
            
            if vis_val == "CAVOK" and (cloud_str == "N/A" or not cloud_str):
                cloud_str = "NSC"
            
            return {
                "source": "Ogimet",
                                                               
                "dt": dt,
                "visibility_raw": vis_val,
                "clouds_raw": cloud_str,
                "raw_metar": metar_text
            }
        except Exception:
            return None

class IMDScraper:
    def __init__(self, session_cookie=None):
        self.session = requests.Session()
        
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Upgrade-Insecure-Requests": "1"
        })
                                                                                              
        if session_cookie:
            self.session.cookies.set("PHPSESSID", session_cookie)
        
        self.url = "https://nwp.imd.gov.in/gfs_taf.php"

    def _get_with_retry(self, url, timeout=10, retries=6):
        """
        Executes a GET request with more aggressive exponential backoff retry logic
        specifically to handle IMD's frequent connection resets.
        """
        for i in range(retries):
            try:
                response = self.session.get(url, timeout=timeout)
                return response
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError) as e:
                if i < retries - 1:
                                                               
                    sleep_time = (2 ** i) * 1.5 + random.uniform(1, 3)
                    print(f"[IMD] Server busy/reset connection ({type(e).__name__}). Retrying ({i+1}/{retries}) in {sleep_time:.2f}s...")
                    time.sleep(sleep_time)
                else:
                    print(f"[IMD] Max retries reached for {url}.")
                    raise e
        return None
        
    def fetch_data(self, station_code=None):
        """
        Fetches data. Tries online download first, then falls back to local cache.
        """
        station = station_code.upper() if station_code else "VABB"
        
        download_result = self.download_data(station)
        if "error" not in download_result:
             print(f"[IMD] Successfully downloaded latest data for {station}.")
        else:
             print(f"[IMD] Online download failed: {download_result['error']}")
             print("[IMD] Attempting to read from local cache...")

        return self.read_from_cache(station)

    def download_data(self, station_code):
        """
        Crawls IMD site to find the data file and saves it locally.
        """
        station = station_code.upper()
                                       
        cache_dir = os.path.join(os.getcwd(), "imd_cache")
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
            
        print(f"[IMD] Searching for station '{station}' to download...")

        base_url = "https://nwp.imd.gov.in"
        
        station_mwo_map = {
                        
            "VABB": "tafstnmum.html",
            "VANM": "tafstnmum.html",
            "VAAU": "tafstnmum.html",
            "VASD": "tafstnmum.html",
            "VAJJ": "tafstnmum.html",
            "VAKP": "tafstnmum.html",
                                               
            "VOGA": "tafstnchen.html", 
            "GOA": "tafstnchen.html",
            "VOSR": "tafstnchen.html", 
            "SINDHUDURG": "tafstnchen.html",
            "VOND": "tafstnchen.html",
            "NANDED": "tafstnchen.html" 
        }
        
        start_page = station_mwo_map.get(station, "tafstndel.html")
        
        visited = set()
        queue = [start_page]
        max_pages = 6
        
        found_url = None
        
        while queue and len(visited) < max_pages:
            current_page = queue.pop(0)
            if current_page in visited: continue
            visited.add(current_page)
            
            full_url = f"{base_url}/{current_page}"
            print(f"[IMD] checking page: {current_page}")
            
            try:
                response = self._get_with_retry(full_url, timeout=10)
                if response and "login" in response.url:
                     return {"error": "Authentication Failed. Please check PHPSESSID."}
            except Exception as e:
                print(f"[IMD] Failed to load {current_page}: {e}")
                continue

            soup = BeautifulSoup(response.content, 'lxml')
            
            name_map = {
                "VOGA": "VOGA-GOA",
                "VOSR": "SINDHUDURG",
                "VOND": "NANDED"
            }
            station_name = name_map.get(station, "")
            
            select = soup.find('select', attrs={'name': 'ac'})
            target_value = None
            if select:
                for opt in select.find_all('option'):
                    txt = opt.get_text(strip=True).upper()
                    val = opt.get('value').upper()
                    
                    match_code = (station in val)
                    match_name = (station_name and station_name in txt)
                    
                    if match_code or match_name:
                        target_value = opt.get('value')                                    
                        break
            
            if target_value:
                                                                      
                if "/" in target_value and (".txt" in target_value or "gfs" in target_value):
                     if target_value.startswith("/"):
                        found_url = f"https://nwp.imd.gov.in{target_value}"
                     else:
                        found_url = f"https://nwp.imd.gov.in/{target_value}"
                     break
                else:
                                                                                                   
                    return self._submit_and_save(full_url, target_value, station)

            links = soup.find_all('a')
            for a in links:
                href = a.get('href')
                if href and 'tafstn' in href and 'html' in href:
                    page_name = href.split('/')[-1]
                    if page_name not in visited and page_name not in queue:
                        queue.append(page_name)
        
        if found_url:
             return self._download_url_to_file(found_url, station)
        
        return {"error": f"Station '{station}' not found in any MWO region pages."}

    def _save_with_versioning(self, content, station):
        """
        Parses content for 'BASED ON' timestamp and saves a copy.
        """
        try:
                             
            text = content.decode('utf-8', errors='ignore') if isinstance(content, bytes) else content
            
            import re
            match = re.search(r'BASED\s+ON\s+(\d+)\s+UTC\s+of\s+(\d+)', text, re.IGNORECASE)
            
            if match:
                hour = match.group(1).zfill(2)          
                date_str = match.group(2)                     
                
                versioned_filename = f"{station.upper()}_{date_str}_{hour}UTC.txt"
                
                cache_root = os.path.join(os.getcwd(), "imd_cache")
                station_dir = os.path.join(cache_root, station.upper())
                
                if not os.path.exists(station_dir):
                    os.makedirs(station_dir)
                    
                versioned_path = os.path.join(station_dir, versioned_filename)
                
                if not os.path.exists(versioned_path):
                    with open(versioned_path, "wb") as f:
                         f.write(content if isinstance(content, bytes) else content.encode('utf-8'))
                    print(f"[IMD] Versioned copy saved: {versioned_path}")
                else:
                    print(f"[IMD] Versioned copy already exists: {versioned_filename}")
            else:
                print("[IMD] Could not find 'BASED ON' timestamp for versioning.")
                return None
                
            return versioned_path
        except Exception as e:
            print(f"[IMD] Failed to save versioned copy: {e}")
            return None

    def _download_url_to_file(self, url, station):
        try:
            print(f"[IMD] Downloading from {url}...")
            response = self._get_with_retry(url, timeout=15)
            response.raise_for_status()
            
            saved_path = self._save_with_versioning(response.content, station)
            
            if saved_path:
                return {"success": True, "path": saved_path}
            else:
                return {"error": "Could not determine timestamp from file content."}
        except Exception as e:
            return {"error": f"Download failed: {e}"}

    def _submit_and_save(self, url, station_value, station):
                                    
        try:
            headers = {"Referer": url, "Origin": "https://nwp.imd.gov.in"}
            payload = {'ac': station_value, 'submit': 'submit'}
            
            response = self.session.post(url, data=payload, headers=headers, timeout=15)
            response.raise_for_status()
            
            saved_path = self._save_with_versioning(response.content, station)
            
            if saved_path:
                 return {"success": True, "path": saved_path}
            else:
                 return {"error": "Could not determine timestamp to save file."}
        except Exception as e:
            return {"error": f"Form submission failed: {e}"}

    def read_from_cache(self, station_code):
        import glob
                               
        station = station_code.upper()
                                                
        cache_dir = os.path.join(os.getcwd(), "imd_cache", station)
        
        pattern = os.path.join(cache_dir, f"{station}_*UTC.txt")
        files = glob.glob(pattern)
        
        target_file = None
        if not files:
                                                                 
             fallback_pattern = os.path.join(os.getcwd(), "imd_cache", f"{station}_*UTC.txt")
             files = glob.glob(fallback_pattern)
             
             if not files:
                 return {"error": f"No cached data found for {station}."}
        
        files.sort(reverse=True)
        target_file = files[0]
             
        try:
            print(f"[IMD] Reading from cache: {os.path.basename(target_file)}")
            with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            if "<html>" in content.lower() or "<table" in content.lower():
                 soup = BeautifulSoup(content, 'lxml')
                 return self._parse_data_table(soup)
            else:
                                                                                  
                 return self._parse_text_response(content)
        except Exception as e:
            return {"error": f"Failed to read cache: {e}"}

    def _parse_text_response(self, text):
                                                                     
        lines = text.strip().splitlines()
        if not lines: return {"error": "Empty text response"}
        
        header_idx = -1
        headers = []
        for i, line in enumerate(lines):
            if "Time" in line and "Dir" in line:
                header_idx = i
                raw_headers = line.split()
                                                                
                headers = [h for h in raw_headers if h != "&"]
                                                               
                break
        
        if header_idx == -1:
            return {"error": "Could not find headers in text file."}
        
        map_idx = {}
        for idx, h in enumerate(headers):
            h_low = h.lower()
            if "time" in h_low and "utc" in h_low: map_idx["Time"] = idx
            elif "time" in h_low: map_idx["Time"] = idx           
            elif "dir" in h_low and "deg" in h_low: map_idx["Dir"] = idx
            elif "ws" in h_low and "kts" in h_low and "gust" not in h_low: map_idx["WS"] = idx
            elif "gust" in h_low and "kts" in h_low: map_idx["Gust"] = idx
            elif "rh" in h_low and "%" in h_low: map_idx["RH"] = idx
            elif "rain" in h_low and "mm" in h_low: map_idx["Rain"] = idx
            elif "lcb" in h_low and "octa" in h_low: map_idx["LCB"] = idx 
            elif "ccb" in h_low and "octa" in h_low: map_idx["CCB"] = idx
            
        if "Time" not in map_idx:
            return {"error": f"Missing 'Time' column. Headers: {headers}"}

        now = datetime.datetime.utcnow()
        curr_day = now.day
        curr_hour = now.hour
        
        t_current = f"{curr_day:02d}{curr_hour:02d}"
        t_next = f"{curr_day:02d}{(curr_hour+1)%24:02d}"
        t_prev = f"{curr_day:02d}{(curr_hour-1)%24:02d}"
        
        best_row = None
        match_type = None 
        
        forecast_entries = []
        
        for i in range(header_idx + 1, len(lines)):
            line = lines[i].strip()
            if not line or line.startswith("-") or line.startswith("="):
                continue
            
            if line[0].isdigit():
                parts = line.split()
                
                if not parts: continue
                time_code = parts[0]
                
                row_data = {}
                for key, idx in map_idx.items():
                    if idx < len(parts):
                        row_data[key] = parts[idx]
                    else:
                        row_data[key] = ""
                forecast_entries.append(row_data)

                if t_current in time_code:
                    best_row = row_data
                    match_type = 'curr'
                    
                elif t_next in time_code:
                    if match_type != 'curr': 
                        best_row = row_data
                        match_type = 'next'
                
                elif t_prev in time_code:
                    if match_type is None:
                         best_row = row_data
                         match_type = 'prev'
        
        if not best_row:
                                             
              if forecast_entries:
                  best_row = forecast_entries[0]
        
        if not best_row:
             return {"error": "No valid data rows found after header."}
        
        result = best_row.copy()
        result["forecast"] = forecast_entries
        
        return result

    def _parse_data_table(self, soup):
        tables = soup.find_all('table')
        if not tables:
             return {"error": "No tables in result"}

        target_table = None
        field_map = {}
        
        for tbl in tables:
            rows = tbl.find_all('tr')
            if not rows: continue
            
            for r_idx in range(min(5, len(rows))):
                cols = rows[r_idx].find_all(['th', 'td'])
                current_headers = [c.get_text(strip=True).upper() for c in cols]
                
                matches = 0
                temp_map = {
                    "TIME": -1, "DIR": -1, "WS": -1, "RH": -1, "RAIN": -1, "LCB": -1, "CCB": -1
                }
                
                for idx, h in enumerate(current_headers):
                    h_clean = h.replace(" ", "").replace("\n", "")
                    if "TIME" in h_clean or "UTC" in h_clean: temp_map["TIME"] = idx; matches += 1
                    elif "DIR" in h_clean: temp_map["DIR"] = idx; matches += 1
                    elif "WS" in h_clean: temp_map["WS"] = idx; matches += 1
                    elif "RH" in h_clean: temp_map["RH"] = idx; matches += 1
                    elif "RAIN" in h_clean: temp_map["RAIN"] = idx; matches += 1
                    elif "LCB" in h_clean: temp_map["LCB"] = idx; matches += 1
                    elif "CCB" in h_clean: temp_map["CCB"] = idx; matches += 1
                
                if matches >= 3:
                     target_table = tbl
                     field_map = temp_map
                     self.header_row_index = r_idx
                     break
            if target_table: break
            
        if not target_table:
            return {"error": "No matching data table in result."}
            
        rows = target_table.find_all('tr')
        try:
                                        
            if len(rows) <= self.header_row_index + 1:
                return {"error": "Table empty (no data rows)."}
                
            data_row = rows[self.header_row_index + 1].find_all('td')
            
            def get_val(key):
                idx = field_map.get(key, -1)
                if idx != -1 and idx < len(data_row):
                    return data_row[idx].get_text(strip=True)
                return ""
            
            return {
                "Time": get_val("TIME"),
                "Dir": get_val("DIR"),
                "WS": get_val("WS"),
                "RH": get_val("RH"),
                "Rain": get_val("RAIN"),
                "LCB": get_val("LCB"),
                "CCB": get_val("CCB"),
                "forecast": [] 
            }
        except Exception as e:
            return {"error": f"Extraction failed: {e}"}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("station", nargs="?", default="VABB", help="Station code (e.g., VIDP, VABB)")
    parser.add_argument("--cookie", help="PHPSESSID cookie")
    args = parser.parse_args()
    
    scraper = IMDScraper(session_cookie=args.cookie)
    data = scraper.fetch_data(args.station)
    print("\n--- Result ---")
    print(data)

