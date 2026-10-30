# S19 可访问性（WCAG 2.1 AA 基线）

> 状态：**TESTED**（19 例：规则/对比度/扫描/页面 17 + Chromium E2E 2；另完成 375 例模板回归）
> 代码：`smass_a11y/`、`templates/s19/`、`smass/settings_s19.py`、`smass/urls_s19.py`
> 报告页：`/s19/`（管理员）

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 语言声明 | `<html>` 必须有 `lang`；子模板（extends）不误报 | `test_missing_lang`、`test_lang_ok`、`test_partial_template_skips_lang` |
| 图片替代文本 | `<img>` 必须带 `alt` | `test_image_without_alt` |
| 控件可访问名称 | `label[for]` / 包裹 / `aria-label(by)` 三选一 | `test_input_without_label`、`test_input_with_aria_label`、`test_input_with_for_label` |
| 链接名称 | `<a>` 必须有可见文本或 `aria-label` | `test_empty_link` |
| Tab 顺序 | 禁止正整数 `tabindex` | `test_positive_tabindex` |
| 表格表头 | `<table>` 需 `<th>` | 规则内置（warning） |
| 焦点可见 | 清除 `outline` 必须提供 `:focus` 替代 | 浏览器焦点轮廓断言 |
| 对比度 | WCAG 相对亮度 + 对比率，AA/AAA 判定 | `test_black_on_white`、`test_wcag_levels`、`test_design_system_pairs_pass_aa` |
| 真实模板零 error | 新模板（R12–R20、S09–S16、S19）扫描 0 error | `test_new_templates_have_no_error` |
| 键盘可达 | 首个 Tab 落在"跳到主要内容"，Enter 跳转 | `test_skip_link_focus_and_zoom` |
| 窄屏/缩放 | 320px 视口无横向溢出 | 同上 |
| 报告页权限 | 未登录 302、学生 403、管理员 200 | `test_requires_login`、`test_student_forbidden`、`test_admin_report` |

## 2. 本轮真实修复

1. **20 个新模板的可访问名称缺失**：批量给无 `id`/无 `label` 的 `input/select/textarea`
   加 `aria-label`（优先取 `placeholder` 文本；否则取 `name`），涉及
   `r12/r13/r14/r15/r16/r17/r18/r19/s09/s10/s13`；
2. **扫描器误报**：子模板 `{% extends %}` 不含 `<html>` 时不再误报 `html-lang`；
3. **文本收集缺陷**：原实现把父标签名混入链接文本，改为栈式逐节点收集并冒泡子文本；
4. **窄屏横向溢出**：报告页表格改 `table-layout: fixed` + `overflow-wrap: anywhere`，
   320px 视口溢出从 130px 降到 0。

## 3. 回归证据

模板改动后回归 11 个模块（`.local/evidence/s19_template_regression.log`）：

| 模块 | 例数 | 结果 |
|---|---|---|
| smass_enrollment | 43 | OK |
| smass_attendance | 41 | OK |
| smass_activities | 28 | OK |
| smass_clubs | 28 | OK |
| smass_facilities | 59 | OK |
| smass_forum | 32 | OK |
| smass_finance | 34 | OK |
| smass_party | 35 | OK |
| smass_mfa | 24 | OK |
| smass_stepup | 26 | OK |
| smass_privacy | 25 | OK |
| **合计** | **375** | **全部 OK** |

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_a11y --settings=smass.settings_s19 --noinput
```

实测（2026-10-30）：**19 例 OK**。

## 4. 已知边界

1. 历史模板（TRAE 前）仍有 67 个 error，作为既有基线登记、未在本轮清理（避免大范围改旧页面引入回归）；
2. 未引入 axe-core（需联网 npm 依赖），当前为自研规则 + 浏览器焦点/溢出实测；
3. 对比度只覆盖设计系统的 6 组关键配色，未做全站逐元素取样；
4. 屏幕阅读器实测（NVDA/JAWS）未做，仅静态语义 + 键盘路径验证。
