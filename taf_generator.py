import datetime

class TafGenerator:
    def __init__(self):
        pass

    def _get_standard_issue_time(self, now=None):
        """
        returns closest TAF issue time (05, 11, 17, 23 UTC)
        and the corresponding issue datetime object.
        """
        if now is None:
            now = datetime.datetime.utcnow()

        candidates = [5, 11, 17, 23]
        
        # find closest hour
        current_hour = now.hour
        best_hour = candidates[0]
        min_diff = 24
        
        for h in candidates:
            diff = abs(h - current_hour)
            if diff < min_diff:
                min_diff = diff
                best_hour = h
        
        # allocate proper slots
        if 2 <= current_hour < 8: best_hour = 5
        elif 8 <= current_hour < 14: best_hour = 11
        elif 14 <= current_hour < 20: best_hour = 17
        else: 
            best_hour = 23
            # when in early hours (0, 1) of Day X, the 2300 slot belongs to Day X-1
            if current_hour < 2:
                now = now - datetime.timedelta(days=1)
        
        issue_dt = now.replace(hour=best_hour, minute=0, second=0, microsecond=0)
        return issue_dt.strftime("%d%H%M") + "Z", issue_dt

    def _round_to_nearest_10(self, val):
        try:
            val = int(float(val))
            rounded = round(val / 10) * 10
            if rounded == 0: return "360" # as 000 is used for calm winds, 360 used for 0 degree(north)
            if rounded == 360: return "360"
            return f"{rounded:03d}"
        except (ValueError, TypeError):
            return "000"

    def _format_wind(self, d_str, s_str, g_str="0", is_vrb=None):
        """
        standard wind formatting
        """
        try:
            d = float(d_str or 0)
            s = float(s_str or 0)
            g = float(g_str or 0)
            
            d_val = int(round(d / 10.0) * 10)
            if 0 < d < 10: d_val = 10
            if d_val == 0: d_val = 360 
            if d_val == 360 and s == 0: d_val = 0 
            
            d_fmt = f"{d_val:03d}"
            
            if s == 0:
                return "00000KT"
            
            # decide VRB state
            is_variable = False
            
            if is_vrb is True:
                is_variable = True
            elif s <= 3 and is_vrb is not False:
                is_variable = True
                
            if is_variable:
                if g >= 10:
                     return f"VRB{int(s):02d}G{int(g):02d}KT"
                else:
                     return f"VRB{int(s):02d}KT"
            
            # gust logic: avg = gust - 10
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
        cloud height from METAR ~24 hours prior.
        """
        if not history: return None
        
        best_dt = None
        min_diff = datetime.timedelta(hours=999)
        
        for dt_key in history.keys():
            diff = abs(dt_key - target_dt)
            if diff < min_diff:
                min_diff = diff
                best_dt = dt_key
                
        # accepts within reasonable window (+/- 90 min)
        if min_diff > datetime.timedelta(minutes=90):
            return None
            
        metar_data = history.get(best_dt)
        if not metar_data: return None
        
        # for parsing clouds from Ogimet METAR
        c_raw = metar_data.get('clouds_raw', '')
        # pattern is  3 letters + 3 digits
        import re
        matches = re.findall(r'[A-Z]{3}(\d{3})', c_raw)
        if matches:
            return matches[0] # returns height for first cloud layer 
        return None

    def _get_projected_conditions(self, entry, forecast_dt=None, history=None, rain_3hr_sum=None):
        """
        estimates visibility, weather, clouds based on IMD data.
        """
        # default values
        final_vis = "9999"
        wx = []
        cloud_str = "NSC"
        
        try:
            rain = float(entry.get('Rain', '0'))
            eval_rain = rain_3hr_sum if rain_3hr_sum is not None else rain
            
            lcb = float(entry.get('LCB', '0'))
            ccb = float(entry.get('CCB', '0'))
            
            # rain weather codes
            if eval_rain >= 0.1:
                if eval_rain >= 65: 
                    wx.append("+RA")
                elif eval_rain >= 15:
                    wx.append("RA")
                elif eval_rain > 0: 
                    wx.append("-RA")
            else:
                # when no rain we use RH% to tell weather type
                try:
                    rh = float(entry.get('RH', '0'))
                    if rh <= 60:
                        wx.append("FU")
                    elif 60 < rh <= 75:
                        wx.append("HZ")
                    elif rh > 75:
                        wx.append("BR")
                except:
                    pass               
            #  visibility logic
            # the exacr time -> 24 hr fallback -> 48 hr fallback -> or else 9999(nil)
            
            if forecast_dt and history:
                vis_found = False
                
                # 1. for exact time 
                hist_metar_exact = self._find_matching_metar(forecast_dt, history)
                if hist_metar_exact:
                    v_hist = hist_metar_exact.get('visibility_raw')
                    if v_hist and v_hist != 'N/A':
                        final_vis = v_hist
                        vis_found = True
                
                # 2. 24h fallback
                if not vis_found:
                    target_hist_24 = forecast_dt - datetime.timedelta(hours=24)
                    hist_metar_24 = self._find_matching_metar(target_hist_24, history)
                    if hist_metar_24:
                        v_hist = hist_metar_24.get('visibility_raw')
                        if v_hist and v_hist != 'N/A': 
                             final_vis = v_hist
                             vis_found = True
                
                # 3.  48h fallback 
                if not vis_found:
                    target_hist_48 = forecast_dt - datetime.timedelta(hours=48)
                    hist_metar_48 = self._find_matching_metar(target_hist_48, history)
                    if hist_metar_48:
                        v_hist = hist_metar_48.get('visibility_raw')
                        if v_hist and v_hist != 'N/A':
                             final_vis = v_hist

            # cloud when
            if lcb == 0 and ccb == 0:
                cloud_str = "NSC"
            else:
                # when LCB/CCB are non-zero check for
                persisted_clouds = None
                
                if forecast_dt and history:
                    # 1. exact time 
                    hist_metar_exact = self._find_matching_metar(forecast_dt, history)
                    if hist_metar_exact:
                        c_raw = hist_metar_exact.get('clouds_raw')
                        if c_raw and c_raw != 'N/A': # allow NSC here
                            persisted_clouds = c_raw

                    # 2. 24h fallback
                    if not persisted_clouds:
                        target_hist_24 = forecast_dt - datetime.timedelta(hours=24)
                        hist_metar_24 = self._find_matching_metar(target_hist_24, history)
                        if hist_metar_24:
                            c_raw = hist_metar_24.get('clouds_raw')
                            if c_raw and c_raw != 'N/A' and c_raw != 'NSC':
                                persisted_clouds = c_raw
                    
                    # 3.  48h fallback 
                    if not persisted_clouds:
                        target_hist_48 = forecast_dt - datetime.timedelta(hours=48)
                        hist_metar_48 = self._find_matching_metar(target_hist_48, history)
                        if hist_metar_48:
                            c_raw = hist_metar_48.get('clouds_raw')
                            if c_raw and c_raw != 'N/A' and c_raw != 'NSC':
                                persisted_clouds = c_raw
                
                if persisted_clouds:
                    cloud_str = persisted_clouds
                else:
                    # fallback if non-zero clouds but no history available default to NSC 
                    cloud_str = "NSC"
            
            wx_str = " ".join(wx)
            return final_vis, wx_str.strip(), cloud_str
            
        except Exception:
            return "9999", "", "NSC"

    def _normalize_visibility(self, val_str):
        try:
           val = int(val_str)
           if val >= 9999: return "9999"
           
           if val < 800: return f"{int(round(val/50)*50):04d}"
           
           # Standard 100m steps for 800 - 4999
           if val < 5000:
               return f"{int(round(val/100)*100):04d}"
               
           # For 5000-9000, usually standard is 1000 steps, or just report 9999 if >10km
           # We will fallback to 9999 for anything >= 5000 to match previous "bucket" logic style 
           # but using the standard "clear" code instead of 5000.
           return "9999"
        except:
           return "9999"

    def _snap_visibility(self, vis):
        """
        Snaps visibility based on user rules:
        - If > 1500m: Nearest 500m
        - If <= 1500m: Nearest 100m
        """
        try:
            v = int(vis)
            if v == 9999: return "9999" # Keep 9999 as is
            
            if v > 1500:
                # Nearest 500
                remainder = v % 500
                if remainder >= 250:
                    v = v + (500 - remainder)
                else:
                    v = v - remainder
            else:
                # Nearest 100
                remainder = v % 100
                if remainder >= 50:
                    v = v + (100 - remainder)
                else:
                    v = v - remainder
            
            # Formatting: 4 digits
            return f"{v:04d}"
        except:
            return "9999"

    def _check_vis_limit_change(self, old_vis, new_vis):
        """
        Checks if visibility change is >= 30% deviation.
        Returns True if change triggers.
        """
        try:
            v1 = float(old_vis)
            v2 = float(new_vis)
            
            if v1 == 0: return v2 > 0 # Handle zero division
            
            # Delta %
            delta = abs(v2 - v1) / v1
            
            # Threshold 30%
            if delta >= 0.30:
                return True
            return False
        except:
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
                # Calculate Centered 3-Hour Rain Sum: Rain(T-1) + Rain(T) + Rain(T+1)
                # This smooths the intensity and matches user thresholds (15/65).
                rain_t = float(entry.get('Rain', '0'))
                
                prev_dt = curr_dt - datetime.timedelta(hours=1)
                next_dt = curr_dt + datetime.timedelta(hours=1)
                
                # Fetch neighbors safely (default 0 if missing/out of bounds)
                rain_prev = float(data_map.get(prev_dt, {}).get('Rain', '0'))
                rain_next = float(data_map.get(next_dt, {}).get('Rain', '0'))
                
                rain_3hr = rain_prev + rain_t + rain_next
                
                # Process Conditions using 3hr Sum for thresholds
                p_vis, p_wx, p_clouds = self._get_projected_conditions(entry, curr_dt, history, rain_3hr_sum=rain_3hr)
                
                # Logic moved to _get_projected_conditions:
                # - Exact Match
                # - 24h Persistence
                # - 48h Persistence
                # - Defaults

                p_vis = self._normalize_visibility(p_vis)
                
                # Wind
                d_str = entry.get('Dir', '0')
                s_str = entry.get('WS', '0')
                g_str = entry.get('Gust', '0')
                
                wspd = float(s_str or 0)
                wgust = float(g_str or 0)
                wdir = float(d_str or 0)
                
                # VRB Check: Speed(t) <= 3 AND Speed(t+1) <= 3
                # We need next hour's speed.
                
                # Default assume false if end of data
                is_vrb_condition = False
                
                # Check current speed
                if wspd <= 3:
                    # Check next speed
                    # We already have next_dt from rain calc
                    next_entry = data_map.get(next_dt)
                    if next_entry:
                        s_next = float(next_entry.get('WS', '0'))
                        if s_next <= 3:
                            is_vrb_condition = True
                
                state = {
                    'dt': curr_dt,
                    'wdir': wdir,
                    'wspd': wspd,
                    'wgust': wgust,
                    'vis': p_vis,
                    'wx': p_wx,
                    'clouds': p_clouds,
                    'is_vrb': is_vrb_condition,
                    'rain_3hr': rain_3hr,
                    'raw_entry': entry
                }
                # DEBUG PRINT
                # if curr_dt.hour == 13 and curr_dt.day == 11:
                #     print(f"DEBUG: {curr_dt} Row={entry.get('Time')} WSPD={wspd} WGUST={wgust} Raw={entry}")
                timeline.append(state)
            
            curr_dt += datetime.timedelta(hours=1)
            
        # --- Hysteresis for VRB ---
        # Enter VRB: wspd <= 3 for >= 2 consecutive hours
        # Exit VRB: wspd >= 5 for >= 2 consecutive hours
        # Initialize State (assume Directional start, or check first few?)
        # To be safe and strict, we start Directional and let the counter build up.
        
        current_state_vrb = False
        count_le_3 = 0
        count_ge_5 = 0
        
        for i in range(len(timeline)):
            wspd = timeline[i]['wspd']
            
            # Track counts
            if wspd <= 3:
                count_le_3 += 1
            else:
                count_le_3 = 0
                
            if wspd >= 5:
                count_ge_5 += 1
            else:
                count_ge_5 = 0
                
            # State Transitions
            if not current_state_vrb:
                # Attempt to Enter VRB
                if count_le_3 >= 2:
                    current_state_vrb = True
            else:
                # Attempt to Exit VRB
                if count_ge_5 >= 2:
                    current_state_vrb = False
            
            # Apply State
            timeline[i]['is_vrb'] = current_state_vrb

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
                
                # 2. Iterate through this block and split into max 4h chunks (Strict Rule 4h)
                curr_idx = block_start_idx
                while curr_idx < block_end_idx:
                    chunk_end_idx = min(curr_idx + 4, block_end_idx)
                    
                    # Analyze Chunk - Find MAX SPEED to drive the calculation
                    chunk_max_ws = 0
                    for k in range(curr_idx, chunk_end_idx):
                        if timeline[k]['wspd'] > chunk_max_ws: chunk_max_ws = timeline[k]['wspd']
                    
                    # Calculate per User Rule: Gust = Speed + 10
                    # "If wgust >= 17 ... Read wspd ... wgust = wspd+10"
                    reported_spd = chunk_max_ws
                    reported_gust = reported_spd + 10
                    
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
                    
                    # Use Direction from Start of Chunk (or maybe avg?)
                    d_val = timeline[curr_idx]['wdir'] 
                    d_fmt = self._round_to_nearest_10(d_val)
                    if d_fmt == "000" and reported_spd > 0: d_fmt = "360"
                    
                    # Format String: D(Speed)G(Speed+10)KT
                    wind_str = f"{d_fmt}{int(reported_spd):02d}G{int(reported_gust):02d}KT"
                    
                    tempo_str = f"TEMPO {s_str}/{e_str} {wind_str}"
                    groups.append(tempo_str)
                    
                    # Move cursor
                    curr_idx = chunk_end_idx
                
                # Resume main loop after this entire block
                i = block_end_idx 
            else:
                i += 1
        
        # --- RAIN TEMPO LOGIC (Separate Pass) ---
        # Rule: If rain > 50mm, Add "TEMPO HH/HH 1500 +RA +SHRA" (6hr validity)
        # --- RAIN TEMPO LOGIC (Separate Pass) ---
        # Rule: If rain > 50mm, Add "TEMPO HH/HH ... " (6hr validity)
        # We process this similarly to Wind, detecting continuous blocks > 50mm.
        i = 0
        while i < len(timeline):
            state = timeline[i]
            # Use 3-hourly accumulated rain from state
            rain_val = state.get('rain_3hr', 0.0)
            
            if rain_val > 50:
                # 1. Identify valid block
                j = i + 1
                while j < len(timeline):
                    next_r = timeline[j].get('rain_3hr', 0.0)
                    if next_r <= 50:
                        break
                    j += 1
                
                block_start = i
                block_end = j
                
                # 2. Process block in 6h chunks
                curr = block_start
                while curr < block_end:
                    chunk_end = min(curr + 6, block_end)
                    
                    s_dt = timeline[curr]['dt']
                    e_dt_validity = timeline[chunk_end - 1]['dt'] + datetime.timedelta(hours=1)
                    
                    s_str = f"{s_dt.day:02d}{s_dt.hour:02d}"
                    e_str = f"{e_dt_validity.day:02d}{e_dt_validity.hour:02d}"
                    
                    # Determine conditions for the TEMPO
                    # User request: "TEMPO to/from vis +RA +SHRA"
                    # We need 'vis'. Let's pick the minimum visibility in this chunk.
                    min_vis_val = 9999
                    min_vis_str = "9999"
                    
                    for k in range(curr, chunk_end):
                        v_str = timeline[k]['vis']
                        try:
                            v_int = int(v_str)
                            if v_int < min_vis_val:
                                min_vis_val = v_int
                                min_vis_str = v_str
                        except:
                            pass
                            
                    # Format
                    tempo_str = f"TEMPO {s_str}/{e_str} {min_vis_str} +RA +SHRA"
                    groups.append(tempo_str)
                    
                    curr = chunk_end
                
                # Advance main loop
                i = block_end
            else:
                i += 1

        # --- VISIBILITY TEMPO LOGIC (Separate Pass) ---
        # Rule: If Vis <= 1500m for >= 2 consecutive hours, Add "TEMPO HH/HH [min_vis] [valid_wx]"
        # Max Validity: 4 Hours
        
        i = 0
        while i < len(timeline):
            state = timeline[i]
            
            # Skip if already covered by Wind/Rain TEMPO
            if state['dt'] in masked_times:
                i += 1
                continue
                
            try:
                vis_val = int(state['vis'])
            except:
                vis_val = 9999
            
            if vis_val <= 1500:
                # 1. Check for Continuity (>= 2 hours required)
                # Look ahead
                j = i + 1
                consecutive_count = 1
                
                # Scan block of low vis
                while j < len(timeline):
                    # Break on gap or masked time
                    next_dt = timeline[j]['dt']
                    if next_dt in masked_times:
                        break
                        
                    try:
                        next_v = int(timeline[j]['vis'])
                    except:
                        next_v = 9999
                        
                    if next_v > 1500:
                        break
                        
                    consecutive_count += 1
                    j += 1
                
                if consecutive_count >= 2:
                    block_start = i
                    block_end = j
                    
                    # Process block in 4h chunks
                    curr = block_start
                    while curr < block_end:
                        chunk_end = min(curr + 4, block_end)
                        
                        s_dt = timeline[curr]['dt']
                        e_dt_validity = timeline[chunk_end - 1]['dt'] + datetime.timedelta(hours=1)
                        
                        s_str = f"{s_dt.day:02d}{s_dt.hour:02d}"
                        e_str = f"{e_dt_validity.day:02d}{e_dt_validity.hour:02d}"
                        
                        # Determine conditions
                        min_vis_val = 9999
                        min_vis_str = "9999"
                        
                        # Wx Collection
                        wx_set = set()
                        
                        for k in range(curr, chunk_end):
                            v_str = timeline[k]['vis']
                            try:
                                v_int = int(v_str)
                                if v_int < min_vis_val:
                                    min_vis_val = v_int
                                    min_vis_str = v_str
                            except:
                                pass
                            
                            w_k = timeline[k]['wx']
                            if w_k:
                                for code in w_k.split():
                                    if code not in ["NSW", ""]:
                                        wx_set.add(code)
                        
                        # Sort Wx
                        wx_list = sorted(list(wx_set))
                        wx_str = " ".join(wx_list)
                        
                        # Update Mask
                        mask_cursor = s_dt
                        while mask_cursor < e_dt_validity:
                            masked_times.add(mask_cursor)
                            mask_cursor += datetime.timedelta(hours=1)
                        
                        # Format
                        tempo_str = f"TEMPO {s_str}/{e_str} {min_vis_str} {wx_str}".strip()
                        groups.append(tempo_str)
                        
                        curr = chunk_end
                    
                    i = block_end
                else:
                    # Not enough duration
                    i += 1
            else:
                i += 1

        return groups, masked_times

    def _generate_change_groups(self, timeline, init_vis, init_clouds, init_wx, init_wind_obj, masked_times=None):
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
        curr_wx = init_wx
        curr_wdir = init_wind_obj['d']
        curr_wspd = init_wind_obj['s']
        curr_is_vrb = init_wind_obj.get('is_vrb', False)
        
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
                curr_wx = state['wx']
                curr_is_vrb = state['is_vrb']
                i += 1
                continue
            
            # Check for changes vs Current Persisting State
            
            # Wx Change Check (Base Logic)
            wx_chg = (state['wx'] != curr_wx)
            
            # 1. Wind Change
            diff_dir = abs(state['wdir'] - curr_wdir)
            if diff_dir > 180: diff_dir = 360 - diff_dir
            dir_significant = (diff_dir >= 60) # User strict rule: Just check deviation > 60
            spd_significant = (abs(state['wspd'] - curr_wspd) >= 10)
            
            # VRB Change Check
            vrb_chg = (state['is_vrb'] != curr_is_vrb)
            
            wind_chg = dir_significant or spd_significant or vrb_chg
            
            # 2. Vis Change
            vis_chg = self._check_vis_limit_change(curr_vis, state['vis'])
            
            # 3. Cloud Change
            cloud_chg = (state['clouds'] != curr_clouds)
            
            # User Rule: Rain (Wx) does NOT trigger BECMG by itself.
            # Only Wind, Vis, or Cloud changes trigger it.
            if wind_chg or vis_chg or cloud_chg:
                # CANDIDATE CHANGE
                
                # --- SMOOTHING LOGIC ---
                is_transient = False
                if i + 1 < len(timeline):
                    next_state = timeline[i+1]
                    
                    # Wx consistency
                    wx_consistent = (state['wx'] == next_state['wx'])
                    
                    d_diff_next = abs(state['wdir'] - next_state['wdir'])
                    if d_diff_next > 180: d_diff_next = 360 - d_diff_next
                    wind_consistent = (d_diff_next < 60) and (abs(state['wspd'] - next_state['wspd']) < 10)
                    
                    # Check VRB consistency
                    vrb_consistent = (state['is_vrb'] == next_state['is_vrb'])
                    if vrb_chg and not vrb_consistent: is_transient = True
                    
                    vis_consistent = not self._check_vis_limit_change(state['vis'], next_state['vis'])
                    cloud_consistent = (state['clouds'] == next_state['clouds'])
                    
                    if (dir_significant or spd_significant) and not wind_consistent: is_transient = True
                    if vis_chg and not vis_consistent: is_transient = True
                    if wx_chg and not wx_consistent: is_transient = True
                    if cloud_chg and not cloud_consistent: is_transient = True
                
                if is_transient:
                    i += 1
                    continue
                    
                # CONFIRMED CHANGE
                target_state = state
                check_ahead = 1
                
                while check_ahead <= 2 and (i + check_ahead) < len(timeline):
                    next_s = timeline[i + check_ahead]
                    
                    n_wind = (abs(next_s['wdir'] - target_state['wdir']) >= 60) 
                    n_vis = self._check_vis_limit_change(target_state['vis'], next_s['vis'])
                    n_wx = (next_s['wx'] != target_state['wx'])
                    n_cld = (next_s['clouds'] != target_state['clouds'])
                    n_vrb = (next_s['is_vrb'] != target_state['is_vrb'])
                    
                    if n_wind or n_vis or n_cld or n_wx or n_vrb:
                        target_state = next_s
                        
                    check_ahead += 1
                
                steps_to_skip = 0
                if target_state != state:
                     steps_to_skip = timeline.index(target_state) - i

                start_dt = state['dt']
                end_dt = start_dt + datetime.timedelta(hours=2)
                
                start_str = f"{start_dt.day:02d}{start_dt.hour:02d}"
                end_str = f"{end_dt.day:02d}{end_dt.hour:02d}"
                
                out_parts = [f"BECMG {start_str}/{end_str}"]
                
                # FIXED: Always Include Elements (Display Everything)
                
                # 1. Wind
                out_parts.append(self._format_wind(target_state['wdir'], target_state['wspd'], target_state['wgust'], is_vrb=target_state['is_vrb']))
                
                # 2. Vis
                out_parts.append(target_state['vis'])
                
                # 3. Wx
                if target_state['wx']:
                    out_parts.append(target_state['wx'])
                elif curr_wx and not target_state['wx']:
                     out_parts.append("NSW")
                
                # 4. Clouds
                out_parts.append(target_state['clouds'])

                # Prevent Empty BECMG
                grp = " ".join(part for part in out_parts if part).strip()
                if len(out_parts) > 1: # Ensure we have content besides the header
                    groups.append(grp)
                
                curr_wdir = target_state['wdir']
                curr_wspd = target_state['wspd']
                curr_vis = target_state['vis']
                curr_clouds = target_state['clouds']
                curr_wx = target_state['wx']
                curr_is_vrb = target_state['is_vrb']
                
                i += (1 + steps_to_skip)
                continue
                
            # If no change detected
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
        init_wind = self._format_wind(base['wdir'], base['wspd'], base['wgust'], is_vrb=base['is_vrb'])
        taf_body = f"{init_wind} {base['vis']} {base['wx']} {base['clouds']}".strip()
        taf_body = " ".join(taf_body.split())
        
        # 3. Smart Groups
        # Need distinct init objects for tracking
        init_wind_obj = {'d': base['wdir'], 's': base['wspd'], 'is_vrb': base['is_vrb']}
        
        # Determine TEMPOs first and get mask
        tempo_groups, masked_times = self._consolidate_tempo_groups(timeline)
        
        # Pass slice [1:] to skip comparing base vs base, AND mask
        becmg_groups = self._generate_change_groups(timeline[1:], base['vis'], base['clouds'], base['wx'], init_wind_obj, masked_times)
        
        # 4. Assemble & Sort
        all_groups = becmg_groups + tempo_groups
        all_groups.sort(key=lambda g: self._get_group_sort_key(g, issue_dt))
        
        parts = [f"TAF {station} {issue_str} {validity} {taf_body}"]
        parts.extend(all_groups)
        
        return "\n".join(parts) + "="

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
        init_wind = self._format_wind(base['wdir'], base['wspd'], base['wgust'], is_vrb=base['is_vrb'])
        taf_body = f"{init_wind} {base['vis']} {base['wx']} {base['clouds']}".strip()
        taf_body = " ".join(taf_body.split())
        
        init_wind_obj = {'d': base['wdir'], 's': base['wspd'], 'is_vrb': base['is_vrb']}
        
        tempo_groups, masked_times = self._consolidate_tempo_groups(timeline)
        becmg_groups = self._generate_change_groups(timeline[1:], base['vis'], base['clouds'], base['wx'], init_wind_obj, masked_times)
        
        all_groups = becmg_groups + tempo_groups
        all_groups.sort(key=lambda g: self._get_group_sort_key(g, issue_dt))
        
        parts = [f"TAF {station} {issue_str} {validity} {taf_body}"]
        parts.extend(all_groups)
        
        return "\n".join(parts) + "="

