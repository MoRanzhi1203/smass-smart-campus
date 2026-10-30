# S14 安全文件上传

> 状态：**TESTED**（27 例：服务 19 + 页面 6 + Chromium E2E 2）
> 代码：`smass_uploads/`、`templates/s14/`、`smass/settings_s14.py`、`smass/urls_s14.py`
> 隔离库：`smass_s14_uploads`；私有目录 `private_uploads/`（已 gitignore）

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 扩展名白名单 | 按用途限制（头像 png/jpg；附件 pdf/png/jpg/docx/xlsx/zip；导入 csv/xlsx；报告 pdf/csv） | `test_exe_rejected`、`test_png_upload_ok` |
| 文件签名校验 | PNG/JPEG/PDF/ZIP(docx/xlsx) magic number；CSV 文本校验（拒二进制、UTF-8/GBK） | `test_fake_png_rejected`、`test_csv_binary_rejected`、`test_csv_text_ok` |
| 大小上限 | 单文件 ≤ 10 MB，空文件拒绝 | `test_oversize_rejected`、`test_empty_file_rejected` |
| 解压炸弹 | ZIP 条目 ≤ 200、解压 ≤ 50 MB、压缩比 ≤ 100:1 | `test_zip_bomb_rejected`、`test_valid_zip_ok` |
| 文件名清洗 | `basename` + 去控制字符/危险字符 + 截断；落盘用 UUID | `test_filename_sanitized` |
| 私有存储 | 文件在 `SMASS_PRIVATE_MEDIA_ROOT`，无公共 MEDIA URL | `test_png_upload_ok`（路径断言） |
| 归属鉴权 | 只有上传者或管理员可下载/删除 | `test_other_cannot_download`、`test_admin_can_download`、`test_other_cannot_delete` |
| 删除 | 物理删除 + 状态置 deleted；删除后不可下载 | `test_delete_removes_file` |
| 列表范围 | 学生只看自己的；管理员看全部 | `test_list_scoped_to_owner`、`test_scoping` |
| 浏览器 E2E | 上传 → 列表 → 下载内容一致；伪造 PNG 显示拒绝原因 | `test_upload_and_download` |

## 2. 设计要点

- **先校验后落盘**：任何一项校验失败都不会产生文件；
- **签名优先于扩展名**：改扩展名无法绕过；
- **私有目录 + 鉴权视图**：`FileResponse(as_attachment=True)` + `X-Content-Type-Options: nosniff`；
- **落盘名与原名分离**：原始名仅存数据库，磁盘上是 UUID，避免路径注入与覆盖；
- **ZIP 防护三层**：条目数、解压总量、压缩比。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_uploads --settings=smass.settings_s14
```

实测（2026-10-30）：**27 例 OK**（服务 19 + 页面 6 + Chromium E2E 2）。

## 4. 已知边界

1. 未接入病毒扫描引擎（`meta.virus_scan='not_available'` 如实记录），生产应接 ClamAV 等；
2. 未做图片内容解析（如像素炸弹）与 PDF 深度解析，仅签名级校验；
3. 未实现对象存储/分片上传，当前为本地私有目录；
4. 存储配额与清理策略属于 S23（容量配额），本模块只记录大小。
