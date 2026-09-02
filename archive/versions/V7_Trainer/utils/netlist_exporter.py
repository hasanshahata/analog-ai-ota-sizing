import numpy as np

class NetlistExporter:
    @staticmethod
    def export_spectre(perf, filename="5t_ota_sized.scs"):
        """
        Exports the sized 5T OTA to a Cadence Spectre netlist format.
        """
        m1, m2 = perf['devices']['M1'], perf['devices']['M2']
        m3, m4 = perf['devices']['M3'], perf['devices']['M4']
        m5 = perf['devices']['M5']
        
        with open(filename, 'w') as f:
            f.write("// 5T OTA Sized by Analog AI Optimizer\n")
            f.write("// Technology: TSMC 65nm\n\n")
            
            f.write("simulator lang=spectre\n")
            f.write("global 0 vdd!\n\n")
            
            f.write("// Subcircuit Definition\n")
            f.write("subckt OTA5T (inp inm vout)\n")
            
            # Format: Name Drain Gate Source Bulk Model W L
            # Assuming models are 'nch' and 'pch'
            f.write(f"M1 (vmirror inp vtail 0) nch w={m1['W']*1e6:.4f}u l={m1['L']*1e6:.4f}u\n")
            f.write(f"M2 (vout inm vtail 0) nch w={m2['W']*1e6:.4f}u l={m2['L']*1e6:.4f}u\n")
            f.write(f"M3 (vmirror vmirror vdd! vdd!) pch w={m3['W']*1e6:.4f}u l={m3['L']*1e6:.4f}u\n")
            f.write(f"M4 (vout vmirror vdd! vdd!) pch w={m4['W']*1e6:.4f}u l={m4['L']*1e6:.4f}u\n")
            
            # Tail bias voltage is VGS5
            f.write(f"M5 (vtail vbiastail 0 0) nch w={m5['W']*1e6:.4f}u l={m5['L']*1e6:.4f}u\n")
            
            # Bias voltage source inside the subckt for simplicity, or we can expose it
            f.write(f"Vbias (vbiastail 0) vsource dc={m5['VGS']:.4f}\n")
            
            f.write("ends OTA5T\n\n")
            
            f.write("// Testbench\n")
            f.write("Vdd (vdd! 0) vsource dc=1.2\n")
            f.write("Vcm_in (vicm 0) vsource dc=0.6\n")
            
            # AC Analysis Setup (Differential input)
            f.write("Vinp (inp vicm) vsource dc=0 mag=0.5\n")
            f.write("Vinm (inm vicm) vsource dc=0 mag=-0.5 phase=180\n")
            
            f.write("X1 (inp inm vout) OTA5T\n")
            f.write("CL (vout 0) capacitor c=1p\n\n")
            
            f.write("// Analyses\n")
            f.write("dcOp dc\n")
            f.write("acSweep ac start=1 stop=10G dec=20\n")
        
        print(f"Exported Spectre netlist to {filename}")

