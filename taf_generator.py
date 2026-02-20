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
        
        current_hour = now.hour
        best_hour = candidates[0]
        min_diff = 24
        
        for h in candidates:
            diff = abs(h - current_hour)
            if diff < min_diff:
                min_diff = diff
                best_hour = h
        
        if 2 <= current_hour < 8: best_hour = 5
        elif 8 <= current_hour < 14: best_hour = 11
        elif 14 <= current_hour < 20: best_hour = 17
        else: 
            best_hour = 23
                                                                                   
            if current_hour < 2:
                now = now - datetime.timedelta(days=1)
        
        issue_dt = now.replace(hour=best_hour, minute=0, second=0, microsecond=0)
        return issue_dt.strftime("%d%H%M") + "Z", issue_dt

    def _round_to_nearest_10(self, val):
        try:
            val = int(float(val))
            rounded = round(val / 10) * 10
            if rounded == 0: return "360"                                                              
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
                
        if min_diff > datetime.timedelta(minutes=90):
            return None
            
        metar_data = history.get(best_dt)
        if not metar_data: return None
        
        c_raw = metar_data.get('clouds_raw', '')
                                          
        import re
        matches = re.findall(r'[A-Z]{3}(\d{3})', c_raw)
        if matches:
            return matches[0]                                        
        return None

    def _get_projected_conditions(self, entry, forecast_dt=None, history=None, rain_3hr_sum=None, prev_vis="9999", prev_clouds="NSC"):
        """
        estimates visibility, weather, clouds based on IMD data.
        """
                        
        final_vis = prev_vis 
        wx = []
        cloud_str = prev_clouds 
        
        try:
            rain = float(entry.get('Rain', '0'))
            eval_rain = rain_3hr_sum if rain_3hr_sum is not None else rain
            
            lcb = float(entry.get('LCB', '0'))
            ccb = float(entry.get('CCB', '0'))
            
            if eval_rain >= 0.1:
                if eval_rain >= 65: 
                    wx.append("+RA")
                elif eval_rain >= 15:
                    wx.append("RA")
                elif eval_rain > 0: 
                    wx.append("-RA")
            else:
                                                              
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
                               
            if forecast_dt and history:
                vis_found = False
                
                hist_metar_exact = self._find_matching_metar(forecast_dt, history)
                if hist_metar_exact:
                    v_hist = hist_metar_exact.get('visibility_raw')
                    if v_hist and v_hist != 'N/A':
                        final_vis = v_hist
                        vis_found = True
                
                if not vis_found:
                    target_hist_24 = forecast_dt - datetime.timedelta(hours=24)
                    hist_metar_24 = self._find_matching_metar(target_hist_24, history)
                    if hist_metar_24:
                        v_hist = hist_metar_24.get('visibility_raw')
                        if v_hist and v_hist != 'N/A': 
                             final_vis = v_hist
                             vis_found = True
                
                if not vis_found:
                    target_hist_48 = forecast_dt - datetime.timedelta(hours=48)
                    hist_metar_48 = self._find_matching_metar(target_hist_48, history)
                    if hist_metar_48:
                        v_hist = hist_metar_48.get('visibility_raw')
                        if v_hist and v_hist != 'N/A':
                             final_vis = v_hist

            if lcb == 0 and ccb == 0:
                cloud_str = "NSC"
            else:
                                                     
                persisted_clouds = None
                
                if forecast_dt and history:
                                    
                    hist_metar_exact = self._find_matching_metar(forecast_dt, history)
                    if hist_metar_exact:
                        c_raw = hist_metar_exact.get('clouds_raw')
                        if c_raw and c_raw != 'N/A':                 
                            persisted_clouds = c_raw

                    if not persisted_clouds:
                        target_hist_24 = forecast_dt - datetime.timedelta(hours=24)
                        hist_metar_24 = self._find_matching_metar(target_hist_24, history)
                        if hist_metar_24:
                            c_raw = hist_metar_24.get('clouds_raw')
                            if c_raw and c_raw != 'N/A' and c_raw != 'NSC':
                                persisted_clouds = c_raw
                    
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
           
           if val < 5000:
               return f"{int(round(val/100)*100):04d}"
               
           if val < 9999:
                                                            
               return f"{int(round(val/1000)*1000):04d}"

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
            if v == 9999: return "9999"                  
            
            if v > 1500:
                             
                remainder = v % 500
                if remainder >= 250:
                    v = v + (500 - remainder)
                else:
                    v = v - remainder
            else:
                             
                remainder = v % 100
                if remainder >= 50:
                    v = v + (100 - remainder)
                else:
                    v = v - remainder
            
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
            
            if v1 == 0: return v2 > 0                       
            
            delta = abs(v2 - v1) / v1
            
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
        
        best_match = None
        min_diff = datetime.timedelta(minutes=45)            
        
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
        
        data_map = {}
        
        issue_str, issue_dt = self._get_standard_issue_time()
        
        for entry in forecast:
            t_str = entry.get('Time', '')
            if not t_str: continue
            try:
                day = int(t_str[:2])
                hour = int(t_str[2:4])
                
                f_dt = issue_dt.replace(day=day, hour=hour, minute=0, second=0)
                                       
                if f_dt < issue_dt - datetime.timedelta(hours=12): 
                     f_dt = f_dt + datetime.timedelta(days=28) 
                     if day < issue_dt.day:
                         pass
                
                if f_dt < issue_dt - datetime.timedelta(days=1):
                     f_dt = f_dt + datetime.timedelta(days=30)
                
                data_map[f_dt] = entry
            except:
                continue

        curr_dt = start_valid
        
        last_known_vis = "9999"
        last_known_clouds = "NSC"
        
        while curr_dt < end_valid:
            entry = data_map.get(curr_dt)
            
            if entry:
                                                                                     
                rain_t = float(entry.get('Rain', '0'))
                
                prev_dt = curr_dt - datetime.timedelta(hours=1)
                next_dt = curr_dt + datetime.timedelta(hours=1)
                
                rain_prev = float(data_map.get(prev_dt, {}).get('Rain', '0'))
                rain_next = float(data_map.get(next_dt, {}).get('Rain', '0'))
                
                rain_3hr = rain_prev + rain_t + rain_next
                
                p_vis, p_wx, p_clouds = self._get_projected_conditions(
                    entry, 
                    curr_dt, 
                    history, 
                    rain_3hr_sum=rain_3hr,
                    prev_vis=last_known_vis,
                    prev_clouds=last_known_clouds
                )
                
                last_known_vis = p_vis
                last_known_clouds = p_clouds
                
                p_vis = self._normalize_visibility(p_vis)
                
                d_str = entry.get('Dir', '0')
                s_str = entry.get('WS', '0')
                g_str = entry.get('Gust', '0')
                
                wspd = float(s_str or 0)
                wgust = float(g_str or 0)
                wdir = float(d_str or 0)
                
                s_next = 999
                next_entry = data_map.get(next_dt)
                if next_entry:
                    s_next = float(next_entry.get('WS', '0'))
                
                if s_next == 999: s_next = wspd

                enter_vrb = (wspd <= 3 and s_next <= 3)
                exit_vrb = (wspd >= 5 and s_next >= 5)
                
                prev_is_vrb = False
                if timeline:
                    prev_is_vrb = timeline[-1].get('is_vrb', False)

                if prev_is_vrb:
                    is_vrb_condition = not exit_vrb
                else:
                    is_vrb_condition = enter_vrb
                
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
                             
                timeline.append(state)
            
            curr_dt += datetime.timedelta(hours=1)
            
        return timeline

    def _consolidate_tempo_groups(self, timeline, prevailing_plan=None):
        """
        Finds continuous blocks of Gust >= 17 and creates merged TEMPO groups.
        - Rules: Max 4 Hours, Gust = Wspd + 10
        - Cross-Check: Skips if redundant with prevailing_plan.
        """
        groups = []
        masked_times = set()
        if not timeline: return groups, masked_times
        if prevailing_plan is None: prevailing_plan = {}
        
        i = 0
        while i < len(timeline):
            state = timeline[i]
            if state['wgust'] >= 17:
                                    
                j = i + 1
                while j < len(timeline):
                    if timeline[j]['wgust'] < 17: break
                    j += 1
                block_start_idx = i
                block_end_idx = j
                
                curr_idx = block_start_idx
                while curr_idx < block_end_idx:
                    chunk_end_idx = min(curr_idx + 4, block_end_idx)
                    
                    chunk_max_ws = 0
                    for k in range(curr_idx, chunk_end_idx):
                        if timeline[k]['wspd'] > chunk_max_ws: chunk_max_ws = timeline[k]['wspd']
                    
                    reported_spd = chunk_max_ws
                    reported_gust = reported_spd + 10
                    
                    p_state = prevailing_plan.get(timeline[curr_idx]['dt'], {})
                    if p_state.get('wspd', 0) >= 15 or float(p_state.get('wgust', 0)) >= 17:
                                                                        
                        curr_idx = chunk_end_idx
                        continue

                    s_dt = timeline[curr_idx]['dt']
                    e_dt = timeline[chunk_end_idx - 1]['dt'] + datetime.timedelta(hours=1)
                    while s_dt < e_dt:
                        masked_times.add(s_dt)
                        s_dt += datetime.timedelta(hours=1)
                    
                    s_dt = timeline[curr_idx]['dt']        
                    s_str = f"{s_dt.day:02d}{s_dt.hour:02d}"
                    e_str = f"{e_dt.day:02d}{e_dt.hour:02d}"
                    d_val = timeline[curr_idx]['wdir'] 
                    d_fmt = self._round_to_nearest_10(d_val)
                    if d_fmt == "000" and reported_spd > 0: d_fmt = "360"
                    
                    wind_str = f"{d_fmt}{int(reported_spd):02d}G{int(reported_gust):02d}KT"
                    groups.append(f"TEMPO {s_str}/{e_str} {wind_str}")
                    curr_idx = chunk_end_idx
                i = block_end_idx 
            else:
                i += 1
        
        i = 0
        while i < len(timeline):
            state = timeline[i]
            if state.get('rain_3hr', 0.0) > 50:
                j = i + 1
                while j < len(timeline):
                    if timeline[j].get('rain_3hr', 0.0) <= 50: break
                    j += 1
                block_start = i
                block_end = j
                curr = block_start
                while curr < block_end:
                    chunk_end = min(curr + 6, block_end)
                    
                    p_state = prevailing_plan.get(timeline[curr]['dt'], {})
                    p_wx = p_state.get('wx', '')
                    if "+RA" in p_wx:
                                                        
                         curr = chunk_end
                         continue

                    s_dt = timeline[curr]['dt']
                    e_dt_validity = timeline[chunk_end - 1]['dt'] + datetime.timedelta(hours=1)
                    s_str = f"{s_dt.day:02d}{s_dt.hour:02d}"
                    e_str = f"{e_dt_validity.day:02d}{e_dt_validity.hour:02d}"
                    
                    min_vis_str = "9999"
                    min_v_val = 9999
                    for k in range(curr, chunk_end):
                        try:
                            v = int(timeline[k]['vis'])
                            if v < min_v_val: 
                                min_v_val = v
                                min_vis_str = timeline[k]['vis']
                        except: pass
                            
                    groups.append(f"TEMPO {s_str}/{e_str} {min_vis_str} +RA +SHRA")
                    curr = chunk_end
                i = block_end
            else:
                i += 1

        i = 0
        while i < len(timeline):
            state = timeline[i]
            if state['dt'] in masked_times:
                i += 1
                continue
            try: vis_val = int(state['vis'])
            except: vis_val = 9999
            
            if vis_val <= 1500:
                j = i + 1
                while j < len(timeline):
                    if timeline[j]['dt'] in masked_times: break
                    try: next_v = int(timeline[j]['vis'])
                    except: next_v = 9999
                    if next_v > 1500: break
                    j += 1
                
                if (j - i) >= 2:
                    block_start = i
                    block_end = j
                    curr = block_start
                    while curr < block_end:
                        chunk_end = min(curr + 4, block_end)
                        
                        min_vis_str = "9999"
                        min_v_val = 9999
                        wx_set = set()
                        for k in range(curr, chunk_end):
                            try:
                                v = int(timeline[k]['vis'])
                                if v < min_v_val:
                                    min_v_val = v
                                    min_vis_str = timeline[k]['vis']
                            except: pass
                            w_k = timeline[k]['wx']
                            if w_k:
                                for code in w_k.split():
                                    if code not in ["NSW", ""]: wx_set.add(code)
                        
                        is_invalid = False
                        
                        p_state = prevailing_plan.get(timeline[curr]['dt'], {})
                        if p_state.get('vis') == min_vis_str:
                            is_invalid = True
                        
                        if not is_invalid and block_end < len(timeline):
                            after_state = timeline[block_end]
                            if after_state['vis'] == min_vis_str:
                                is_invalid = True
                        
                        if is_invalid:
                            curr = chunk_end
                                                                                           
                            continue

                        s_dt = timeline[curr]['dt']
                        e_dt_validity = timeline[chunk_end - 1]['dt'] + datetime.timedelta(hours=1)
                        s_str = f"{s_dt.day:02d}{s_dt.hour:02d}"
                        e_str = f"{e_dt_validity.day:02d}{e_dt_validity.hour:02d}"
                        wx_list = sorted(list(wx_set))
                        wx_str = " ".join(wx_list)
                        
                        mask_cursor = s_dt
                        while mask_cursor < e_dt_validity:
                            masked_times.add(mask_cursor)
                            mask_cursor += datetime.timedelta(hours=1)
                        
                        groups.append(f"TEMPO {s_str}/{e_str} {min_vis_str} {wx_str}".strip())
                        curr = chunk_end
                    i = block_end
                else: i += 1
            else: i += 1

        return groups, masked_times

    def _generate_change_groups(self, timeline, init_vis, init_clouds, init_wx, init_wind_obj, masked_times=None):
        """
        Generates BECMG groups with smoothing (Debouncing 1-hour changes).
        Skips generation for times in masked_times.
        """
        groups = []
        if not timeline: return groups
        if masked_times is None: masked_times = set()
        
        curr_vis = init_vis
        curr_clouds = init_clouds
        curr_wx = init_wx
        curr_wdir = init_wind_obj['d']
        curr_wspd = init_wind_obj['s']
        curr_is_vrb = init_wind_obj.get('is_vrb', False)
        
        i = 0
        while i < len(timeline):
            state = timeline[i]
            
            if state['dt'] in masked_times:
                                                                        
                curr_wdir = state['wdir']
                curr_wspd = state['wspd']
                curr_vis = state['vis']
                curr_clouds = state['clouds']
                curr_wx = state['wx']
                curr_is_vrb = state['is_vrb']
                i += 1
                continue
            
            wx_chg = (state['wx'] != curr_wx)
            
            diff_dir = abs(state['wdir'] - curr_wdir)
            if diff_dir > 180: diff_dir = 360 - diff_dir
            
            dir_significant = (diff_dir >= 60)
            spd_significant = (abs(state['wspd'] - curr_wspd) >= 10)
            
            vrb_chg = (state['is_vrb'] != curr_is_vrb)
            
            if curr_is_vrb and state['is_vrb']:
                dir_significant = False
                spd_significant = False
            
            wind_chg = dir_significant or spd_significant or vrb_chg
            
            vis_chg = self._check_vis_limit_change(curr_vis, state['vis'])
            
            cloud_chg = (state['clouds'] != curr_clouds)
            
            if wind_chg or vis_chg or cloud_chg:
                                  
                is_transient = False
                if i + 1 < len(timeline):
                    next_state = timeline[i+1]
                    
                    wx_consistent = (state['wx'] == next_state['wx'])
                    
                    d_diff_next = abs(state['wdir'] - next_state['wdir'])
                    if d_diff_next > 180: d_diff_next = 360 - d_diff_next
                    wind_consistent = (d_diff_next < 60) and (abs(state['wspd'] - next_state['wspd']) < 10)
                    
                    vis_consistent = not self._check_vis_limit_change(state['vis'], next_state['vis'])
                    cloud_consistent = (state['clouds'] == next_state['clouds'])
                    
                    if (dir_significant or spd_significant) and not wind_consistent: is_transient = True
                    if vis_chg and not vis_consistent: is_transient = True
                    if wx_chg and not wx_consistent: is_transient = True
                    if cloud_chg and not cloud_consistent: is_transient = True
                
                if is_transient:
                    i += 1
                    continue
                    
                target_state = state
                check_ahead = 1
                
                while check_ahead <= 2 and (i + check_ahead) < len(timeline):
                    next_s = timeline[i + check_ahead]
                    
                    n_wind = (abs(next_s['wdir'] - target_state['wdir']) >= 60) 
                    n_vis = self._check_vis_limit_change(target_state['vis'], next_s['vis'])
                    n_wx = (next_s['wx'] != target_state['wx'])
                    n_cld = (next_s['clouds'] != target_state['clouds'])
                    n_vrb = (next_s['is_vrb'] != target_state['is_vrb'])
                    
                    if target_state['is_vrb'] and next_s['is_vrb']:
                        n_wind = False
                        
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
                
                out_parts.append(self._format_wind(target_state['wdir'], target_state['wspd'], target_state['wgust'], is_vrb=target_state['is_vrb']))
                
                out_parts.append(target_state['vis'])
                
                if target_state['wx']:
                    out_parts.append(target_state['wx'])
                elif curr_wx and not target_state['wx']:
                    out_parts.append("NSW")
                
                out_parts.append(target_state['clouds'])

                grp = " ".join(part for part in out_parts if part).strip()
                if len(out_parts) > 1:                                            
                    groups.append(grp)
                
                curr_wdir = target_state['wdir']
                curr_wspd = target_state['wspd']
                curr_vis = target_state['vis']
                curr_clouds = target_state['clouds']
                curr_wx = target_state['wx']
                curr_is_vrb = target_state['is_vrb']
                
                i += (1 + steps_to_skip)
                continue
                
            i += 1
            
        return groups

    def _build_prevailing_plan(self, timeline, init_vis, init_clouds, init_wx, init_wind_obj):
        """
        Calculates the prevailing state at every hour of the timeline.
        This captures the transitions (BECMGs) so TEMPO logic knows the hourly baseline.
        """
        plan = {}
        if not timeline: return plan
        
        curr_state = {
            'vis': init_vis,
            'clouds': init_clouds,
            'wx': init_wx,
            'wdir': init_wind_obj['d'],
            'wspd': init_wind_obj['s'],
            'is_vrb': init_wind_obj.get('is_vrb', False)
        }
        
        curr_vis = init_vis
        curr_clouds = init_clouds
        curr_wx = init_wx
        curr_wdir = init_wind_obj['d']
        curr_wspd = init_wind_obj['s']
        curr_is_vrb = init_wind_obj.get('is_vrb', False)
        
        i = 0
        while i < len(timeline):
            state = timeline[i]
            
            diff_dir = abs(state['wdir'] - curr_wdir)
            if diff_dir > 180: diff_dir = 360 - diff_dir
            
            dir_significant = (diff_dir >= 60)
            spd_significant = (abs(state['wspd'] - curr_wspd) >= 10)
            vrb_chg = (state['is_vrb'] != curr_is_vrb)
            
            if curr_is_vrb and state['is_vrb']:
                dir_significant = False
                spd_significant = False
                
            wind_chg = dir_significant or spd_significant or vrb_chg
            vis_chg = self._check_vis_limit_change(curr_vis, state['vis'])
            cloud_chg = (state['clouds'] != curr_clouds)
            
            if wind_chg or vis_chg or cloud_chg:
                                                                
                target_state = state
                check_ahead = 1
                while check_ahead <= 2 and (i + check_ahead) < len(timeline):
                    next_s = timeline[i + check_ahead]
                    n_wind = (abs(next_s['wdir'] - target_state['wdir']) >= 60) 
                    n_vis = self._check_vis_limit_change(target_state['vis'], next_s['vis'])
                    n_cld = (next_s['clouds'] != target_state['clouds'])
                    n_vrb = (next_s['is_vrb'] != target_state['is_vrb'])
                    
                    if target_state['is_vrb'] and next_s['is_vrb']:
                        n_wind = False
                        
                    if n_wind or n_vis or n_cld or n_vrb: target_state = next_s
                    check_ahead += 1
                
                curr_vis = target_state['vis']
                curr_clouds = target_state['clouds']
                curr_wx = target_state['wx']
                curr_wdir = target_state['wdir']
                curr_wspd = target_state['wspd']
                curr_is_vrb = target_state['is_vrb']
                
                steps_to_jump = timeline.index(target_state) - i
                
                for k in range(i, len(timeline)):
                    plan[timeline[k]['dt']] = {
                        'vis': curr_vis,
                        'clouds': curr_clouds,
                        'wx': curr_wx,
                        'wdir': curr_wdir,
                        'wspd': curr_wspd,
                        'is_vrb': curr_is_vrb
                    }
                
                i += (1 + steps_to_jump)
                continue
            
            if timeline[i]['dt'] not in plan:
                plan[timeline[i]['dt']] = {
                    'vis': curr_vis,
                    'clouds': curr_clouds,
                    'wx': curr_wx,
                    'wdir': curr_wdir,
                    'wspd': curr_wspd,
                    'is_vrb': curr_is_vrb
                }
            i += 1
            
        return plan

    def _get_group_sort_key(self, group_str, issue_dt):
        """
        Parses the start DDHH from a group string and resolves it to a full datetime
        for correct sorting (handling month rollover).
        Format: TYPE DDHH/DDHH ...
        """
        import re
        m = re.search(r'\s(\d{2})(\d{2})/', group_str)
        if not m:
                                                                       
             return datetime.datetime.max
             
        day = int(m.group(1))
        hour = int(m.group(2))
        
        resolved_dt = issue_dt.replace(day=day, hour=hour, minute=0, second=0)
        
        if resolved_dt < issue_dt - datetime.timedelta(hours=12):
             resolved_dt += datetime.timedelta(days=28)                   
                                                                                                     
             if day < issue_dt.day:
                 pass                         
        
        if resolved_dt < issue_dt - datetime.timedelta(days=1):
             resolved_dt += datetime.timedelta(days=30)
             
        return resolved_dt

    def generate_long_taf(self, imd_data, ogimet_data):
        station = ogimet_data.get('station', 'XXXX')
        issue_str, issue_dt = self._get_standard_issue_time()
        
        start_valid = issue_dt + datetime.timedelta(hours=1)
        end_valid = start_valid + datetime.timedelta(hours=30)
        validity = f"{start_valid.day:02d}{start_valid.hour:02d}/{end_valid.day:02d}{end_valid.hour:02d}"
        
        timeline = self._build_forecast_timeline(imd_data, ogimet_data, start_valid, end_valid)
        
        if not timeline:
             return f"TAF {station} {issue_str} {validity} NIL"

        base = timeline[0]
        init_wind = self._format_wind(base['wdir'], base['wspd'], base['wgust'], is_vrb=base['is_vrb'])
        taf_body = f"{init_wind} {base['vis']} {base['wx']} {base['clouds']}".strip()
        taf_body = " ".join(taf_body.split())
        
        init_wind_obj = {'d': base['wdir'], 's': base['wspd'], 'is_vrb': base['is_vrb']}
        
        prevailing_plan = self._build_prevailing_plan(timeline, base['vis'], base['clouds'], base['wx'], init_wind_obj)
        
        tempo_groups, masked_times = self._consolidate_tempo_groups(timeline, prevailing_plan)
        
        becmg_groups = self._generate_change_groups(timeline[1:], base['vis'], base['clouds'], base['wx'], init_wind_obj, masked_times)
        
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
        
        prevailing_plan = self._build_prevailing_plan(timeline, base['vis'], base['clouds'], base['wx'], init_wind_obj)
        
        tempo_groups, masked_times = self._consolidate_tempo_groups(timeline, prevailing_plan)
        becmg_groups = self._generate_change_groups(timeline[1:], base['vis'], base['clouds'], base['wx'], init_wind_obj, masked_times)
        
        all_groups = becmg_groups + tempo_groups
        all_groups.sort(key=lambda g: self._get_group_sort_key(g, issue_dt))
        
        parts = [f"TAF {station} {issue_str} {validity} {taf_body}"]
        parts.extend(all_groups)
        
        return "\n".join(parts) + "="

