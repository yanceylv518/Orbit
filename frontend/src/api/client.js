async function readJson(response) {
  const text = await response.text();
  if (!text.trim()) {
    return {
      error: `服务没有返回 JSON（HTTP ${response.status}）。请确认 8765 后端服务已经启动。`,
    };
  }
  try {
    return JSON.parse(text);
  } catch {
    return {
      error: `服务返回了非 JSON 响应（HTTP ${response.status}）。请确认 8765 后端服务已经启动。`,
    };
  }
}

export async function fetchAppState() {
  const response = await fetch("/api/state", {
    headers: { Accept: "application/json" },
  });
  const data = await readJson(response);
  if (!response.ok || data.error) {
    return {
      __error: data.error || `读取系统状态失败（HTTP ${response.status}）。`,
    };
  }
  return data;
}

export async function postJson(path, payload = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await readJson(response);
  return { response, data };
}

export async function loginRequest(login, password) {
  const response = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ login, password }),
  });
  const data = await readJson(response);
  return { response, data };
}

export async function logoutRequest() {
  await fetch("/api/logout", { method: "POST" });
}
