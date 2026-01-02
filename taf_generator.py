import datetime

class TafGenerator:
    def __init__(self):
        pass

    def _get_standard_issue_time(self):
        """
        Returns the closest standard TAF issue time (05, 11, 17, 23 UTC)
        and the corresponding issue datetime object.
        """
        now = datetime.datetime.utcnow()
        candidates = [5, 11, 17, 23]
        
        # Find closest hour
        current_hour = now.hour
        best_hour = candidates[0]
        min_diff = 24
        
        for h in candidates:
            diff = abs(h - current_hour)
            if diff < min_diff:
                min_diff = diff
                best_hour = h
        
        # Proper slot allocation
        if 2 <= current_hour < 8: best_hour = 5
        elif 8 <= current_hour < 14: best_hour = 11
        elif 14 <= current_hour < 20: best_hour = 17
        else: best_hour = 23
        
        issue_dt = now.replace(hour=best_hour, minute=0, second=0, microsecond=0)
        return issue_dt.strftime("%d%H%M") + "Z", issue_dt

    def _round_to_nearest_10(self, val):
        try:
            val = int(float(val))
            rounded = round(val / 10) * 10
            if rounded == 0: return "360" # Prefer 360 for direction unless 00000KT
            if rounded == 360: return "360"
            return f"{rounded:03d}"
        except (ValueError, TypeError):
            return "000"

    def _format_wind(self, d_str, s_str, g_str="0"):
        """
        Formats wind string based on rules:
        - Round Dir to nearest 10.
        - If Speed <= 3 KT -> VRB03KT (or VRBxxKT).
        - If Speed >= 15 KT or Gust >= 17 KT -> GxxKT.
        """
        try:
            d_val = int(float(d_str or 0))
            s_val = int(float(s_str or 0))
            g_val = int(float(g_str or 0))
            
            # 1. Round Direction
            rounded_dir = round(d_val / 10) * 10
            if rounded_dir == 0: rounded_dir = 360 
            if rounded_dir == 360: rounded_dir = 360 # Explicit
            
            d_final = f"{rounded_dir:03d}"
            
            # 2. VRB Logic (Speed <= 3)
            # Rule: "if wspd =< 3KT then, wind = VRB03KT" (using example style or just VRB + speed)
            if s_val <= 3:
                d_final = "VRB"
            
            # 3. Gust Logic
            # "If wspd >= 15KT or wgust >= 17KT"
            gust_part = ""
            if s_val >= 15 or g_val >= 17:
                # Ensure gust > speed
                if g_val > s_val:
                    gust_part = f"G{g_val:02d}"
            
            return f"{d_final}{s_val:02d}{gust_part}KT"
            
        except (ValueError, TypeError):
            return "00000KT"

    def _get_projected_conditions(self, entry):
        """
        Estimates Vis, Weather, Clouds based on IMD Forecast Data.
        Rules:
        - Rain > 0: Check intensity.
        - Rain = 0: Check RH for FU/HZ/BR.
          - RH <= 60: FU
          - 60 < RH <= 75: HZ
          - RH > 75: BR
        """
        # Defaults
        vis = "5000" # Forecast default?
        wx = []
        clouds = [] 
        
        try:
            rh = float(entry.get('RH', '0'))
            rain = float(entry.get('Rain', '0'))
            ws = float(entry.get('WS', '0'))
            lcb = float(entry.get('LCB', '0'))
            ccb = float(entry.get('CCB', '0'))
            
            # --- Weather & Vis ---
            if rain > 0:
                # Rain Logic
                if rain > 10: 
                    vis = "1000"
                    wx.append("+RA")
                elif rain > 2.5:
                    vis = "3000"
                    wx.append("RA")
                else: 
                    vis = "4000"
                    wx.append("-RA")
            elif rain == 0:
                # No Rain - Strict RH Rules
                # 1. RH <= 60 -> FU (Smoke)
                if rh <= 60:
                    vis = "4000" 
                    wx.append("FU")
                # 2. 60 < RH <= 75 -> HZ (Haze)
                elif rh <= 75:
                    vis = "4000" 
                    wx.append("HZ")
                # 3. RH > 75 -> Mist (BR) or Fog (FG)
                else:
                    # If RH is very high, assume Fog
                    if rh >= 95:
                        vis = "0800"
                        wx.append("FG")
                    else:
                        vis = "2000"
                        wx.append("BR")
                    
            # --- Clouds ---
            # Mapping Octas (0-8) to Cloud Amount
            # 1-2: FEW, 3-4: SCT, 5-7: BKN, 8: OVC
            def get_cloud_str(octas, height_str):
                # height_str should be 3 digits (e.g. "018" for 1800ft)
                if octas < 1: return None
                if octas <= 2: amt = "FEW"
                elif octas <= 4: amt = "SCT"
                elif octas <= 7: amt = "BKN"
                else: amt = "OVC"
                return f"{amt}{height_str}"

            # Low Clouds (LCB) 
            c1 = get_cloud_str(lcb, "020")
            if c1: clouds.append(c1)
            
            # Convective (CCB) 
            c2 = get_cloud_str(ccb, "100") 
            if c2: clouds.append(c2)
            
            if not clouds:
                cloud_str = "NSC"
            else:
                cloud_str = " ".join(clouds)
            
            wx_str = " ".join(wx)
            return vis, wx_str.strip(), cloud_str
            
        except Exception:
            return "5000", "HZ", "NSC"

    def _extract_historical_height(self, target_dt, history):
        """
        Finds the cloud height from a METAR ~24 hours prior.
        """
        if not history: return None
        
        best_dt = None
        min_diff = datetime.timedelta(hours=999)
        
        for dt_key in history.keys():
            diff = abs(dt_key - target_dt)
            if diff < min_diff:
                min_diff = diff
                best_dt = dt_key
                
        # Only accept if within reasonable window (e.g. +/- 1.5 hours)
        if min_diff > datetime.timedelta(minutes=90):
            return None
            
        metar_data = history.get(best_dt)
        if not metar_data: return None
        
        # Parse Cloud String from METAR (e.g. "FEW030 SCT100")
        c_raw = metar_data.get('clouds_raw', '')
        # Pattern: 3 letters + 3 digits (e.g. FEW030)
        import re
        matches = re.findall(r'[A-Z]{3}(\d{3})', c_raw)
        if matches:
            return matches[0] # Return first layer height
        return None

    def _get_projected_conditions(self, entry, forecast_dt=None, history=None):
        """
        Estimates Vis, Weather, Clouds based on IMD Forecast Data.
        """
        # Defaults
        vis = "5000" 
        wx = []
        clouds = [] 
        
        try:
            rh = float(entry.get('RH', '0'))
            rain = float(entry.get('Rain', '0'))
            ws = float(entry.get('WS', '0'))
            lcb = float(entry.get('LCB', '0'))
            ccb = float(entry.get('CCB', '0'))
            
            # --- Weather & Vis ---
            if rain > 0:
                # Rain Logic
                if rain > 10: 
                    vis = "1000"
                    wx.append("+RA")
                elif rain > 2.5:
                    vis = "3000"
                    wx.append("RA")
                else: 
                    vis = "4000"
                    wx.append("-RA")
            elif rain == 0:
                # No Rain - Strict RH Rules
                # 1. RH <= 60 -> FU (Smoke)
                if rh <= 60:
                    vis = "4000" 
                    wx.append("FU")
                # 2. 60 < RH <= 75 -> HZ (Haze)
                elif rh <= 75:
                    vis = "4000" 
                    wx.append("HZ")
                # 3. RH > 75 -> Mist (BR) or Fog (FG)
                else:
                    # If RH is very high, assume Fog
                    if rh >= 95:
                        vis = "0800"
                        wx.append("FG")
                    else:
                        vis = "2000"
                        wx.append("BR")
                    
            # --- Clouds ---
            # Mapping Octas (0-8) to Cloud Amount
            # 1-2: FEW, 3-4: SCT, 5-7: BKN, 8: OVC
            def get_cloud_str(octas, height_str):
                # height_str should be 3 digits (e.g. "018" for 1800ft)
                if octas < 1: return None
                if octas <= 2: amt = "FEW"
                elif octas <= 4: amt = "SCT"
                elif octas <= 7: amt = "BKN"
                else: amt = "OVC"
                return f"{amt}{height_str}"
            
            # Historical Height Lookup
            hist_height = None
            if (lcb > 0 or ccb > 0) and forecast_dt and history:
                target_hist = forecast_dt - datetime.timedelta(hours=24)
                hist_height = self._extract_historical_height(target_hist, history)

            # Low Clouds (LCB) 
            # Use historical height if available, else default 020
            h1 = hist_height if hist_height else "020"
            c1 = get_cloud_str(lcb, h1)
            if c1: clouds.append(c1)
            
            # Convective (CCB) 
            # If historical used for LCB, maybe use it + delta for CCB? 
            # Or assume CCB is higher. For now, default 100 unless only CCB exists.
            # If both exist, using same height is weird. 
            # Simplification: If LCB exists, use hist for LCB. If CCB exists, use 100.
            # If ONLY CCB exists, use hist for CCB.
            
            h2 = "100"
            if ccb > 0 and lcb == 0 and hist_height:
                 h2 = hist_height
            
            c2 = get_cloud_str(ccb, h2) 
            if c2: clouds.append(c2)
            
            if not clouds:
                cloud_str = "NSC"
            else:
                cloud_str = " ".join(clouds)
            
            wx_str = " ".join(wx)
            return vis, wx_str.strip(), cloud_str
            
        except Exception:
            return "5000", "HZ", "NSC"

    def _check_vis_limit_change(self, old_vis, new_vis):
        """
        Checks if visibility change crosses specific thresholds:
        800, 1500, 2000, 3000, 5000 meters.
        """
        thresholds = [800, 1500, 2000, 3000, 5000]
        try:
            v1 = int(old_vis)
            v2 = int(new_vis)
            
            for t in thresholds:
                # Check crossing: one is below, other is >=
                # v1 < t <= v2  (Improving: Old below strict, New at/above)
                # v2 <= t < v1  (Deteriorating: New at/below, Old above strict)
                if (v1 < t <= v2) or (v2 <= t < v1):
                    return True
        except (ValueError, TypeError):
            return False
        return False

    def _find_matching_metar(self, target_dt, history):
        """
        Finds the METAR from history that is closest to the target_dt.
        Prioritizes exact match or very close past match.
        """
        if not history: return None
        
        # history keys are datetimes
        best_match = None
        min_diff = datetime.timedelta(minutes=45) # Tolerance
        
        for dt_key, data in history.items():
            diff = abs(dt_key - target_dt)
            if diff <= min_diff:
                min_diff = diff
                best_match = data
                
        return best_match

    def generate_long_taf(self, imd_data, ogimet_data):
        """
        Generates a 30-hour TAF with BECMG groups including Vis/Wx/Clouds.
        """
        station = ogimet_data.get('station', 'XXXX')
        
        issue_str, issue_dt = self._get_standard_issue_time()
        
        start_valid = issue_dt + datetime.timedelta(hours=1)
        end_valid = start_valid + datetime.timedelta(hours=30)
        validity = f"{start_valid.day:02d}{start_valid.hour:02d}/{end_valid.day:02d}{end_valid.hour:02d}"
        
        # Select Base Data
        forecast = imd_data.get('forecast', [])
        base_dir = imd_data.get('Dir')
        base_ws = imd_data.get('WS')
        base_gust = imd_data.get('Gust')
        
        issue_time_code = issue_dt.strftime("%d%H%M")
        
        base_entry = {}
        for entry in forecast:
            if entry.get('Time', '').startswith(issue_time_code):
                base_dir = entry.get('Dir')
                base_ws = entry.get('WS')
                base_gust = entry.get('Gust')
                base_entry = entry
                break
        
        init_wind = self._format_wind(base_dir, base_ws, base_gust)
        
        # Calculate Heuristics for Base Entry
        calc_vis, calc_wx, calc_clouds = self._get_projected_conditions(base_entry)
        
        # --- NEW LOGIC: Find Matching METAR ---
        history = ogimet_data.get('history', {})
        matched_metar = self._find_matching_metar(issue_dt, history)
        
        if matched_metar:
             vis = matched_metar.get('visibility_raw')
             clouds = matched_metar.get('clouds_raw')
        else:
             # Fallback to latest
             vis = ogimet_data.get('visibility_raw')
             clouds = ogimet_data.get('clouds_raw')
        
        if not vis or vis == '9999' or vis == 'N/A': vis = calc_vis # Fallback to calc if missing
        
        if not clouds or clouds == 'NSC' or clouds == 'N/A': clouds = calc_clouds # Fallback if missing
        
        # Use Calculated Weather strictly if Ogimet missing or to enforce User Rules
        weather = calc_wx

        taf_body = f"{init_wind} {vis} {weather} {clouds}".strip()
        taf_body = " ".join(taf_body.split())
        
        # BECMG Loop
        try:
            last_dir = int(float(base_dir or '0'))
            last_ws = int(float(base_ws or '0'))
        except:
            last_dir, last_ws = 0, 0
            
        last_vis = vis # Track visibility
        last_clouds = clouds # Track clouds
        # history = ogimet_data.get('history', None) # Passed above
        
        becmg_groups = []
        tempo_groups = []
        
        for entry in forecast:
            t_str = entry.get('Time', '') 
            d_str = entry.get('Dir', '0')
            s_str = entry.get('WS', '0')
            g_str = entry.get('Gust', '0')
            
            if not t_str: continue
            
            try:
                day = int(t_str[:2])
                hour = int(t_str[2:4])
                
                # Construct Forecast DT
                f_dt = issue_dt
                if day < issue_dt.day:
                    f_dt = f_dt + datetime.timedelta(days=15) # Move to next month safely (logic works for standard dates)
                # Fix: If forecast day is roughly same as issue day but hour < issue hour, it might be past?
                # Actually, strictly construct using the day/hour provided.
                # Assume forecast entry belongs to Month of Issue or Month of Issue + 1
                
                # Robust Construction:
                # 1. Start with issue_dt
                f_dt = issue_dt.replace(day=day, hour=hour, minute=0, second=0)
                
                # Handle Month Rollover (e.g. Issue 30th, Forecast 1st)
                if f_dt < issue_dt - datetime.timedelta(days=1): 
                     # If f_dt is way in past (more than 1 day), implies it's next month
                     # (Simple heuristic, or check validity)
                     f_dt = f_dt + datetime.timedelta(days=30) # Primitive month add approximately
                     # Better: use start_valid comparison
                
                # Skip if Time < Start Validity (Allowing 1 hour buffer maybe?)
                if f_dt < start_valid:
                    continue

                curr_dir = int(float(d_str or 0))
                curr_ws = int(float(s_str or 0))
                curr_gust = int(float(g_str or 0))
                
                # Calculate full conditions for this time step, passing DT and History
                p_vis, p_wx, p_clouds = self._get_projected_conditions(entry, f_dt, history)
                
                # Check BECMG Triggers
                triggered = False
                
                # 1. Wind Trigger
                diff_dir = abs(curr_dir - last_dir)
                if diff_dir > 180: diff_dir = 360 - diff_dir 
                
                wind_change = (diff_dir >= 60 and (last_ws >= 10 or curr_ws >= 10)) or \
                              (abs(curr_ws - last_ws) >= 10)
                              
                # 2. Visibility Trigger
                vis_change = self._check_vis_limit_change(last_vis, p_vis)
                
                # 3. Cloud Trigger (Simple string comparison)
                cloud_change = (p_clouds != last_clouds)
                
                if wind_change or vis_change or cloud_change:
                    end_h = (hour + 2) % 24
                    end_day = day + (1 if (hour+2)>=24 else 0)
                    
                    new_wind_grp = self._format_wind(d_str, s_str, g_str)
                    
                    group = f"BECMG {day:02d}{hour:02d}/{end_day:02d}{end_h:02d} {new_wind_grp} {p_vis} {p_wx} {p_clouds}"
                    group = " ".join(group.split()) 
                    becmg_groups.append(group)
                    
                    last_dir = curr_dir
                    last_ws = curr_ws
                    last_vis = p_vis
                    last_clouds = p_clouds

                # TEMPO Check
                if curr_gust >= 17:
                     calc_gust = curr_ws + 10
                     d_rounded = self._round_to_nearest_10(curr_dir)
                     tempo_wind = f"{d_rounded}{curr_ws:02d}G{calc_gust:02d}KT"
                     
                     t_end_h = (hour + 4) % 24
                     t_end_day = day + (1 if (hour+4)>=24 else 0)
                     
                     t_group = f"TEMPO {day:02d}{hour:02d}/{t_end_day:02d}{t_end_h:02d} {tempo_wind}"
                     tempo_groups.append(t_group)

            except Exception:
                continue
                
        # Format with New Lines
        # Structure: Header + Body
        #            BECMG ...
        #            BECMG ...
        
        parts = [f"TAF {station} {issue_str} {validity} {taf_body}"]
        parts.extend(becmg_groups)
        parts.extend(tempo_groups)
        
        full_taf = "\n".join(parts)
        return full_taf

    def generate_short_taf(self, imd_data, ogimet_data):
        """
        Generates a 9-hour TAF.
        """
        station = ogimet_data.get('station', 'XXXX')
        
        issue_str, issue_dt = self._get_standard_issue_time()
        
        # Validity: 9 Hours
        start_valid = issue_dt + datetime.timedelta(hours=1)
        end_valid = start_valid + datetime.timedelta(hours=9)
        
        validity = f"{start_valid.day:02d}{start_valid.hour:02d}/{end_valid.day:02d}{end_valid.hour:02d}"
        
        # Select Data Row matching Issue Time
        forecast = imd_data.get('forecast', [])
        
        base_dir = imd_data.get('Dir')
        base_ws = imd_data.get('WS')
        base_gust = imd_data.get('Gust')
        
        issue_time_code = issue_dt.strftime("%d%H%M") 
        
        base_entry = {}
        for entry in forecast:
            if entry.get('Time', '').startswith(issue_time_code):
                base_dir = entry.get('Dir')
                base_ws = entry.get('WS')
                base_gust = entry.get('Gust')
                base_entry = entry
                break
        
        wind = self._format_wind(base_dir, base_ws, base_gust)
        
        # Calculate Heuristics
        history = ogimet_data.get('history', {}) # Ensure non-None
        
        # For Short TAF base entry, the time is issue_dt
        calc_vis, calc_wx, calc_clouds = self._get_projected_conditions(base_entry, issue_dt, history)
        
        # --- NEW LOGIC: Find Matching METAR ---
        matched_metar = self._find_matching_metar(issue_dt, history)
        
        if matched_metar:
             vis = matched_metar.get('visibility_raw')
             clouds = matched_metar.get('clouds_raw')
        else:
             vis = ogimet_data.get('visibility_raw')
             clouds = ogimet_data.get('clouds_raw')
        
        if not vis or vis == '9999' or vis == 'N/A': vis = calc_vis
        
        if not clouds or clouds == 'NSC' or clouds == 'N/A': clouds = calc_clouds
            
        weather = calc_wx

        taf_body = f"{wind} {vis} {weather} {clouds}".strip()
        taf_body = " ".join(taf_body.split())
        
        return f"TAF {station} {issue_str} {validity} {taf_body}"
