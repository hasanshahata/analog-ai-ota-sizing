import numpy as np
try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError:
    gym = None

class OTA5tGymEnv(gym.Env):
    """
    V11 Goal-Conditioned Gymnasium environment for RL agents.
    Fixes from V10:
    1. Pure negative reward (no survival bonus exploit)
    2. No early termination (agent must endure all steps)
    3. Smooth normalized cost function preserved from V10
    """
    def __init__(self, ota, bounds, max_steps=200):
        if gym is None:
            raise ImportError("gymnasium is required for the RL environment")
            
        self.ota = ota
        self.bounds = np.array(bounds) # 5 parameters [L1, gmid1, L3, gmid3, Itail]
        self.max_steps = max_steps
        
        # Action space: 5 parameters (direct output, mapped to bounds)
        self.action_space = gym.spaces.Box(low=-1.0, high=1.0, shape=(5,), dtype=np.float32)
        
        # Observation space: 5 (Design Params) + 5 (Performance) + 5 (Targets) = 15
        self.observation_space = gym.spaces.Box(low=-np.inf, high=np.inf, shape=(15,), dtype=np.float32)
        
        self.current_step = 0
        self.target_specs = self._sample_target_specs()
        self.state = self._get_random_valid_state()
        self.current_cost = self._evaluate_state(self.state)[0]
        
    def _sample_target_specs(self):
        """Randomly sample achievable targets."""
        gain = np.random.uniform(20.0, 45.0)          # dB
        gbw = np.random.uniform(50e6, 300e6)           # Hz
        cl_pf = np.random.uniform(0.1, 5.0)            # pF
        power = np.random.uniform(50e-6, 400e-6)       # Watts
        
        return {
            'Gain_min': gain,
            'GBW_min': gbw,
            'CL_pF': cl_pf,
            'Power_max': power
        }
        
    def _calc_cost(self, perf):
        """V10 Balanced Normalized Cost Function (No Cliffs)."""
        if perf is None:
            return 1000.0
            
        cost = 0.0
        
        # 1. Gain Penalty
        if perf['DC_Gain_dB'] < self.target_specs['Gain_min']:
            gain_err = (self.target_specs['Gain_min'] - perf['DC_Gain_dB']) / self.target_specs['Gain_min']
            cost += (gain_err * 10.0) ** 2
            
        # 2. GBW Penalty
        if perf['GBW'] < self.target_specs['GBW_min']:
            gbw_err = (self.target_specs['GBW_min'] - perf['GBW']) / self.target_specs['GBW_min']
            cost += (gbw_err * 10.0) ** 2
            
        # 3. Power Penalty
        if perf['Power'] > self.target_specs['Power_max']:
            power_err = (perf['Power'] - self.target_specs['Power_max']) / self.target_specs['Power_max']
            cost += (power_err * 10.0) ** 2
            
        # 4. Phase Margin Penalty
        if perf['PM'] < 45.0:
            pm_err = (45.0 - perf['PM']) / 45.0
            cost += (pm_err * 10.0) ** 2
            
        # 5. Saturation Margin Penalty
        if perf['min_sat_margin'] < 0.05:
            sat_err = (0.05 - perf['min_sat_margin']) / 0.05
            cost += (sat_err * 10.0) ** 2
            
        # 6. Area Penalty
        max_W_nmos = max([perf['devices']['M1']['W'], perf['devices']['M2']['W'], perf['devices']['M5']['W']])
        if max_W_nmos > 250e-6:
            area_err = (max_W_nmos - 250e-6) / 250e-6
            cost += (area_err * 10.0) ** 2
            
        max_W_pmos = max([perf['devices']['M3']['W'], perf['devices']['M4']['W']])
        if max_W_pmos > 750e-6:
            area_err = (max_W_pmos - 750e-6) / 750e-6
            cost += (area_err * 10.0) ** 2
            
        # 7. Gentle Optimization (Base Minimization to pull away from the boundary safely)
        cost += (perf['Power'] / 400e-6) * 0.1
        cost += perf['Area'] * 1e12 * 0.01
            
        return cost

    def _get_random_valid_state(self):
        return np.random.uniform(self.bounds[:, 0], self.bounds[:, 1])
        
    def _evaluate_state(self, x):
        try:
            cl_farads = self.target_specs['CL_pF'] * 1e-12
            perf = self.ota.evaluate(x, CL=cl_farads)
            return self._calc_cost(perf), perf
        except Exception:
            return 1e9, None
            
    def _normalize_state(self, perf):
        """Construct the 15-D Observation: [Design Params] + [Performance] + [Targets]"""
        # Normalize design parameters to [0, 1]
        design_norm = (self.state - self.bounds[:, 0]) / (self.bounds[:, 1] - self.bounds[:, 0])
        
        if perf is None:
            performance = np.zeros(5, dtype=np.float32)
        else:
            performance = np.array([
                perf['DC_Gain_dB'] / 40.0,
                perf['GBW'] / 3e8,
                perf['Power'] / 400e-6,
                perf['PM'] / 90.0,
                max(perf['min_sat_margin'], 0.0) / 0.3
            ], dtype=np.float32)
            
        targets = np.array([
            self.target_specs['Gain_min'] / 40.0,
            self.target_specs['GBW_min'] / 3e8,
            self.target_specs['CL_pF'] / 5.0,
            self.target_specs['Power_max'] / 400e-6,
            45.0 / 90.0  # PM target is always 45 degrees
        ], dtype=np.float32)
        
        return np.concatenate([design_norm.astype(np.float32), performance, targets])
        
    def reset(self, seed=None, options=None):
        self.current_step = 0
        self.target_specs = self._sample_target_specs()
        self.state = self._get_random_valid_state()
        self.current_cost, perf = self._evaluate_state(self.state)
        return self._normalize_state(perf), {}
        
    def step(self, action):
        self.current_step += 1
        
        # Direct parameter output (action maps directly to design space)
        # action is in [-1, 1], map to [lower, upper]
        new_state = self.bounds[:, 0] + (action + 1.0) / 2.0 * (self.bounds[:, 1] - self.bounds[:, 0])
        new_state = np.clip(new_state, self.bounds[:, 0], self.bounds[:, 1])
        
        new_cost, perf = self._evaluate_state(new_state)
        
        # V11 FIX: Pure negative reward. Every step with cost > 0 hurts.
        # The ONLY way to maximize cumulative reward is to drive cost to 0.
        # Clip to [-10, 0] to keep gradients stable for PPO.
        reward = float(np.clip(-new_cost, -10.0, 0.0))
        
        self.state = new_state
        self.current_cost = new_cost
        
        # V11 FIX: No early termination. The agent must endure all 200 steps.
        # A perfect design (cost=0) earns 0 per step. A mediocre design (cost=50)
        # earns -10 per step = -2000 total. There is no survival bonus exploit.
        terminated = False
        truncated = bool(self.current_step >= self.max_steps)
        
        return self._normalize_state(perf), reward, terminated, truncated, {}
