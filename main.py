import sys
import time
from scraper import IMDScraper, OgimetScraper
from taf_generator import TafGenerator

def main():
    print("=== TAF Generator Tool ===")
    print("Security Note: To avoid 'unauthorized access' flags on IMD, please log in via your browser first.")
    print("Then, copy the value of the 'PHPSESSID' cookie and paste it here.")
    
    session_id = input("\nEnter IMD PHPSESSID (or press Enter to skip if relying on public links): ").strip()
    
    imd_scraper = IMDScraper(session_cookie=session_id if session_id else None)
        
    station = input("\nEnter Station Code for Ogimet (e.g., VABB, VIDP): ").strip().upper()
    if not station:
        station = "VABB"

    ogimet_scraper = OgimetScraper()
    generator = TafGenerator()

    # Fetch Data
    print("\n--- Fetching Data ---")
    
    # 1. IMD
    print(f"Downloading data for {station}...")
    download_res = imd_scraper.download_data(station)
    if "error" in download_res:
        print(f"Download warning/error: {download_res['error']}")
        print("Attempting to read from local cache...")
    
    imd_data = imd_scraper.read_from_cache(station)
    if "error" in imd_data:
        print(f"Error reading IMD Data: {imd_data['error']}")
        sys.exit(1)
    print(f"IMD Data: {imd_data}")

    # 2. Ogimet
    ogimet_data = ogimet_scraper.fetch_data(station)
    if "error" in ogimet_data:
        print(f"Error fetching Ogimet Data: {ogimet_data['error']}")
        sys.exit(1)
    print(f"Ogimet Data: {ogimet_data}")

    # Generate TAFs
    print("\n--- Generated TAFs ---")
    
    long_taf = generator.generate_long_taf(imd_data, ogimet_data)
    print(f"\n[LONG TAF - 30 HR]\n{long_taf}")

    short_taf = generator.generate_short_taf(imd_data, ogimet_data)
    print(f"\n[SHORT TAF - 9 HR]\n{short_taf}")
    
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()
