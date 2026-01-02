from flask import Flask, render_template, request, redirect, url_for, flash
import os
from scraper import IMDScraper, OgimetScraper
from taf_generator import TafGenerator

app = Flask(__name__)
app.secret_key = 'super_secret_taf_key'  # Needed for flash messages

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    imd_cookie = request.form.get('imd_cookie')
    station = request.form.get('station', 'VABB').upper()
    
    # Initialize Scrapers
    imd_scraper = IMDScraper(session_cookie=imd_cookie)
    ogimet_scraper = OgimetScraper()
    generator = TafGenerator()

    # Fetch Data
    # IMD
    imd_data = imd_scraper.fetch_data(station)
    
    # Ogimet
    ogimet_data = ogimet_scraper.fetch_data(station)

    # Check for critical errors (blocking TAF generation)
    # We allow partial generation if possible, but usually TAF needs both.
    
    error_msg = None
    debug_forms = None
    
    if "error" in imd_data:
        error_msg = f"IMD Error: {imd_data['error']}"
        debug_forms = imd_data.get('debug_forms', None) # Get debug forms if available
        if debug_forms:
            print("\n[DEBUG info for Developer]")
            print(str(debug_forms))
            print("[End Debug info]\n")
    elif "error" in ogimet_data:
        error_msg = f"Ogimet Error: {ogimet_data['error']}"
    
    long_taf = ""
    short_taf = ""
    
    if not error_msg:
        try:
            long_taf = generator.generate_long_taf(imd_data, ogimet_data)
            short_taf = generator.generate_short_taf(imd_data, ogimet_data)
        except Exception as e:
            error_msg = f"Generation Error: {str(e)}"

    return render_template('index.html', 
                         long_taf=long_taf, 
                         short_taf=short_taf, 
                         error=error_msg, 
                         debug_forms=debug_forms,
                         last_cookie=imd_cookie,
                         last_station=station,
                         imd_raw=imd_data if "error" not in imd_data else None,
                         ogimet_raw=ogimet_data if "error" not in ogimet_data else None)

if __name__ == '__main__':
    # Run slightly verbose for dev
    app.run(debug=True, port=5000)
