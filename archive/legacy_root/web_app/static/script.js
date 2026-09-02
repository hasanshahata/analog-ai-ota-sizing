document.getElementById('specs-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    // UI Elements
    const btn = document.getElementById('submit-btn');
    const btnText = btn.querySelector('.btn-text');
    const spinner = btn.querySelector('.spinner');
    const outputSection = document.getElementById('output-section');
    const sizingDetails = document.getElementById('sizing-details');
    const perfDetails = document.getElementById('perf-details');
    
    // Show loading state
    btn.disabled = true;
    btnText.classList.add('hidden');
    spinner.classList.remove('hidden');
    outputSection.classList.add('hidden');
    
    // Gather form data
    const formData = new FormData(e.target);
    const payload = {};
    formData.forEach((value, key) => {
        payload[key] = parseFloat(value);
    });
    
    try {
        const response = await fetch('/api/optimize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) throw new Error('API Error');
        
        const data = await response.json();
        
        // Render Sizing
        sizingDetails.innerHTML = `
            <div class="transistor-block">
                <div class="transistor-name">Total Tail Current</div>
                <div class="data-row"><span class="data-label">I_tail</span><span class="data-value">${data.sizing.Itail_uA.toFixed(2)} µA</span></div>
            </div>
            <div class="transistor-block">
                <div class="transistor-name">Input Differential Pair (M1, M2)</div>
                <div class="data-row"><span class="data-label">Width (W)</span><span class="data-value">${data.sizing.M1_M2.W_um.toFixed(2)} µm</span></div>
                <div class="data-row"><span class="data-label">Length (L)</span><span class="data-value">${data.sizing.M1_M2.L_nm.toFixed(1)} nm</span></div>
                <div class="data-row"><span class="data-label">gm/Id</span><span class="data-value">${data.sizing.M1_M2.gmid.toFixed(2)}</span></div>
            </div>
            <div class="transistor-block">
                <div class="transistor-name">Current Mirror Load (M3, M4)</div>
                <div class="data-row"><span class="data-label">Width (W)</span><span class="data-value">${data.sizing.M3_M4.W_um.toFixed(2)} µm</span></div>
                <div class="data-row"><span class="data-label">Length (L)</span><span class="data-value">${data.sizing.M3_M4.L_nm.toFixed(1)} nm</span></div>
                <div class="data-row"><span class="data-label">gm/Id</span><span class="data-value">${data.sizing.M3_M4.gmid.toFixed(2)}</span></div>
            </div>
            <div class="transistor-block">
                <div class="transistor-name">Tail Current Source (M5)</div>
                <div class="data-row"><span class="data-label">Width (W)</span><span class="data-value">${data.sizing.M5.W_um.toFixed(2)} µm</span></div>
                <div class="data-row"><span class="data-label">Length (L)</span><span class="data-value">${data.sizing.M5.L_nm.toFixed(1)} nm</span></div>
                <div class="data-row"><span class="data-label">gm/Id</span><span class="data-value">${data.sizing.M5.gmid.toFixed(2)}</span></div>
            </div>
        `;
        
        // Render Performance
        perfDetails.innerHTML = `
            <div class="data-row"><span class="data-label">DC Gain</span><span class="data-value" style="color: ${data.performance.Gain_dB >= payload.Gain_min ? 'var(--success)' : 'var(--danger)'}">${data.performance.Gain_dB.toFixed(2)} dB</span></div>
            <div class="data-row"><span class="data-label">GBW</span><span class="data-value" style="color: ${data.performance.GBW_MHz >= payload.GBW_min ? 'var(--success)' : 'var(--danger)'}">${data.performance.GBW_MHz.toFixed(2)} MHz</span></div>
            <div class="data-row"><span class="data-label">Phase Margin</span><span class="data-value" style="color: ${data.performance.PM_Deg >= payload.PM_min ? 'var(--success)' : 'var(--danger)'}">${data.performance.PM_Deg.toFixed(2)}°</span></div>
            <div class="data-row"><span class="data-label">Power</span><span class="data-value" style="color: ${data.performance.Power_uW <= payload.Power_max ? 'var(--success)' : 'var(--danger)'}">${data.performance.Power_uW.toFixed(2)} µW</span></div>
            <div class="data-row"><span class="data-label">Slew Rate</span><span class="data-value" style="color: ${data.performance.SR_Vus >= payload.SR_min ? 'var(--success)' : 'var(--danger)'}">${data.performance.SR_Vus.toFixed(2)} V/µs</span></div>
            <div class="data-row"><span class="data-label">Output Swing</span><span class="data-value" style="color: ${data.performance.Swing_V >= payload.Swing_min ? 'var(--success)' : 'var(--danger)'}">${data.performance.Swing_V.toFixed(2)} V</span></div>
            <div class="data-row"><span class="data-label">ICMR (min)</span><span class="data-value" style="color: ${data.performance.ICMR_V <= payload.ICMR_max ? 'var(--success)' : 'var(--danger)'}">${data.performance.ICMR_V.toFixed(2)} V</span></div>
        `;
        
        outputSection.classList.remove('hidden');
        
        // Smooth scroll to results
        outputSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        
    } catch (error) {
        alert('An error occurred during optimization.');
        console.error(error);
    } finally {
        // Reset button
        btn.disabled = false;
        spinner.classList.add('hidden');
        btnText.classList.remove('hidden');
    }
});
