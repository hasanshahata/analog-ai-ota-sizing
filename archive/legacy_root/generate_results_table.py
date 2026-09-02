import os
import json
import requests
import glob

def main():
    json_files = glob.glob('test_specs/*.json')
    
    # Markdown Table Header
    markdown_lines = [
        "| Profile Name | Target Specs (Gain/GBW/Power) | Achieved Specs (Gain/GBW/Power) | M1/M2 (W/L) | M3/M4 (W/L) | M5 (W/L) | I_tail (uA) |",
        "|---|---|---|---|---|---|---|"
    ]
    
    for jf in sorted(json_files):
        with open(jf, 'r') as f:
            data = json.load(f)
            
        profile = data.get("profile_name", "Unknown")
        specs = data["specs"]
        
        # Map to API payload
        payload = {
            "Gain_min": specs.get("min_dc_gain_dB", 40.0),
            "GBW_min": specs.get("min_gbw_MHz", 200.0),
            "PM_min": specs.get("min_phase_margin_deg", 60.0),
            "Power_max": specs.get("max_power_consumption_uW", 150.0),
            "SR_min": specs.get("min_slew_rate_V_us", 50.0),
            "Swing_min": specs.get("min_output_swing_V", 0.8),
            # Approximate ICMR max based on range
            "ICMR_max": 1.2 - specs.get("min_icmr_range_V", 0.7)
        }
        
        try:
            resp = requests.post("http://127.0.0.1:8000/api/optimize", json=payload)
            if resp.status_code == 200:
                result = resp.json()
                sz = result['sizing']
                pf = result['performance']
                
                # Format strings
                target_str = f"{payload['Gain_min']}dB / {payload['GBW_min']}MHz / {payload['Power_max']}uW"
                achieved_str = f"{pf['Gain_dB']}dB / {pf['GBW_MHz']}MHz / {pf['Power_uW']}uW"
                
                m12_str = f"{sz['M1_M2']['W_um']}u / {sz['M1_M2']['L_nm']}n"
                m34_str = f"{sz['M3_M4']['W_um']}u / {sz['M3_M4']['L_nm']}n"
                m5_str = f"{sz['M5']['W_um']}u / {sz['M5']['L_nm']}n"
                
                row = f"| **{profile}** | {target_str} | {achieved_str} | {m12_str} | {m34_str} | {m5_str} | {sz['Itail_uA']} |"
                markdown_lines.append(row)
            else:
                markdown_lines.append(f"| **{profile}** | Error | Error | Error | Error | Error | Error |")
        except Exception as e:
            markdown_lines.append(f"| **{profile}** | Error: {e} | Error | Error | Error | Error | Error |")
            
    with open('evaluation_table.md', 'w') as f:
        f.write('\n'.join(markdown_lines))
        
if __name__ == '__main__':
    main()
