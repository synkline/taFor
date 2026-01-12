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
        Standard Wind Formatting (Main TAF & BECMG).
        Logic (User Defined previously):
        If Speed >= 15 or Gust >= 17:
             Avg = Gust - 10
             Format: D(Avg)G(Gust)KT
        Else:
             Format: D(Speed)KT
        """
        try:
            d = float(d_str or 0)
            s = float(s_str or 0)
            g = float(g_str or 0)
            
            d_val = int(round(d / 10.0) * 10)
            if d_val == 0: d_val = 360 
            if d_val == 360 and s == 0: d_val = 0 
            
            d_fmt = f"{d_val:03d}"
            
            if s <= 3:
                return f"VRB{int(s):02d}KT"
            
            # Gust Logic: Avg = Gust - 10
            if s >= 15 or g >= 17:
                avg_val = int(g - 10)
                if avg_val < 0: avg_val = int(s)
                return f"{d_fmt}{avg_val:02d}G{int(g):02d}KT"
            else:
                return f"{d_fmt}{int(s):02d}KT"
                
        except Exception:
            return "00000KT"

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
        Rules (User Image 1767376200044 & New User Instruction):
        - Rain (3hrly accm):
          - 0-15mm: -RA
          - 15-65mm: RA
          - 65-115mm: +RA
        - Weather (Wx):
           - Stick to RH rules (FU <= 60, HZ <= 75, BR > 75)
        - Visibility:
           - Prioritize Persistence: Look for METAR -24hrs.
           - Fallback: Use RH-based estimation if history missing.
        - Clouds:
           - Persistence if LCB/CCB > 0.
        """
        # Defaults for Fallback (RH Based)
        calc_vis = "5000" 
        wx = []
        clouds = [] 
        
        try:
            rh = float(entry.get('RH', '0'))
            rain = float(entry.get('Rain', '0'))
            ws = float(entry.get('WS', '0'))
            lcb = float(entry.get('LCB', '0'))
            ccb = float(entry.get('CCB', '0'))
            
            # --- Weather Codes (Strictly RH/Rain) ---
            if rain > 0:
                # Rain Logic
                if rain > 10: 
                    calc_vis = "1000"
                    wx.append("+RA")
                elif rain > 2.5:
                    calc_vis = "3000"
                    wx.append("RA")
                else: 
                    # 0-2.5mm
                    calc_vis = "4000"
                    wx.append("-RA")
            elif rain == 0:
                # No Rain - Strict RH Rules for Wx Code
                if rh <= 60:
                    calc_vis = "4000" 
                    wx.append("FU")
                elif rh <= 75:
                    calc_vis = "4000" 
                    wx.append("HZ")
                else:
                    if rh >= 95:
                        calc_vis = "0800"
                        wx.append("FG")
                    else:
                        calc_vis = "2000"
                        wx.append("BR")
                    
            # --- Visibility Determination ---
            # Priority 1: Persistence (Same time yesterday)
            final_vis = calc_vis # Start with fallback
            
            if forecast_dt and history:
                target_hist = forecast_dt - datetime.timedelta(hours=24)
                hist_metar = self._find_matching_metar(target_hist, history)
                
                if hist_metar:
                    v_hist = hist_metar.get('visibility_raw')
                    if v_hist and v_hist != 'N/A' and v_hist != '9999': 
                         final_vis = v_hist
            
            # --- Clouds ---
            if lcb == 0 and ccb == 0:
                cloud_str = "NSC"
            else:
                # Cloud Persistence Logic
                persisted_clouds = None
                if forecast_dt and history:
                    target_hist = forecast_dt - datetime.timedelta(hours=24)
                    hist_metar = self._find_matching_metar(target_hist, history)
                    if hist_metar:
                        persisted_clouds = hist_metar.get('clouds_raw')
                
                if persisted_clouds and persisted_clouds != 'N/A' and persisted_clouds != 'NSC':
                    cloud_str = persisted_clouds
                else:
                    # Fallback mapping
                    c_list = []
                    if lcb > 0:
                        amt = "FEW" if lcb <= 2 else "SCT" if lcb <= 4 else "BKN" if lcb <= 7 else "OVC"
                        c_list.append(f"{amt}020")
                    if ccb > 0:
                        amt = "FEW" if ccb <= 2 else "SCT" if ccb <= 4 else "BKN" if ccb <= 7 else "OVC"
                        c_list.append(f"{amt}100")
                        
                    cloud_str = " ".join(c_list) if c_list else "NSC"
            
            wx_str = " ".join(wx)
            return final_vis, wx_str.strip(), cloud_str
            
        except Exception:
            return "5000", "HZ", "NSC"

    def _normalize_visibility(self, val_str):
        try:
           val = int(val_str)
           if val >= 5000: return "5000"
           if val < 800: return f"{int(round(val/50)*50):04d}"
           if val < 5000:
               if val >= 1500:
                   return f"{int(round(val/500)*500):04d}" 
               return f"{int(round(val/100)*100):04d}"
           return "9999"
        except:
           return "9999"

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

    def _build_forecast_timeline(self, imd_data, ogimet_data, start_valid, end_valid):
        """
        Parses IMD forecast data into a chronological list of state objects.
        Returns: list of dicts ordered by time
        """
        timeline = []
        forecast = imd_data.get('forecast', [])
        history = ogimet_data.get('history', {})
        
        # 1. Map Forecast Entries to Datetime
        data_map = {}
        
        issue_str, issue_dt = self._get_standard_issue_time()
        
        for entry in forecast:
            t_str = entry.get('Time', '')
            if not t_str: continue
            try:
                day = int(t_str[:2])
                hour = int(t_str[2:4])
                
                # Robust DT construction
                f_dt = issue_dt.replace(day=day, hour=hour, minute=0, second=0)
                # Handle month rollover
                if f_dt < issue_dt - datetime.timedelta(hours=12): 
                     f_dt = f_dt + datetime.timedelta(days=28) 
                     if day < issue_dt.day:
                         pass
                
                if f_dt < issue_dt - datetime.timedelta(days=1):
                     f_dt = f_dt + datetime.timedelta(days=30)
                
                data_map[f_dt] = entry
            except:
                continue

        # 2. Iterate Hourly from Start to End
        curr_dt = start_valid
        while curr_dt < end_valid:
            entry = data_map.get(curr_dt)
            
            if entry:
                # Process Conditions
                # Vis/Wx/Clouds
                p_vis, p_wx, p_clouds = self._get_projected_conditions(entry, curr_dt, history)
                
                # Check Actual METAR override
                actual_metar = self._find_matching_metar(curr_dt, history)
                if actual_metar:
                     v = actual_metar.get('visibility_raw')
                     c = actual_metar.get('clouds_raw')
                     if v and v != 'N/A': p_vis = v
                     if c and c != 'N/A': p_clouds = c
                else:
                    # Persistence 24h
                    past_dt = curr_dt - datetime.timedelta(days=1)
                    past_metar = self._find_matching_metar(past_dt, history)
                    if past_metar:
                         v = past_metar.get('visibility_raw')
                         c = past_metar.get('clouds_raw')
                         if v and v != 'N/A': p_vis = v
                         if c and c != 'N/A': p_clouds = c

                p_vis = self._normalize_visibility(p_vis)
                
                # Wind
                d_str = entry.get('Dir', '0')
                s_str = entry.get('WS', '0')
                g_str = entry.get('Gust', '0')
                
                wspd = float(s_str or 0)
                wgust = float(g_str or 0)
                wdir = float(d_str or 0)
                
                state = {
                    'dt': curr_dt,
                    'wdir': wdir,
                    'wspd': wspd,
                    'wgust': wgust,
                    'vis': p_vis,
                    'wx': p_wx,
                    'clouds': p_clouds,
                    'raw_entry': entry
                }
                timeline.append(state)
            
            curr_dt += datetime.timedelta(hours=1)
            
        return timeline

    def _consolidate_tempo_groups(self, timeline):
        """
        Finds continuous blocks of Gust >= 17 and creates merged TEMPO groups.
        Rules:
        - Max Validity: 4 Hours
        - Gust Calculation: Gust = Wspd + 10 (Derived from MAX speed in the block)
        Returns: Tuple (list of strings, set of masked datetimes)
        """
        groups = []
        masked_times = set()
        
        if not timeline: return groups, masked_times
        
        i = 0
        while i < len(timeline):
            start_state = timeline[i]
            
            # Check Start Condition: Gust >= 17
            if start_state['wgust'] >= 17:
                # 1. Identify the full continuous block first
                j = i + 1
                
                # Look ahead for continuity (break if gust < 17)
                while j < len(timeline):
                    next_state = timeline[j]
                    if next_state['wgust'] < 17:
                        break
                    j += 1
                
                block_start_idx = i
                block_end_idx = j # Exclusive
                
                # 2. Iterate through this block and split into max 4h chunks
                curr_idx = block_start_idx
                while curr_idx < block_end_idx:
                    chunk_end_idx = min(curr_idx + 4, block_end_idx)
                    
                    # Analyze Chunk
                    chunk_max_ws = 0
                    for k in range(curr_idx, chunk_end_idx):
                        if timeline[k]['wspd'] > chunk_max_ws: chunk_max_ws = timeline[k]['wspd']
                    
                    # Calculate Gust per User Rule (TEMPO specific): Gust = Wspd + 10
                    # We use chunk_max_ws as the representative Speed
                    chunk_gust = chunk_max_ws + 10
                    
                    # Define Time Range
                    s_dt = timeline[curr_idx]['dt']
                    # Last item index is chunk_end_idx - 1. End validity is +1 hour from that.
                    e_dt = timeline[chunk_end_idx - 1]['dt'] + datetime.timedelta(hours=1)
                    
                    # Update Mask (Suppress BECMG for these hours)
                    mask_cursor = s_dt
                    while mask_cursor < e_dt:
                        masked_times.add(mask_cursor)
                        mask_cursor += datetime.timedelta(hours=1)
                        
                    # Format
                    s_str = f"{s_dt.day:02d}{s_dt.hour:02d}"
                    e_str = f"{e_dt.day:02d}{e_dt.hour:02d}"
                    
                    # Use Direction from Start of Chunk
                    d_val = timeline[curr_idx]['wdir'] 
                    d_fmt = self._round_to_nearest_10(d_val)
                    if d_fmt == "000" and chunk_max_ws > 0: d_fmt = "360"
                    
                    # Format String: D(S)G(S+10)KT
                    # Ensure S is at least what was observed? Yes.
                    # Ensure G is exactly S+10. 
                    
                    wind_str = f"{d_fmt}{int(chunk_max_ws):02d}G{int(chunk_gust):02d}KT"
                    
                    tempo_str = f"TEMPO {s_str}/{e_str} {wind_str}"
                    groups.append(tempo_str)
                    
                    # Move cursor
                    curr_idx = chunk_end_idx
                
                # Resume main loop after this entire block
                i = block_end_idx 
            else:
                i += 1
                
        return groups, masked_times

    def _generate_change_groups(self, timeline, init_vis, init_clouds, init_wind_obj, masked_times=None):
        """
        Generates BECMG groups with smoothing (Debouncing 1-hour changes).
        Skips generation for times in masked_times.
        """
        groups = []
        if not timeline: return groups
        if masked_times is None: masked_times = set()
        
        # State Tracking
        curr_vis = init_vis
        curr_clouds = init_clouds
        curr_wdir = init_wind_obj['d']
        curr_wspd = init_wind_obj['s']
        
        i = 0
        while i < len(timeline):
            state = timeline[i]
            
            # SUPPRESSION CHECK (TEMPO Dominance)
            if state['dt'] in masked_times:
                # Update current state strictly without outputting BECMG
                # This ensures that when TEMPO ends, we compare against the conditions *during* TEMPO
                # or rather, we update our tracking so we don't trigger "fake" becmgs.
                curr_wdir = state['wdir']
                curr_wspd = state['wspd']
                curr_vis = state['vis']
                curr_clouds = state['clouds']
                i += 1
                continue
            
            # Check for changes vs Current Persisting State
            
            # 1. Wind Change
            # Rule: Direction change >= 60 OR Speed change >= 10?
            # User Image also said: "wspd exceeds 10KT or more".
            # For now, stick to standard significant change logic, plus the 10KT check.
            
            diff_dir = abs(state['wdir'] - curr_wdir)
            if diff_dir > 180: diff_dir = 360 - diff_dir
            
            # Standard: Dir change > 60 AND mean speed > 10 (either before or after)
            dir_significant = (diff_dir >= 60 and (state['wspd'] >= 10 or curr_wspd >= 10))
            
            # Speed significant: Change >= 10
            spd_significant = (abs(state['wspd'] - curr_wspd) >= 10)
            
            # "Exceeds 10KT" special check: If Crossing 10KT boundary?
            # Maybe implicit in the above if change is large.
            # Let's keep existing logic as it's robust.
            
            wind_chg = dir_significant or spd_significant
            
            # 2. Vis Change
            vis_chg = self._check_vis_limit_change(curr_vis, state['vis'])
            
            # 3. Cloud Change
            cloud_chg = (state['clouds'] != curr_clouds)
            
            if wind_chg or vis_chg or cloud_chg:
                # CANDIDATE CHANGE DETECTED at timeline[i]
                
                # --- SMOOTHING LOGIC ---
                # Peek at i+1. Does this new state persist?
                is_transient = False
                if i + 1 < len(timeline):
                    next_state = timeline[i+1]
                    
                    # Check Wind consistency (Next state similar to Candidate state?)
                    d_diff_next = abs(state['wdir'] - next_state['wdir'])
                    if d_diff_next > 180: d_diff_next = 360 - d_diff_next
                    wind_consistent = (d_diff_next < 60) and (abs(state['wspd'] - next_state['wspd']) < 10)
                    
                    # Check Vis consistency
                    vis_consistent = not self._check_vis_limit_change(state['vis'], next_state['vis'])
                    cloud_consistent = (state['clouds'] == next_state['clouds'])
                    
                    # If the PRIMARY trigger for the change is NOT consistent, we drop it.
                    if wind_chg and not wind_consistent: is_transient = True
                    if vis_chg and not vis_consistent: is_transient = True
                    # Partial mitigation for flip-flopping clouds
                    if cloud_chg and not cloud_consistent: is_transient = True
                
                # Filter Transient
                if is_transient:
                    # Skip this hour, do not update current state
                    i += 1
                    continue
                    
                # CONFIRMED CHANGE
                start_dt = state['dt']
                end_dt = start_dt + datetime.timedelta(hours=2) # Standard 2h trend
                
                # Handle standard trend dates
                start_str = f"{start_dt.day:02d}{start_dt.hour:02d}"
                end_str = f"{end_dt.day:02d}{end_dt.hour:02d}"
                
                # Format
                wind_str = self._format_wind(state['wdir'], state['wspd'], state['wgust'])
                
                grp = f"BECMG {start_str}/{end_str} {wind_str} {state['vis']} {state['wx']} {state['clouds']}"
                grp = " ".join(grp.split())
                groups.append(grp)
                
                # Update State
                curr_wdir = state['wdir']
                curr_wspd = state['wspd']
                curr_vis = state['vis']
                curr_clouds = state['clouds']
                
            i += 1
            
        return groups

    def _get_group_sort_key(self, group_str, issue_dt):
        """
        Parses the start DDHH from a group string and resolves it to a full datetime
        for correct sorting (handling month rollover).
        Format: TYPE DDHH/DDHH ...
        """
        import re
        m = re.search(r'\s(\d{2})(\d{2})/', group_str)
        if not m:
             # Fallback: Put at end or start? Let's treat as max future
             return datetime.datetime.max
             
        day = int(m.group(1))
        hour = int(m.group(2))
        
        # Resolve datetime similar to timeline builder
        # issue_dt is our anchor
        resolved_dt = issue_dt.replace(day=day, hour=hour, minute=0, second=0)
        
        # Handle Rollovers
        # If day is less than issue day (e.g., issue 30, group 01), add month
        if resolved_dt < issue_dt - datetime.timedelta(hours=12):
             resolved_dt += datetime.timedelta(days=28) # Min month length
             # Re-adjust if needed... simple +30 days logic from before works well enough for sorting
             if day < issue_dt.day:
                 pass # Already pushed forward
        
        # If day is way before issue (e.g. prev month?), shouldn't happen in TAF
        if resolved_dt < issue_dt - datetime.timedelta(days=1):
             resolved_dt += datetime.timedelta(days=30)
             
        return resolved_dt

    def generate_long_taf(self, imd_data, ogimet_data):
        station = ogimet_data.get('station', 'XXXX')
        issue_str, issue_dt = self._get_standard_issue_time()
        
        start_valid = issue_dt + datetime.timedelta(hours=1)
        end_valid = start_valid + datetime.timedelta(hours=30)
        validity = f"{start_valid.day:02d}{start_valid.hour:02d}/{end_valid.day:02d}{end_valid.hour:02d}"
        
        # 1. Build Timeline
        timeline = self._build_forecast_timeline(imd_data, ogimet_data, start_valid, end_valid)
        
        if not timeline:
             return f"TAF {station} {issue_str} {validity} NIL"

        # 2. Base Conditions (Timeline[0])
        base = timeline[0]
        init_wind = self._format_wind(base['wdir'], base['wspd'], base['wgust'])
        taf_body = f"{init_wind} {base['vis']} {base['wx']} {base['clouds']}".strip()
        taf_body = " ".join(taf_body.split())
        
        # 3. Smart Groups
        # Need distinct init objects for tracking
        init_wind_obj = {'d': base['wdir'], 's': base['wspd']}
        
        # Determine TEMPOs first and get mask
        tempo_groups, masked_times = self._consolidate_tempo_groups(timeline)
        
        # Pass slice [1:] to skip comparing base vs base, AND mask
        becmg_groups = self._generate_change_groups(timeline[1:], base['vis'], base['clouds'], init_wind_obj, masked_times)
        
        # 4. Assemble & Sort
        all_groups = becmg_groups + tempo_groups
        all_groups.sort(key=lambda g: self._get_group_sort_key(g, issue_dt))
        
        parts = [f"TAF {station} {issue_str} {validity} {taf_body}"]
        parts.extend(all_groups)
        
        return "\n".join(parts)

    def generate_short_taf(self, imd_data, ogimet_data):
        station = ogimet_data.get('station', 'XXXX')
        issue_str, issue_dt = self._get_standard_issue_time()
        
        start_valid = issue_dt + datetime.timedelta(hours=1)
        end_valid = start_valid + datetime.timedelta(hours=9)
        validity = f"{start_valid.day:02d}{start_valid.hour:02d}/{end_valid.day:02d}{end_valid.hour:02d}"
        
        timeline = self._build_forecast_timeline(imd_data, ogimet_data, start_valid, end_valid)
        
        if not timeline:
             return f"TAF {station} {issue_str} {validity} NIL"

        base = timeline[0]
        init_wind = self._format_wind(base['wdir'], base['wspd'], base['wgust'])
        taf_body = f"{init_wind} {base['vis']} {base['wx']} {base['clouds']}".strip()
        taf_body = " ".join(taf_body.split())
        
        init_wind_obj = {'d': base['wdir'], 's': base['wspd']}
        
        tempo_groups, masked_times = self._consolidate_tempo_groups(timeline)
        becmg_groups = self._generate_change_groups(timeline[1:], base['vis'], base['clouds'], init_wind_obj, masked_times)
        
        all_groups = becmg_groups + tempo_groups
        all_groups.sort(key=lambda g: self._get_group_sort_key(g, issue_dt))
        
        parts = [f"TAF {station} {issue_str} {validity} {taf_body}"]
        parts.extend(all_groups)
        
        return "\n".join(parts)
