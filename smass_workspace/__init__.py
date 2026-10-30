"""SMASS 产品工作台：统一认证 + 三端角色化界面。

本 app 只负责**产品化的信息架构与页面组织**：

- 学生工作台（Student Workspace）
- 教师工作台（Teacher Workspace，含辅导员扩展）
- 管理控制台（Administration Console）

业务规则与数据读写仍复用既有模块（``smass_organization`` / ``smass_academic`` /
``smass_scheduling`` / ``smass_attendance`` / ``smass_activities`` / ``smass_clubs`` /
``smass_facilities`` / ``smass_finance`` / ``smass_forum`` / ``smass_workflow`` /
``smass_analytics`` / ``smass_operations`` / ``r21_account``），不新造第二套业务库。
"""
