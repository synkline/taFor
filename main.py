import sys
from scraper import IMDScraper, OgimetScraper
from taf_generator import TafGenerator

def main():
    print("=== TAF Generator Tool ===")
    
    station = input("\nEnter Station Code (e.g., VABB, VIDP) [Default: VABB]: ").strip().upper()
    if not station:
        station = "VABB"

    imd_scraper = IMDScraper()
    ogimet_scraper = OgimetScraper()
    generator = TafGenerator()

    print("\n--- Fetching Data ---")
    
    imd_data = imd_scraper.fetch_data(station)
    if "error" in imd_data:
        print(f"Error fetching IMD Data: {imd_data['error']}")
        input("Press Enter to exit...")
        sys.exit(1)

    ogimet_data = ogimet_scraper.fetch_data(station)
    if "error" in ogimet_data:
        print(f"Error fetching Ogimet Data: {ogimet_data['error']}")
        input("Press Enter to exit...")
        sys.exit(1)

    print("\n--- Generated TAFs ---")
    
    try:
        long_taf = generator.generate_long_taf(imd_data, ogimet_data)
        print(f"\n[LONG TAF - 30 HR]\n{long_taf}")

        short_taf = generator.generate_short_taf(imd_data, ogimet_data)
        print(f"\n[SHORT TAF - 9 HR]\n{short_taf}")
    except Exception as e:
        print(f"Error generating TAF: {e}")
    
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()
