// Listen for requests from popup
chrome.runtime.onMessage.addListener(function (request, sender, sendResponse) {
    if (request.action === "scan_context") {
        const data = analyzePage();
        sendResponse(data);
    }
});

function analyzePage() {
    // 1. Estimate Tokens (Rough count of all text in chat container)
    // Classes might change, so we look for generic message containers if specific ones fail
    // As of late 2024/early 2025, Claude structure varies. 
    // We'll grab the main scrollable area or just body text as a fallback.

    let chatText = "";

    // Attempt to find specific chat message blocks (common selector patterns)
    // This is fragile and may need updates if Anthropic changes class names
    const messageElements = document.querySelectorAll('.font-claude-message, .grid-cols-1, [data-testid="user-message"]');

    if (messageElements.length > 0) {
        messageElements.forEach(el => {
            chatText += el.innerText + " ";
        });
    } else {
        // Fallback: Just grab body text, mostly works for active tab
        chatText = document.body.innerText;
    }

    // 1 token ~= 4 chars (Standard approximation)
    const charCount = chatText.length;
    const estimatedTokens = Math.ceil(charCount / 4);

    // 2. Detect Warnings
    // Look for "remaining" text which usually appears in banners
    let warningDetected = false;
    let warningText = "";

    // Naive text search in body for keywords if specific classes aren't known
    // This is better than strict selectors which break often
    const bodyText = document.body.innerText;
    const warningKeywords = ["messages remaining", "message limit", "until active"];

    // Check specifically for warning banners usually at bottom
    const potentialWarnings = document.querySelectorAll('div[class*="warning"], div[class*="alert"], div[class*="banner"]');

    // Specific check for the floating message limit pill
    if (bodyText.match(/\d+\s+messages\s+remaining/i)) {
        warningDetected = true;
        const match = bodyText.match(/(\d+\s+messages\s+remaining)/i);
        warningText = match ? match[0] : "Message limit warning";
    }

    return {
        estimatedTokens: estimatedTokens,
        warningDetected: warningDetected,
        warningText: warningText
    };
}
