import matplotlib.pyplot as plt
import numpy as np

class Visualizer:
    @staticmethod
    def plot_bode(freqs, V_out, filename="bode_plot.png"):
        """
        Plots the Bode plot (Magnitude and Phase) of the OTA AC response.
        """
        mag = 20 * np.log10(np.abs(V_out))
        phase = np.angle(V_out, deg=True)
        
        # Unwrap phase to avoid sharp jumps
        phase = np.unwrap(phase * np.pi / 180.0) * 180.0 / np.pi
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
        
        # Magnitude
        ax1.semilogx(freqs, mag, color='blue', linewidth=2)
        ax1.axhline(0, color='red', linestyle='--', alpha=0.5)
        ax1.set_ylabel('Magnitude (dB)', fontsize=12)
        ax1.grid(True, which="both", ls="-", alpha=0.2)
        ax1.set_title('5T OTA AC Response (Bode Plot)', fontsize=14)
        
        # Phase
        ax2.semilogx(freqs, phase, color='green', linewidth=2)
        ax2.axhline(-180, color='red', linestyle='--', alpha=0.5)
        ax2.set_ylabel('Phase (Degrees)', fontsize=12)
        ax2.set_xlabel('Frequency (Hz)', fontsize=12)
        ax2.grid(True, which="both", ls="-", alpha=0.2)
        
        plt.tight_layout()
        plt.savefig(filename, dpi=300)
        print(f"Bode plot saved to {filename}")
        
    @staticmethod
    def print_design_summary(perf):
        print("\n" + "="*50)
        print("          5T OTA DESIGN SUMMARY          ")
        print("="*50)
        print(f"DC Gain:       {perf['DC_Gain_dB']:.2f} dB")
        print(f"GBW:           {perf['GBW']/1e6:.2f} MHz")
        print(f"Phase Margin:  {perf['PM']:.2f} deg")
        print(f"Power:         {perf['Power']*1e6:.2f} uW")
        print(f"Slew Rate:     {perf['SR']/1e6:.2f} V/us")
        print(f"Output Swing:  {perf['Swing']:.2f} V")
        print(f"ICMR Min:      {perf['ICMR_min']:.2f} V")
        print(f"Total Area:    {perf['Area']*1e12:.2f} um^2")
        print("="*50)
        print(" DEVICE SIZING & BIASING ")
        print("="*50)
        print(f"{'Dev':<5} | {'Type':<4} | {'W (um)':<8} | {'L (um)':<8} | {'ID (uA)':<8} | {'VGS (V)':<7} | {'VDS (V)':<7} | {'VSAT (V)':<8}")
        print("-" * 75)
        for name in ['M1', 'M2', 'M3', 'M4', 'M5']:
            d = perf['devices'][name]
            print(f"{name:<5} | {d['type'].upper():<4} | {d['W']*1e6:<8.2f} | {d['L']*1e6:<8.3f} | {d['ID']*1e6:<8.1f} | {d['VGS']:<7.3f} | {d['VDS']:<7.3f} | {d['VDSAT']:<8.3f}")
        print("="*50)
