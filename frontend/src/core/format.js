export function fmt(n, digits = 2) {
  return Number(n || 0).toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function cls(n) {
  return Number(n || 0) >= 0 ? "positive" : "negative";
}

export function percent(n, digits = 2) {
  return `${fmt(Number(n || 0), digits)}%`;
}
