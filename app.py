from flask import Flask, make_response, render_template, request, redirect, url_for, flash
import os
import secrets
from scraper import IMDScraper, OgimetScraper
from taf_generator import TafGenerator
from cleanup import run_automated_cleanup
import threading

app = Flask(__name__)
configured_secret = os.environ.get('FLASK_SECRET_KEY')
if os.environ.get('AUTO_TAF_ENV', 'development').lower() == 'production' and not configured_secret:
    raise RuntimeError('FLASK_SECRET_KEY must be configured in production.')
app.secret_key = configured_secret or secrets.token_urlsafe(32)

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
                                                            
    threading.Thread(target=run_automated_cleanup, daemon=True).start()

    station = request.form.get('station', 'VABB').upper()
    
    imd_scraper = IMDScraper()
    ogimet_scraper = OgimetScraper()
    generator = TafGenerator()

    imd_data = imd_scraper.fetch_data(station)
    
    ogimet_data = ogimet_scraper.fetch_data(station)

    error_msg = None
    debug_forms = None
    
    if "error" in imd_data:
        error_msg = f"IMD Error: {imd_data['error']}"
        debug_forms = imd_data.get('debug_forms', None)                                  
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

    response = make_response(render_template('index.html',
                         long_taf=long_taf,
                         short_taf=short_taf,
                         error=error_msg,
                         debug_forms=debug_forms,
                         last_station=station))
    response.headers['X-AutoTAF-IMD-Source'] = imd_data.get('_imd_download_status', 'unknown')
    if imd_data.get('_imd_model_issue_utc'):
        response.headers['X-AutoTAF-IMD-Issue-UTC'] = imd_data['_imd_model_issue_utc']
    return response

if __name__ == '__main__':
                                                                 
    app.run(debug=True, port=5000)
