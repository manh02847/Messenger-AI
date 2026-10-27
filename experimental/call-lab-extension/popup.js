const fields = ["endpoint", "token", "monitor"];
function request(action) {
  return chrome.runtime.sendMessage({from: "call-lab-popup", action,
    endpoint: document.getElementById("endpoint").value.trim(),
    token: document.getElementById("token").value.trim(),
    monitor: document.getElementById("monitor").checked,
  }).then(result => { document.getElementById("status").textContent = result?.status || "Chưa có trạng thái."; })
    .catch(() => { document.getElementById("status").textContent = "Tiện ích chưa sẵn sàng; mở lại bảng này."; });
}
chrome.storage.session.get(fields).then(saved => {
  for (const field of fields) {
    if (saved[field] === undefined) continue;
    document.getElementById(field)[field === "monitor" ? "checked" : "value"] = saved[field];
  }
  return request("status");
});
document.getElementById("start").addEventListener("click", () => request("start"));
document.getElementById("stop").addEventListener("click", () => request("stop"));
setInterval(() => request("status"), 1500);
