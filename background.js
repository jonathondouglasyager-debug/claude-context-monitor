// Minimal background script
// Could be used for periodic alarms or icon badges in future versions

chrome.runtime.onInstalled.addListener(() => {
    console.log("Claude Context Monitor Installed");
});
