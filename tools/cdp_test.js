const { spawn } = require('child_process');
const http = require('http');

async function main() {
    const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
    const chrome = spawn(chromePath, [
        '--headless=new',
        '--remote-debugging-port=9222',
        '--disable-gpu',
        '--no-sandbox',
        '--user-data-dir=C:\\Users\\sri\\AppData\\Local\\Temp\\cdp_test_' + Date.now(),
        'http://localhost:8080/index.html?t=' + Date.now()
    ]);

    console.log('Launched Chrome with remote debugging on port 9222');

    // Wait for Chrome port 9222 to be ready
    let targets = null;
    for (let i = 0; i < 20; i++) {
        await new Promise(r => setTimeout(r, 300));
        try {
            const res = await fetch('http://127.0.0.1:9222/json');
            targets = await res.json();
            if (targets && targets.length > 0) break;
        } catch (e) {}
    }

    if (!targets || targets.length === 0) {
        console.error('Failed to connect to Chrome CDP endpoint.');
        chrome.kill();
        process.exit(1);
    }

    const target = targets.find(t => t.type === 'page' && t.url.includes('localhost')) || targets.find(t => t.type === 'page') || targets[0];
    console.log('Target found:', target.title, target.url);
    const wsUrl = target.webSocketDebuggerUrl;
    const ws = new WebSocket(wsUrl);

    let msgId = 1;
    const pending = new Map();
    const consoleLogs = [];

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.id && pending.has(msg.id)) {
            pending.get(msg.id)(msg);
            pending.delete(msg.id);
        }
        if (msg.method === 'Runtime.consoleAPICalled') {
            consoleLogs.push({ type: msg.params.type, args: msg.params.args.map(a => a.value || a.description) });
        }
        if (msg.method === 'Runtime.exceptionThrown') {
            console.error('>>> RUNTIME EXCEPTION IN BROWSER:', JSON.stringify(msg.params.exceptionDetails, null, 2));
        }
    };

    await new Promise(r => ws.onopen = r);

    function send(method, params = {}) {
        return new Promise((resolve) => {
            const id = msgId++;
            pending.set(id, resolve);
            ws.send(JSON.stringify({ id, method, params }));
        });
    }

    await send('Runtime.enable');
    await send('Page.enable');
    await send('Console.enable');

    console.log('Waiting 2 seconds for initial load & render...');
    await new Promise(r => setTimeout(r, 2000));

    // Evaluate state in browser
    const evalRes = await send('Runtime.evaluate', {
        expression: `
            ({
                clock: document.getElementById('clock-display')?.textContent,
                rescued: document.getElementById('rescued-count')?.textContent,
                queueDepth: document.getElementById('queue-depth-val')?.textContent,
                queueCardsCount: document.querySelectorAll('.queue-card').length,
                firstCardText: document.querySelector('.queue-card')?.innerText,
                diesCount: document.querySelectorAll('.die-box').length,
                simIsRunning: window.simState?.isRunning,
                activeScenario: window.simState?.activeScenario,
                traceLength: window.simState?.trace?.length,
                hasRealCheops: !!window.REAL_CHEOPS_TRACE,
                realCheopsCount: window.REAL_CHEOPS_TRACE?.length
            })
        `,
        returnByValue: true
    });

    console.log('\n--- BROWSER STATE AT LOAD ---');
    console.log(JSON.stringify(evalRes?.result?.result?.value || evalRes, null, 2));

    // Try clicking Start Simulation
    console.log('\nClicking #btn-play-pause...');
    await send('Runtime.evaluate', {
        expression: `document.getElementById('btn-play-pause').click()`
    });

    // Wait 2 seconds while running
    await new Promise(r => setTimeout(r, 2000));

    const runningRes = await send('Runtime.evaluate', {
        expression: `
            ({
                clock: document.getElementById('clock-display')?.textContent,
                rescued: document.getElementById('rescued-count')?.textContent,
                queueDepth: document.getElementById('queue-depth-val')?.textContent,
                queueCardsCount: document.querySelectorAll('.queue-card').length,
                firstCardText: document.querySelector('.queue-card')?.innerText,
                simIsRunning: window.simState?.isRunning,
                s3Completed: window.simState?.s3?.completed?.length,
                s0Completed: window.simState?.s0?.completed?.length,
                s1Misses: window.simState?.s1?.critMisses,
                s3Misses: window.simState?.s3?.critMisses
            })
        `,
        returnByValue: true
    });

    console.log('\n--- BROWSER STATE AFTER 2 SECONDS RUNNING ---');
    console.log(JSON.stringify(runningRes?.result?.result?.value || runningRes, null, 2));

    // Try clicking Step 1 Token
    console.log('\nClicking #btn-step...');
    await send('Runtime.evaluate', {
        expression: `document.getElementById('btn-step').click()`
    });

    await new Promise(r => setTimeout(r, 500));

    const stepRes = await send('Runtime.evaluate', {
        expression: `
            ({
                clock: document.getElementById('clock-display')?.textContent,
                s3Completed: window.simState?.s3?.completed?.length,
                s0Completed: window.simState?.s0?.completed?.length
            })
        `,
        returnByValue: true
    });

    console.log('\n--- BROWSER STATE AFTER STEP 1 TOKEN ---');
    console.log(JSON.stringify(stepRes?.result?.result?.value || stepRes, null, 2));

    console.log('\n--- CONSOLE LOGS CAPTURED ---');
    consoleLogs.forEach(l => console.log(`[${l.type}]`, ...l.args));

    ws.close();
    chrome.kill();
    process.exit(0);
}

main().catch(err => {
    console.error('Test error:', err);
    process.exit(1);
});
