## 改动说明

<!-- 一句话说明改了什么、为什么改 -->

## 改动类型

- [ ] 算法 / 评分逻辑
- [ ] 页面 / 前端
- [ ] 数据抓取 / 构建脚本
- [ ] 服务端（`server.js` / `refresh_core.js`）
- [ ] 文档
- [ ] 其他

## 自测确认

- [ ] **未提交数据文件** —— `data/`、`*.js` 数据包、`*.gz` 均不入库（`.gitignore` 已覆盖，CI 会拦截）
- [ ] 若改动了**评分 / 买点算法**：三份拷贝已同步修改（`compute_strong.py` ↔ `refresh_core.js` ↔ `strong_screener.html`），并附上 Python 与 JS 的**对拍结果**
- [ ] 若改动了**数据修正 / 刷新逻辑**：附上修复前后的数值对比与验证口径
- [ ] 若改动了 `.js`：`node --check <文件>` 通过
- [ ] 若改动了前端：改的是**根目录** `strong_screener.html`，并已通过脚本同步到 `dist_strong/`
- [ ] 若涉及发布：确认以 `language=node` 发布（**绝不能 static**）

## 相关 issue

<!-- 关联的 issue 编号，如 Closes #12 -->
