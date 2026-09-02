from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import numpy as np

# Load our local modules
from stable_baselines3 import PPO
from tech_luts.lut_utils import LUT
from core.device_model import DeviceModel
from circuits.ota5t import OTA5T
from optimizer.rl_environment import OTA5tGymEnv

# Initialize App
app = FastAPI(title="Analog AI Optimizer API")

# Define Data Model for Input
class SpecsInput(BaseModel):
    Gain_min: float = 40.0
    GBW_min: float = 200.0 # MHz
    PM_min: float = 60.0
    Power_max: float = 150.0 # uW
    SR_min: float = 50.0 # V/us
    Swing_min: float = 0.8
    ICMR_max: float = 0.4
    Sat_margin_min: float = 0.05

# Global Variables for loaded models
env = None
model = None
ota = None

@app.on_event("startup")
async def startup_event():
    global env, model, ota
    print("Loading 5.5GB LUTs into memory... This might take a few seconds.")
    nch_path = 'tech_luts/TSMC_fast_65nm_nch.pkl'
    pch_path = 'tech_luts/TSMC_fast_65nm_pch.pkl'
    
    if not os.path.exists(nch_path):
        raise RuntimeError(f"Missing {nch_path}")
        
    nch = LUT(nch_path)
    pch = LUT(pch_path)
    dm = DeviceModel(nch, pch)
    ota = OTA5T(dm, vdd=1.2, cl=1e-12)
    ota.Vicm = 0.5
    
    bounds = [
        (60e-9, 1.0e-6),  # L1
        (5.0, 25.0),      # gmid1
        (60e-9, 1.0e-6),  # L3
        (5.0, 25.0),      # gmid3
        (60e-9, 1.0e-6),  # L5
        (5.0, 25.0),      # gmid5
        (10e-6, 500e-6)   # Itail
    ]
    env = OTA5tGymEnv(ota, bounds=bounds, max_steps=100)
    
    model_path = 'universal_ppo_agent_65nm.zip'
    if not os.path.exists(model_path):
        raise RuntimeError(f"Missing {model_path}")
    model = PPO.load(model_path, env=env)
    print("Backend Initialized and Ready!")


@app.post("/api/optimize")
async def optimize(specs: SpecsInput):
    # Convert units to base SI for the environment
    custom_target = {
        'Gain_min': specs.Gain_min,
        'GBW_min': specs.GBW_min * 1e6,
        'PM_min': specs.PM_min,
        'Power_max': specs.Power_max * 1e-6,
        'SR_min': specs.SR_min * 1e6,
        'Swing_min': specs.Swing_min,
        'ICMR_max': specs.ICMR_max,
        'Sat_margin_min': specs.Sat_margin_min
    }
    
    obs, _ = env.reset()
    env.target_specs = custom_target
    perf = ota.evaluate(env.state)
    obs = env._normalize_state(perf)
    
    for step in range(50):
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated:
            break
            
    final_perf = ota.evaluate(env.state)
    L1, gmid1, L3, gmid3, L5, gmid5, Itail = env.state
    
    # We can fetch exact W values from final_perf['devices']
    m1 = final_perf['devices']['M1']
    m3 = final_perf['devices']['M3']
    m5 = final_perf['devices']['M5']

    return {
        "status": "success",
        "sizing": {
            "Itail_uA": round(Itail * 1e6, 2),
            "M1_M2": {"W_um": round(m1['W']*1e6, 2), "L_nm": round(m1['L']*1e9, 1), "gmid": round(gmid1, 2)},
            "M3_M4": {"W_um": round(m3['W']*1e6, 2), "L_nm": round(m3['L']*1e9, 1), "gmid": round(gmid3, 2)},
            "M5": {"W_um": round(m5['W']*1e6, 2), "L_nm": round(m5['L']*1e9, 1), "gmid": round(gmid5, 2)},
        },
        "performance": {
            "Gain_dB": round(final_perf['DC_Gain_dB'], 2),
            "GBW_MHz": round(final_perf['GBW'] / 1e6, 2),
            "PM_Deg": round(final_perf['PM'], 2),
            "Power_uW": round(final_perf['Power'] * 1e6, 2),
            "SR_Vus": round(final_perf['SR'] / 1e6, 2),
            "Swing_V": round(final_perf['Swing'], 2),
            "ICMR_V": round(final_perf['ICMR_min'], 2)
        }
    }

app.mount("/static", StaticFiles(directory="web_app/static"), name="static")

@app.get("/")
async def root():
    return FileResponse("web_app/static/index.html")
