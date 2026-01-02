import re

def test_parse(metar_text):
    print(f"Testing: '{metar_text}'")
    vis_match = re.search(r'\b(\d{4})\b|\b(CAVOK)\b', metar_text)
    vis_val = "N/A"
    if vis_match:
        vis_val = vis_match.group(1) if vis_match.group(1) else vis_match.group(2)
    print(f"  Vis: {vis_val}")

    clouds = re.findall(r'\b((?:FEW|SCT|BKN|OVC)\d{3})\b|\b(NSC|SKC)\b', metar_text)
    cloud_str = "N/A"
    
    if clouds:
        c_list = [c[0] if c[0] else c[1] for c in clouds if c[0] or c[1]]
        cloud_str = " ".join(c_list)
    
    if vis_val == "CAVOK" and (cloud_str == "N/A" or not cloud_str):
        cloud_str = "NSC"
    print(f"  Clouds: {cloud_str}")
    print("-" * 20)

samples = [
    "METAR VABB 290500Z 08005KT 4000 FU NSC 30/20 Q1012 NOSIG", # Standard
    "METAR VABB 290500Z 08005KT 0800 FU NSC 30/20 Q1012",       # Low Vis
    "METAR VABB 290500Z 00000KT CAVOK 30/20 Q1011",             # CAVOK
    "METAR VABB 290500Z 12003KT 5000 HZ FEW030 31/22 Q1012",    # Clouds
    "METAR VABB 290500Z 0805KT 3000 FU",                        # Missing Clouds
    "METAR VABB 290500Z 30010KT 9999 HZ",                       # No cloud group
]

for s in samples:
    test_parse(s)
