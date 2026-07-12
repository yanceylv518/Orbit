# Orbit Frontend

前端控制台目录，使用 Vue 3 + Vite。开发时由 Vite dev server 代理后端 API，生产构建产物由后端服务托管。

```text
frontend/
  index.html
  package.json
  vite.config.js
  src/
    main.js
    App.vue
    api/
    charts/
    components/
    core/
    domain/
    pages/
    stores/
    styles/
```

开发：

```powershell
npm install
npm run dev
```

开发服务默认运行在：

```text
http://127.0.0.1:5173/
```

Vite 会把 `/api` 和 `/reports` 代理到后端：

```text
http://127.0.0.1:8765
```

语法检查：

```powershell
npm run check
```

构建：

```powershell
npm run build
```
