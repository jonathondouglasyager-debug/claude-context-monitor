document.addEventListener('DOMContentLoaded', function () {
    const scanBtn = document.getElementById('scan-now');
    const tokenDisplay = document.getElementById('token-count');
    const riskDisplay = document.getElementById('risk-level');
    const warningBox = document.getElementById('warning-msg');

    // Function to update UI based on response
    function updateUI(response) {
        if (!response) {
            tokenDisplay.textContent = "Error";
            return;
        }

        const tokens = response.estimatedTokens || 0;
        tokenDisplay.textContent = tokens.toLocaleString();

        // Context risk levels (Rough estimates based on generic context windows)
        // 200k context is HUGE, so we are looking for "safe" vs "getting heavy"
        // Just illustrative levels
        if (tokens < 50000) {
            riskDisplay.textContent = "Low (Safe)";
            riskDisplay.style.color = "green";
        } else if (tokens < 150000) {
            riskDisplay.textContent = "Medium";
            riskDisplay.style.color = "orange";
        } else {
            riskDisplay.textContent = "High (Critical)";
            riskDisplay.style.color = "red";
        }

        if (response.warningDetected) {
            warningBox.style.display = "block";
            warningBox.textContent = `⚠️ Warning detected: "${response.warningText}"`;
        } else {
            warningBox.style.display = "none";
        }
    }

    // Send message to content script to scan page
    function scanPage() {
        tokenDisplay.textContent = "Scanning...";

        chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
            if (!tabs[0].url.includes("claude.ai")) {
                tokenDisplay.textContent = "N/A";
                riskDisplay.textContent = "Not Claude tab";
                return;
            }

            chrome.tabs.sendMessage(tabs[0].id, { action: "scan_context" }, function (response) {
                if (chrome.runtime.lastError) {
                    tokenDisplay.textContent = "Refresh Page";
                    console.error(chrome.runtime.lastError);
                    return;
                }
                updateUI(response);
            });
        });
    }

    // Initial scan
    scanPage();

    // Button click scan
    scanBtn.addEventListener('click', scanPage);
});
