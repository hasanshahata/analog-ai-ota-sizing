import numpy as np
from scipy.optimize import differential_evolution

class GlobalOptimizer:
    def __init__(self, ota, cost_fn, bounds, popsize=15, maxiter=50):
        self.ota = ota
        self.cost_fn = cost_fn
        self.bounds = bounds
        self.popsize = popsize
        self.maxiter = maxiter
        
        self.best_x = None
        self.best_cost = np.inf
        self.best_perf = None
        self.history = []

    def _objective(self, x):
        # We might get some invalid operating points, so we handle exceptions
        try:
            perf = self.ota.evaluate(x)
            cost = self.cost_fn(perf)
            
            # Keep track of best performance for reporting
            if cost < self.best_cost:
                self.best_cost = cost
                self.best_x = x.copy()
                self.best_perf = perf
                
            return cost
        except Exception as e:
            # If the sizing completely fails (e.g., negative square root, extreme params out of LUT bounds)
            return 1e9

    def optimize(self):
        print(f"Starting Differential Evolution Optimization...")
        
        def callback(xk, convergence):
            print(f"Current Best Cost: {self.best_cost:.2f} | Convergence: {convergence:.4f}")
            self.history.append((xk.copy(), self.best_cost))
            
        result = differential_evolution(
            self._objective, 
            self.bounds,
            strategy='best1bin',
            maxiter=self.maxiter,
            popsize=self.popsize,
            mutation=(0.5, 1.0),
            recombination=0.7,
            tol=1e-3,
            callback=callback,
            disp=True,
            workers=1 # Using 1 worker because LUT interpolation might not be thread-safe depending on backend, or for simple printing
        )
        
        print("Optimization finished.")
        return result, self.best_perf
