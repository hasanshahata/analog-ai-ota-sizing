import numpy as np
try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError:
    gym = None

class OTA5tGymEnv(gym.Env):
    """
    Goal-Conditioned Gymnasium environment for RL agents.
    V2: Ideal Current Source, Dynamic CL, Area Penalty, Hard Constraints.
    """
    def __init__(self, ota, bounds, max_steps=100):
        if gym is None:
            raise ImportError("gymnasium is required for the RL environment")
            
        self.ota = ota
        self.bounds = np.array(bounds) # 5 parameters [L1, gmid1, L3, gmid3, Itail]
        self.max_steps = max_steps
        
        # Action space: 5 parameters
        self.action_space = gym.spaces.Box(low=-1.0, high=1.0, shape=(5,), dtype=np.float32)
        
        # Observation space: 4 (Current Perf) + 4 (Target Specs) = 8
        # [Gain, GBW, CL, Power]
        self.observation_space = gym.spaces.Box(low=-np.inf, high=np.inf, shape=(8,), dtype=np.float32)
        
        self.current_step = 0
        self.target_specs = self._sample_target_specs()
        self.state = self._get_random_valid_state()
        self.current_cost = self._evaluate_state(self.state)[0]
        
    def _sample_target_specs(self):
        """Randomly sample achievable targets."""
        gain = np.random.uniform(20.0, 45.0)          # dB
        gbw = np.random.uniform(50e6, 300e6)          # Hz
        cl_pf = np.random.uniform(0.1, 5.0)           # pF
        power = np.random.uniform(50e-6, 400e-6)      # Watts
        
        return {
            'Gain_min': gain,
            'GBW_min': gbw,
            'CL_pF': cl_pf,
            'Power_max': power
        }
        
    def _calc_cost(self, perf):
        """Flawlessly scaled dynamic cost function (0 to ~2000)."""
        if perf is None:
            return 2000.0
            
        cost = 0.0
        
        # 1. Base Optimization (Encourages low power and area, 0 to 5 points max)
        cost += (perf['Power'] / 1e-6) * 0.01 
        cost += perf['Area'] * 1e12 * 0.1
        
        # 2. Soft Penalties (Forcing it to hit Gain/GBW, max 1250 points)
        if perf['DC_Gain_dB'] < self.target_specs['Gain_min']:
            gain_miss = self.target_specs['Gain_min'] - perf['DC_Gain_dB']
            cost += (min(gain_miss, 50.0) ** 2) * 0.5 
            
        if perf['GBW'] < self.target_specs['GBW_min']:
            gbw_miss = (self.target_specs['GBW_min'] - perf['GBW']) / 1e6
            cost += (min(gbw_miss, 500.0) ** 2) * 0.005 
            
        # 3. Hard Cliff Constraints (Instantly adds 200+ points if rule broken)
        if perf['Power'] > self.target_specs['Power_max']:
            excess_power = (perf['Power'] - self.target_specs['Power_max']) / 1e-6
            cost += 200.0 + min(excess_power * 1.0, 100.0)
            
        max_W_nmos = max([
            perf['devices']['M1']['W'],
            perf['devices']['M2']['W'],
            perf['devices']['M5']['W']
        ])
        if max_W_nmos > 250e-6:
            excess_w_nmos = (max_W_nmos - 250e-6) / 1e-6
            cost += 200.0 + min(excess_w_nmos * 1.0, 100.0)
            
        max_W_pmos = max([
            perf['devices']['M3']['W'],
            perf['devices']['M4']['W']
        ])
        if max_W_pmos > 750e-6:
            excess_w_pmos = (max_W_pmos - 750e-6) / 1e-6
            cost += 200.0 + min(excess_w_pmos * 1.0, 100.0)
            
        if perf['PM'] < 45.0:
            pm_miss = min(45.0 - perf['PM'], 45.0)
            cost += (pm_miss ** 2) * 0.2
            
        if perf['min_sat_margin'] < 0.05:
            cost += 100.0
            
        return cost

    def _get_random_valid_state(self):
        return np.random.uniform(self.bounds[:, 0], self.bounds[:, 1])
        
    def _evaluate_state(self, x):
        try:
            # Pass CL dynamically
            cl_farads = self.target_specs['CL_pF'] * 1e-12
            perf = self.ota.evaluate(x, CL=cl_farads)
            return self._calc_cost(perf), perf
        except Exception:
            return 1e9, None
            
    def _normalize_state(self, perf):
        """Construct the 8-D Observation: [Current Perf] + [Target Specs]"""
        if perf is None:
            current = np.zeros(4, dtype=np.float32)
        else:
            current = np.array([
                perf['DC_Gain_dB'] / 40.0,
                perf['GBW'] / 1e8,
                self.target_specs['CL_pF'] / 5.0, # Target CL is the environment condition
                perf['Power'] / 300e-6
            ], dtype=np.float32)
            
        targets = np.array([
            self.target_specs['Gain_min'] / 40.0,
            self.target_specs['GBW_min'] / 1e8,
            self.target_specs['CL_pF'] / 5.0,
            self.target_specs['Power_max'] / 300e-6
        ], dtype=np.float32)
        
        return np.concatenate([current, targets])
        
    def reset(self, seed=None, options=None):
        self.current_step = 0
        self.target_specs = self._sample_target_specs()
        self.state = self._get_random_valid_state()
        self.current_cost, perf = self._evaluate_state(self.state)
        return self._normalize_state(perf), {}
        
    def step(self, action):
        self.current_step += 1
        
        # Action scales delta dynamically
        delta = action * (self.bounds[:, 1] - self.bounds[:, 0]) * 0.1
        new_state = np.clip(self.state + delta, self.bounds[:, 0], self.bounds[:, 1])
        
        new_cost, perf = self._evaluate_state(new_state)
        
        # Reward: Difference in cost
        reward = self.current_cost - new_cost
        
        self.state = new_state
        self.current_cost = new_cost
        
        # Terminate if cost is exceptionally low
        terminated = bool(new_cost < 10.0) 
        truncated = bool(self.current_step >= self.max_steps)
        
        return self._normalize_state(perf), reward, terminated, truncated, {}
