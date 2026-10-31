# 页面与路由目录

> 路由由 Django URL 解析器实际展开得到（`scripts/audit_system_inventory.py`）。共 305 条，全部具名。

## 分组统计

| 前缀 | 路由数 | 说明 |
|---|---|---|
| `/r4–/r20（历史模块）` | 194 | 历史业务模块（保留） |
| `/admin` | 41 | 产品三端 |
| `/student` | 21 | 产品三端 |
| `/teacher` | 20 | 产品三端 |
| `/exchange` | 16 | 其它 |
| `/api` | 6 | 其它 |
| `/` | 1 | 统一入口与共用页面 |
| `/login` | 1 | 统一入口与共用页面 |
| `/logout` | 1 | 统一入口与共用页面 |
| `/no-role` | 1 | 统一入口与共用页面 |
| `/profile` | 1 | 统一入口与共用页面 |
| `/notifications` | 1 | 统一入口与共用页面 |
| `/hub` | 1 | 其它 |

---

## `/`

| 路径 | 名称 | 视图 |
|---|---|---|
| `/` | `root` | `smass_workspace.views.auth.root_view` |

---

## `/admin`

| 路径 | 名称 | 视图 |
|---|---|---|
| `/admin/` | `admin_home` | `smass_workspace.views.admin.home` |
| `/admin/academics/` | `admin_academics` | `smass_workspace.views.admin.academics` |
| `/admin/academics/course/` | `admin_course_create` | `smass_workspace.views.admin.course_create` |
| `/admin/academics/term/` | `admin_term_create` | `smass_workspace.views.admin.term_create` |
| `/admin/academics/year/` | `admin_year_create` | `smass_workspace.views.admin.year_create` |
| `/admin/activities/` | `admin_activities` | `smass_workspace.views.admin.activities` |
| `/admin/activities/<int:pk>/<str:action>/` | `admin_activity_action` | `smass_workspace.views.admin.activity_action` |
| `/admin/activities/create/` | `admin_activity_create` | `smass_workspace.views.admin.activity_create` |
| `/admin/approvals/` | `admin_approvals` | `smass_workspace.views.admin.approvals` |
| `/admin/approvals/leave/<int:pk>/<str:action>/` | `admin_leave_action` | `smass_workspace.views.admin.leave_action` |
| `/admin/approvals/task/<int:pk>/complete/` | `admin_task_complete` | `smass_workspace.views.admin.task_complete` |
| `/admin/audit/` | `admin_audit` | `smass_workspace.views.admin.audit` |
| `/admin/booking-approvals/` | `admin_booking_approvals` | `smass_workspace.views.admin.booking_approvals` |
| `/admin/bookings/<int:pk>/<str:action>/` | `admin_booking_action` | `smass_workspace.views.admin.booking_action` |
| `/admin/clubs/` | `admin_clubs` | `smass_workspace.views.admin.clubs` |
| `/admin/data-exchange/` | `admin_data_exchange` | `smass_workspace.views.admin.data_exchange` |
| `/admin/facilities/` | `admin_facilities` | `smass_workspace.views.admin.facilities` |
| `/admin/facilities/rooms/create/` | `admin_room_create` | `smass_workspace.views.admin.room_create` |
| `/admin/monitoring/` | `admin_monitoring` | `smass_workspace.views.admin.monitoring` |
| `/admin/notices/` | `admin_notices` | `smass_workspace.views.admin.notices` |
| `/admin/notices/<int:pk>/publish/` | `admin_announcement_publish` | `smass_workspace.views.admin.announcement_publish` |
| `/admin/notices/create/` | `admin_announcement_create` | `smass_workspace.views.admin.announcement_create` |
| `/admin/organizations/` | `admin_organizations` | `smass_workspace.views.admin.organizations` |
| `/admin/record-changes/` | `admin_record_changes` | `smass_workspace.views.admin.record_changes` |
| `/admin/record-changes/status/<int:pk>/<str:action>/` | `admin_status_change_action` | `smass_workspace.views.admin.status_change_action` |
| `/admin/record-changes/transfer/<int:pk>/<str:action>/` | `admin_transfer_action` | `smass_workspace.views.admin.transfer_action` |
| `/admin/records/` | `admin_records` | `smass_workspace.views.admin.records` |
| `/admin/records/<str:student_no>/` | `admin_record_detail` | `smass_workspace.views.admin.record_detail` |
| `/admin/records/<str:student_no>/update/` | `admin_record_update` | `smass_workspace.views.admin.record_update` |
| `/admin/roles/` | `admin_roles` | `smass_workspace.views.admin.roles` |
| `/admin/scheduling/` | `admin_scheduling` | `smass_workspace.views.admin.scheduling` |
| `/admin/sections/` | `admin_sections` | `smass_workspace.views.admin.sections` |
| `/admin/sections/<int:pk>/roster/` | `admin_section_roster` | `smass_workspace.views.admin.section_roster` |
| `/admin/sections/create/` | `admin_section_create` | `smass_workspace.views.admin.section_create` |
| `/admin/settings/` | `admin_settings` | `smass_workspace.views.admin.settings_overview` |
| `/admin/users/` | `admin_users` | `smass_workspace.views.admin.users` |
| `/admin/users/<int:pk>/reset/` | `admin_user_reset` | `smass_workspace.views.admin.user_reset` |
| `/admin/users/<int:pk>/role/` | `admin_user_role` | `smass_workspace.views.admin.user_role` |
| `/admin/users/<int:pk>/toggle/` | `admin_user_toggle` | `smass_workspace.views.admin.user_toggle` |
| `/admin/users/create/` | `admin_user_create` | `smass_workspace.views.admin.user_create` |
| `/admin/workflows/` | `admin_workflows` | `smass_workspace.views.admin.workflows` |

---

## `/api`

| 路径 | 名称 | 视图 |
|---|---|---|
| `/api/v1/openapi.json` | `api_openapi` | `smass_api.views.openapi` |
| `/api/v1/sections/` | `api_sections` | `smass_api.views.sections` |
| `/api/v1/students/` | `api_students` | `smass_api.views.students` |
| `/api/v1/sync/` | `api_sync` | `smass_api.views.sync` |
| `/api/v1/units/` | `api_units` | `smass_api.views.units` |
| `/api/v1/workflow/instances/` | `api_instances` | `smass_api.views.instances` |

---

## `/exchange`

| 路径 | 名称 | 视图 |
|---|---|---|
| `/exchange/` | `exchange_home` | `smass_data_exchange.views.exchange_home` |
| `/exchange/` | `exchange_home` | `smass_data_exchange.views.exchange_home` |
| `/exchange/commit/<str:dataset>/` | `exchange_commit` | `smass_data_exchange.views.api_commit` |
| `/exchange/commit/<str:dataset>/` | `exchange_commit` | `smass_data_exchange.views.api_commit` |
| `/exchange/errors/<str:dataset>/<int:job_id>/` | `exchange_errors` | `smass_data_exchange.views.error_download` |
| `/exchange/errors/<str:dataset>/<int:job_id>/` | `exchange_errors` | `smass_data_exchange.views.error_download` |
| `/exchange/export/<str:dataset>/` | `exchange_export` | `smass_data_exchange.views.export_view` |
| `/exchange/export/<str:dataset>/` | `exchange_export` | `smass_data_exchange.views.export_view` |
| `/exchange/history/<str:dataset>/` | `exchange_history` | `smass_data_exchange.views.job_history` |
| `/exchange/history/<str:dataset>/` | `exchange_history` | `smass_data_exchange.views.job_history` |
| `/exchange/import/<str:dataset>/` | `exchange_import` | `smass_data_exchange.views.import_page` |
| `/exchange/import/<str:dataset>/` | `exchange_import` | `smass_data_exchange.views.import_page` |
| `/exchange/preview/<str:dataset>/` | `exchange_preview` | `smass_data_exchange.views.api_preview` |
| `/exchange/preview/<str:dataset>/` | `exchange_preview` | `smass_data_exchange.views.api_preview` |
| `/exchange/template/<str:dataset>/` | `exchange_template` | `smass_data_exchange.views.template_download` |
| `/exchange/template/<str:dataset>/` | `exchange_template` | `smass_data_exchange.views.template_download` |

---

## `/hub`

| 路径 | 名称 | 视图 |
|---|---|---|
| `/hub/` | `legacy_hub` | `django.views.generic.base.View.as_view.<locals>.view` |

---

## `/login`

| 路径 | 名称 | 视图 |
|---|---|---|
| `/login/` | `login` | `smass_workspace.views.auth.login_view` |

---

## `/logout`

| 路径 | 名称 | 视图 |
|---|---|---|
| `/logout/` | `logout` | `smass_workspace.views.auth.logout_view` |

---

## `/no-role`

| 路径 | 名称 | 视图 |
|---|---|---|
| `/no-role/` | `no_role` | `smass_workspace.views.common.no_role` |

---

## `/notifications`

| 路径 | 名称 | 视图 |
|---|---|---|
| `/notifications/` | `notifications` | `smass_workspace.views.common.notifications` |

---

## `/profile`

| 路径 | 名称 | 视图 |
|---|---|---|
| `/profile/` | `profile` | `smass_workspace.views.common.profile` |

---

## `/r4–/r20（历史模块）`

| 路径 | 名称 | 视图 |
|---|---|---|
| `/r10/` | `legacy_r10` | `django.views.generic.base.View.as_view.<locals>.view` |
| `/r11/login/` | `legacy_r11_login` | `django.views.generic.base.View.as_view.<locals>.view` |
| `/r11/logout/` | `legacy_r11_logout` | `django.views.generic.base.View.as_view.<locals>.view` |
| `/r11/plan/` | `r11_plan` | `smass_scheduling.views.plan_page` |
| `/r11/plan/<int:run_id>/conflicts/` | `r11_plan_conflicts` | `smass_scheduling.views.plan_conflicts` |
| `/r11/plan/<int:run_id>/publish/` | `r11_plan_publish` | `smass_scheduling.views.plan_publish` |
| `/r11/plan/<int:run_id>/solve/` | `r11_plan_solve` | `smass_scheduling.views.plan_solve` |
| `/r11/timetable/mine.json` | `r11_my_timetable_json` | `smass_scheduling.views.my_timetable_json` |
| `/r11/timetable/room/<int:room_id>/` | `r11_room_timetable` | `smass_scheduling.views.room_timetable` |
| `/r11/timetable/student/` | `r11_student_timetable` | `smass_scheduling.views.student_timetable` |
| `/r11/timetable/teacher/` | `r11_teacher_timetable` | `smass_scheduling.views.teacher_timetable` |
| `/r12/placement/` | `placement_list` | `smass_enrollment.views.placement_list` |
| `/r12/placement/<int:pk>/` | `placement_detail` | `smass_enrollment.views.placement_detail` |
| `/r12/placement/<int:pk>/apply/` | `placement_apply` | `smass_enrollment.views.placement_apply` |
| `/r12/placement/<int:pk>/rollback/` | `placement_rollback` | `smass_enrollment.views.placement_rollback` |
| `/r12/placement/preview/<int:rule_id>/` | `placement_preview` | `smass_enrollment.views.placement_preview` |
| `/r12/status/` | `status` | `smass_enrollment.views.status_list` |
| `/r12/status/<int:pk>/<str:action>/` | `status_action` | `smass_enrollment.views.status_action` |
| `/r12/status/submit/` | `status_submit` | `smass_enrollment.views.status_submit` |
| `/r12/transfers/` | `transfers` | `smass_enrollment.views.transfer_list` |
| `/r12/transfers/<int:pk>/<str:action>/` | `transfer_action` | `smass_enrollment.views.transfer_action` |
| `/r12/transfers/submit/` | `transfer_submit` | `smass_enrollment.views.transfer_submit` |
| `/r13/leaves/` | `leaves` | `smass_attendance.views.leave_list` |
| `/r13/leaves/<int:pk>/<str:action>/` | `leave_action` | `smass_attendance.views.leave_action` |
| `/r13/leaves/submit/` | `leave_submit` | `smass_attendance.views.leave_submit` |
| `/r13/makeups/` | `makeups` | `smass_attendance.views.makeup_list` |
| `/r13/makeups/<int:pk>/<str:action>/` | `makeup_action` | `smass_attendance.views.makeup_action` |
| `/r13/makeups/submit/` | `makeup_submit` | `smass_attendance.views.makeup_submit` |
| `/r13/sessions/` | `sessions` | `smass_attendance.views.session_list` |
| `/r13/sessions/<int:pk>/` | `session_detail` | `smass_attendance.views.session_detail` |
| `/r13/sessions/<int:pk>/close/` | `session_close` | `smass_attendance.views.session_close` |
| `/r13/sessions/<int:pk>/mark/` | `session_mark` | `smass_attendance.views.session_mark` |
| `/r13/sessions/<int:pk>/sign/` | `session_sign` | `smass_attendance.views.session_sign` |
| `/r13/sessions/create/` | `session_create` | `smass_attendance.views.session_create` |
| `/r13/stats/` | `stats` | `smass_attendance.views.stats_view` |
| `/r14/activities/` | `activities` | `smass_activities.views.activity_list` |
| `/r14/activities/<int:pk>/` | `activity_detail` | `smass_activities.views.activity_detail` |
| `/r14/activities/<int:pk>/close/` | `activity_close` | `smass_activities.views.activity_close` |
| `/r14/activities/<int:pk>/generate-credits/` | `activity_generate_credits` | `smass_activities.views.activity_generate_credits` |
| `/r14/activities/<int:pk>/publish/` | `activity_publish` | `smass_activities.views.activity_publish` |
| `/r14/activities/<int:pk>/register/` | `activity_register` | `smass_activities.views.activity_register` |
| `/r14/activities/create/` | `activity_create` | `smass_activities.views.activity_create` |
| `/r14/credits/` | `credits` | `smass_activities.views.credit_list` |
| `/r14/credits/<int:pk>/<str:action>/` | `credit_action` | `smass_activities.views.credit_action` |
| `/r14/registrations/<int:pk>/cancel/` | `registration_cancel` | `smass_activities.views.registration_cancel` |
| `/r14/registrations/<int:pk>/checkin/` | `activity_check_in` | `smass_activities.views.activity_check_in` |
| `/r15/clubs/` | `clubs` | `smass_clubs.views.club_list` |
| `/r15/clubs/<int:pk>/` | `club_detail` | `smass_clubs.views.club_detail` |
| `/r15/clubs/<int:pk>/apply/` | `club_apply` | `smass_clubs.views.club_apply` |
| `/r15/clubs/<int:pk>/appoint/` | `post_appoint` | `smass_clubs.views.post_appoint` |
| `/r15/clubs/create/` | `club_create` | `smass_clubs.views.club_create` |
| `/r15/memberships/<int:pk>/<str:action>/` | `membership_action` | `smass_clubs.views.membership_action` |
| `/r15/posts/` | `posts` | `smass_clubs.views.post_list` |
| `/r15/posts/<int:pk>/end/` | `post_end` | `smass_clubs.views.post_end` |
| `/r16/approvals/` | `approvals` | `smass_facilities.views.approvals` |
| `/r16/approvals/<int:pk>/approve/` | `approve` | `smass_facilities.views.approve` |
| `/r16/approvals/<int:pk>/reject/` | `reject` | `smass_facilities.views.reject` |
| `/r16/bookings/` | `bookings` | `smass_facilities.views.my_bookings` |
| `/r16/bookings/<int:pk>/cancel/` | `cancel_booking` | `smass_facilities.views.cancel_booking` |
| `/r16/bookings/<int:pk>/checkin/` | `check_in` | `smass_facilities.views.check_in` |
| `/r16/bookings/<int:pk>/release/` | `release` | `smass_facilities.views.release` |
| `/r16/calendar/` | `calendar` | `smass_facilities.views.shared_calendar` |
| `/r16/rooms/` | `rooms` | `smass_facilities.views.room_list` |
| `/r16/rooms/<int:pk>/` | `room_detail` | `smass_facilities.views.room_detail` |
| `/r16/rooms/<int:pk>/book/` | `create_booking` | `smass_facilities.views.create_booking` |
| `/r17/announcements/` | `announcements` | `smass_forum.views.announcement_list` |
| `/r17/announcements/<int:pk>/publish/` | `announcement_publish` | `smass_forum.views.announcement_publish` |
| `/r17/announcements/create/` | `announcement_create` | `smass_forum.views.announcement_create` |
| `/r17/forum/` | `forum` | `smass_forum.views.forum_index` |
| `/r17/forum/board/<int:pk>/` | `board` | `smass_forum.views.board_detail` |
| `/r17/forum/board/<int:pk>/post/` | `post_create` | `smass_forum.views.post_create` |
| `/r17/forum/post/<int:pk>/` | `post` | `smass_forum.views.post_detail` |
| `/r17/forum/post/<int:pk>/action/` | `content_action` | `smass_forum.views.content_action` |
| `/r17/forum/post/<int:pk>/comment/` | `comment_create` | `smass_forum.views.comment_create` |
| `/r17/forum/report/` | `content_report` | `smass_forum.views.content_report` |
| `/r17/reports/` | `reports` | `smass_forum.views.report_list` |
| `/r17/reports/<int:pk>/resolve/` | `report_resolve` | `smass_forum.views.report_resolve` |
| `/r18/bills/` | `bills` | `smass_finance.views.bill_list` |
| `/r18/bills/<int:pk>/` | `bill_detail` | `smass_finance.views.bill_detail` |
| `/r18/bills/<int:pk>/pay/` | `bill_pay` | `smass_finance.views.bill_pay` |
| `/r18/bills/<int:pk>/refund/` | `refund_request` | `smass_finance.views.refund_request` |
| `/r18/bills/create/` | `bill_create` | `smass_finance.views.bill_create` |
| `/r18/fee-items/create/` | `fee_item_create` | `smass_finance.views.fee_item_create` |
| `/r18/ledger/` | `ledger` | `smass_finance.views.ledger_list` |
| `/r18/refunds/` | `refunds` | `smass_finance.views.refund_list` |
| `/r18/refunds/<int:pk>/<str:action>/` | `refund_action` | `smass_finance.views.refund_action` |
| `/r19/access/` | `access` | `smass_party.views.access_list` |
| `/r19/access/<int:pk>/<str:action>/` | `access_action` | `smass_party.views.access_action` |
| `/r19/activities/<int:pk>/complete/` | `activity_complete` | `smass_party.views.activity_complete` |
| `/r19/audit/` | `audit` | `smass_party.views.audit_list` |
| `/r19/documents/<int:pk>/` | `document_detail` | `smass_party.views.document_detail` |
| `/r19/documents/<int:pk>/request/` | `document_request` | `smass_party.views.document_request` |
| `/r19/orgs/` | `orgs` | `smass_party.views.org_list` |
| `/r19/orgs/<int:pk>/` | `org_detail` | `smass_party.views.org_detail` |
| `/r19/orgs/<int:pk>/activities/add/` | `activity_create` | `smass_party.views.activity_create` |
| `/r19/orgs/<int:pk>/documents/add/` | `document_create` | `smass_party.views.document_create` |
| `/r19/orgs/<int:pk>/members/add/` | `member_add` | `smass_party.views.member_add` |
| `/r19/orgs/create/` | `org_create` | `smass_party.views.org_create` |
| `/r20/` | `home` | `smass_portal.views.portal_home` |
| `/r20/admin/` | `admin` | `smass_portal.views.portal_admin` |
| `/r20/admin/bootstrap/` | `admin_bootstrap` | `smass_portal.views.admin_bootstrap` |
| `/r20/admin/link/` | `link_create` | `smass_portal.views.link_create` |
| `/r20/admin/notice/` | `notice_create` | `smass_portal.views.notice_create` |
| `/r20/admin/notice/<int:pk>/publish/` | `notice_publish` | `smass_portal.views.notice_publish` |
| `/r20/admin/section/` | `section_create` | `smass_portal.views.section_create` |
| `/r21/change-password/` | `r21_change_password` | `r21_account.views.change_password_view` |
| `/r21/home/` | `legacy_home` | `django.views.generic.base.View.as_view.<locals>.view` |
| `/r21/login/` | `legacy_login` | `django.views.generic.base.View.as_view.<locals>.view` |
| `/r21/logout/` | `legacy_logout` | `django.views.generic.base.View.as_view.<locals>.view` |
| `/r4/health/` | `r4_health` | `smass_organization.views.health` |
| `/r4/import/` | `r4_import_page` | `smass_operations.ui_views.import_page` |
| `/r4/import/commit/` | `r4_import_commit_ui` | `smass_organization.ui_views.import_commit_page` |
| `/r4/import/commit/` | `r4_import_commit` | `smass_organization.views.import_commit_view` |
| `/r4/import/preview/` | `r4_import_preview_ui` | `smass_operations.ui_views.import_preview` |
| `/r4/import/preview/` | `r4_import_preview` | `smass_organization.views.import_preview_view` |
| `/r4/login/` | `r4_login` | `r21_account.views.login_view` |
| `/r4/logout/` | `r4_logout` | `r21_account.views.logout_view` |
| `/r4/students/` | `r4_student_list` | `smass_organization.views.student_list` |
| `/r4/students/<str:student_no>/` | `r4_student_detail_page` | `smass_organization.ui_views.student_detail_page` |
| `/r4/students/<str:student_no>/` | `r4_student_detail` | `smass_organization.views.student_detail` |
| `/r4/students/<str:student_no>/edit/` | `r4_student_edit` | `smass_organization.ui_views.student_edit` |
| `/r4/students/export/` | `r4_student_export_r10` | `smass_organization.views.student_export` |
| `/r4/students/export/` | `r4_student_export` | `smass_organization.views.student_export` |
| `/r4/units/` | `r4_unit_list` | `smass_organization.views.unit_list` |
| `/r4/units/<int:pk>/edit/` | `r4_unit_edit` | `smass_organization.ui_views.unit_edit` |
| `/r4/units/<int:pk>/move/` | `r4_unit_move` | `smass_organization.views.unit_move` |
| `/r4/units/create/` | `r4_unit_create` | `smass_organization.views.unit_create` |
| `/r4/units/new/` | `r4_unit_new` | `smass_organization.ui_views.unit_new` |
| `/r4/units/tree/` | `r4_unit_tree` | `smass_organization.views.unit_tree` |
| `/r5/assignments/<int:pk>/revoke/` | `r5_assignment_revoke` | `smass_academic.ui_views.assignment_revoke` |
| `/r5/courses/` | `r5_course_list` | `smass_academic.views.course_list` |
| `/r5/courses/create/` | `r5_course_create` | `smass_academic.views.course_create` |
| `/r5/courses/new/` | `r5_course_new` | `smass_academic.ui_views.course_new` |
| `/r5/enroll/` | `r5_enroll_page` | `smass_academic.ui_views.enroll_page` |
| `/r5/enroll/<int:pk>/` | `r5_enroll_action` | `smass_academic.ui_views.enroll_action` |
| `/r5/enrollments/<int:pk>/drop/` | `r5_drop_action` | `smass_academic.ui_views.drop_action` |
| `/r5/health/` | `r5_health` | `smass_academic.views.health` |
| `/r5/login/` | `r5_login` | `r21_account.views.login_view` |
| `/r5/logout/` | `r5_logout` | `r21_account.views.logout_view` |
| `/r5/my-courses/` | `r5_my_sections` | `smass_academic.views.my_sections` |
| `/r5/sections/` | `r5_section_list` | `smass_academic.views.section_list` |
| `/r5/sections/<int:pk>/assign/` | `r5_section_assign` | `smass_academic.ui_views.section_assign` |
| `/r5/sections/<int:pk>/roster/` | `r5_roster_page` | `smass_academic.ui_views.section_roster_page` |
| `/r5/sections/<int:pk>/roster/` | `r5_section_roster` | `smass_academic.views.section_roster` |
| `/r5/sections/<int:pk>/roster/<int:enrollment_id>/drop/` | `r5_roster_drop` | `smass_academic.ui_views.roster_drop` |
| `/r5/sections/create/` | `r5_section_create` | `smass_academic.views.section_create` |
| `/r5/sections/new/` | `r5_section_new` | `smass_academic.ui_views.section_new` |
| `/r5/terms/` | `r5_term_list` | `smass_academic.views.term_list` |
| `/r5/terms/create/` | `r5_term_create` | `smass_academic.views.term_create` |
| `/r5/terms/new/` | `r5_term_new` | `smass_academic.ui_views.term_new` |
| `/r5/workspace/` | `r5_teacher_workspace` | `smass_academic.views.teacher_workspace` |
| `/r5/years/` | `r5_year_list` | `smass_academic.views.year_list` |
| `/r5/years/<int:pk>/activate/` | `r5_year_activate` | `smass_academic.views.year_activate` |
| `/r5/years/create/` | `r5_year_create` | `smass_academic.views.year_create` |
| `/r5/years/new/` | `r5_year_new` | `smass_academic.ui_views.year_new` |
| `/r6/definitions/` | `r6_definition_list` | `smass_workflow.views.definition_list` |
| `/r6/definitions/<int:pk>/` | `r6_definition_detail` | `smass_workflow.ui_views.definition_detail` |
| `/r6/definitions/<int:pk>/publish/` | `r6_definition_publish` | `smass_workflow.ui_views.definition_publish` |
| `/r6/definitions/create/` | `r6_definition_create` | `smass_workflow.views.definition_create` |
| `/r6/definitions/new/` | `r6_definition_new` | `smass_workflow.ui_views.definition_new` |
| `/r6/health/` | `r6_health` | `smass_workflow.views.health` |
| `/r6/instances/` | `r6_instance_list` | `smass_workflow.views.instance_list` |
| `/r6/instances/<int:pk>/` | `r6_instance_detail` | `smass_workflow.ui_views.instance_detail` |
| `/r6/instances/<int:pk>/action/` | `r6_instance_action` | `smass_workflow.ui_views.instance_action` |
| `/r6/instances/<int:pk>/action/` | `r6_instance_action` | `smass_workflow.views.instance_action` |
| `/r6/instances/create/` | `r6_instance_create` | `smass_workflow.views.instance_create` |
| `/r6/instances/new/` | `r6_instance_new` | `smass_workflow.ui_views.instance_new` |
| `/r6/login/` | `r6_login` | `r21_account.views.login_view` |
| `/r6/logout/` | `r6_logout` | `r21_account.views.logout_view` |
| `/r6/notifications/` | `r6_notification_page` | `smass_workflow.ui_views.notification_page` |
| `/r6/notifications/` | `r6_notification_list` | `smass_workflow.views.notification_list` |
| `/r6/notifications/<int:pk>/read/` | `r6_notification_read` | `smass_workflow.ui_views.notification_read` |
| `/r6/tasks/` | `r6_task_list_page` | `smass_workflow.ui_views.task_list_page` |
| `/r6/tasks/` | `r6_task_list` | `smass_workflow.views.task_list` |
| `/r6/tasks/<int:pk>/complete/` | `r6_task_complete` | `smass_workflow.ui_views.task_complete` |
| `/r7/dashboard/` | `r7_dashboard_page` | `smass_analytics.ui_views.dashboard_page` |
| `/r7/dashboard/` | `r7_dashboard` | `smass_analytics.views.dashboard` |
| `/r7/health/` | `r7_health` | `smass_analytics.views.health` |
| `/r7/login/` | `r7_login` | `r21_account.views.login_view` |
| `/r7/logout/` | `r7_logout` | `r21_account.views.logout_view` |
| `/r7/metric-series/` | `r7_metric_series` | `smass_analytics.ui_views.metric_series` |
| `/r7/metrics/` | `r7_metric_list_page` | `smass_analytics.ui_views.metric_list_page` |
| `/r7/metrics/` | `r7_metric_list` | `smass_analytics.views.metric_list` |
| `/r7/reports/<str:code>/` | `r7_report_detail_page` | `smass_analytics.ui_views.report_detail_page` |
| `/r7/reports/<str:code>/export/` | `r7_report_export_page` | `smass_analytics.ui_views.report_export_page` |
| `/r7/reports/<str:code>/export/` | `r7_report_export` | `smass_analytics.views.report_export` |
| `/r7/reports/<str:code>/run/` | `r7_report_run` | `smass_analytics.views.report_run` |
| `/r8/docs/` | `r8_api_docs` | `smass_operations.ui_views.api_docs` |
| `/r8/login/` | `r8_login` | `r21_account.views.login_view` |
| `/r9/alerts/` | `r9_alerts` | `smass_operations.views.alerts` |
| `/r9/health/` | `r9_health` | `smass_operations.views.health` |
| `/r9/metrics/` | `r9_metrics` | `smass_operations.views.metrics` |
| `/r9/ready/` | `r9_ready` | `smass_operations.views.ready` |
| `/r9/status/` | `r9_ops_status` | `smass_operations.ui_views.ops_status` |

---

## `/student`

| 路径 | 名称 | 视图 |
|---|---|---|
| `/student/` | `student_home` | `smass_workspace.views.student.home` |
| `/student/activities/` | `student_activities` | `smass_workspace.views.student.activities` |
| `/student/activities/<int:pk>/register/` | `student_activity_register` | `smass_workspace.views.student.activity_register` |
| `/student/activities/registrations/<int:pk>/cancel/` | `student_activity_cancel` | `smass_workspace.views.student.activity_cancel` |
| `/student/attendance/` | `student_attendance` | `smass_workspace.views.student.attendance` |
| `/student/attendance/leave/` | `student_leave_submit` | `smass_workspace.views.student.leave_submit` |
| `/student/attendance/leave/<int:pk>/cancel/` | `student_leave_cancel` | `smass_workspace.views.student.leave_cancel` |
| `/student/bookings/` | `student_bookings` | `smass_workspace.views.student.bookings` |
| `/student/bookings/<int:pk>/cancel/` | `student_booking_cancel` | `smass_workspace.views.student.booking_cancel` |
| `/student/bookings/create/` | `student_booking_create` | `smass_workspace.views.student.booking_create` |
| `/student/clubs/` | `student_clubs` | `smass_workspace.views.student.clubs` |
| `/student/clubs/<int:pk>/apply/` | `student_club_apply` | `smass_workspace.views.student.club_apply` |
| `/student/courses/` | `student_courses` | `smass_workspace.views.student.courses` |
| `/student/dormitory/` | `student_dormitory` | `smass_workspace.views.student.dormitory` |
| `/student/fees/` | `student_fees` | `smass_workspace.views.student.fees` |
| `/student/fees/<int:pk>/pay/` | `student_fee_pay` | `smass_workspace.views.student.fee_pay` |
| `/student/notices/` | `student_notices` | `smass_workspace.views.student.notices` |
| `/student/organizations/` | `student_organizations` | `smass_workspace.views.student.organizations` |
| `/student/record/` | `student_record` | `smass_workspace.views.student.record` |
| `/student/timetable/` | `student_timetable` | `smass_workspace.views.student.timetable` |
| `/student/volunteer/` | `student_volunteer` | `smass_workspace.views.student.volunteer` |

---

## `/teacher`

| 路径 | 名称 | 视图 |
|---|---|---|
| `/teacher/` | `teacher_home` | `smass_workspace.views.teacher.home` |
| `/teacher/approvals/` | `teacher_approvals` | `smass_workspace.views.teacher.approvals` |
| `/teacher/approvals/booking/<int:pk>/<str:action>/` | `teacher_booking_action` | `smass_workspace.views.teacher.booking_action` |
| `/teacher/approvals/leave/<int:pk>/<str:action>/` | `teacher_leave_action` | `smass_workspace.views.teacher.leave_action` |
| `/teacher/approvals/makeup/<int:pk>/<str:action>/` | `teacher_makeup_action` | `smass_workspace.views.teacher.makeup_action` |
| `/teacher/approvals/task/<int:pk>/complete/` | `teacher_task_complete` | `smass_workspace.views.teacher.task_complete` |
| `/teacher/attendance/` | `teacher_attendance` | `smass_workspace.views.teacher.attendance` |
| `/teacher/attendance/<int:pk>/` | `teacher_attendance_detail` | `smass_workspace.views.teacher.attendance_detail` |
| `/teacher/attendance/<int:pk>/close/` | `teacher_attendance_close` | `smass_workspace.views.teacher.attendance_close` |
| `/teacher/attendance/<int:pk>/mark/` | `teacher_attendance_mark` | `smass_workspace.views.teacher.attendance_mark` |
| `/teacher/attendance/create/` | `teacher_attendance_create` | `smass_workspace.views.teacher.attendance_create` |
| `/teacher/classes/` | `teacher_classes` | `smass_workspace.views.teacher.classes` |
| `/teacher/counselor/leaves/` | `teacher_leave_review` | `smass_workspace.views.teacher.leave_review` |
| `/teacher/counselor/students/` | `teacher_counselor_students` | `smass_workspace.views.teacher.counselor_students` |
| `/teacher/courses/` | `teacher_courses` | `smass_workspace.views.teacher.courses` |
| `/teacher/notices/` | `teacher_notices` | `smass_workspace.views.teacher.notices` |
| `/teacher/sections/` | `teacher_sections` | `smass_workspace.views.teacher.sections` |
| `/teacher/students/` | `teacher_students` | `smass_workspace.views.teacher.students` |
| `/teacher/students/<int:pk>/` | `teacher_student_detail` | `smass_workspace.views.teacher.student_detail` |
| `/teacher/timetable/` | `teacher_timetable` | `smass_workspace.views.teacher.timetable` |

---

## 产品三端页面说明

产品页面共 50 个（学生 15 / 教师 13 / 管理 22），全部由 `templates/workspace/base.html` 与 `static/workspace/app.css` 渲染。

### 学生工作台（15 页）

| 一级菜单 | 页面 | URL | 命名路由 | view | 用途 | 主要操作 | 权限 |
|---|---|---|---|---|---|---|---|
| 学习 | 学习工作台 | `/student/` | `workspace:student_home` | `student.home` | 学期、今日课表、考勤率、待缴费用、待办、公告 | 查看；跳转各子页 | 学生本人 |
| 学习 | 我的课表 | `/student/timetable/` | `workspace:student_timetable` | `student.timetable` | 按已发布排课运行渲染周课表 | 查看 | 学生本人 |
| 学习 | 我的课程 | `/student/courses/` | `workspace:student_courses` | `student.courses` | 选课、教学班、任课教师、学分 | 查看 | 学生本人 |
| 学习 | 学籍信息 | `/student/record/` | `workspace:student_record` | `student.record` | 学籍、组织链、变更历史、住宿摘要 | 查看 | 学生本人 |
| 日常 | 考勤与请假 | `/student/attendance/` | `workspace:student_attendance` | `student.attendance` | 考勤统计、最近记录、请假申请与撤销 | 提交请假、撤销本人待批请假 | 学生本人 |
| 日常 | 费用与账单 | `/student/fees/` | `workspace:student_fees` | `student.fees` | 账单、应缴/已缴/待缴、缴费登记 | 自助缴费（台账登记） | 学生本人 |
| 日常 | 场地预约 | `/student/bookings/` | `workspace:student_bookings` | `student.bookings` | 我的预约、场地列表、预约申请 | 申请、取消 | 学生本人 |
| 日常 | 我的寝室 | `/student/dormitory/` | `workspace:student_dormitory` | `student.dormitory` | 楼栋/寝室/床位/室友 | 查看 | 学生本人 |
| 校园 | 活动与志愿 | `/student/activities/` | `workspace:student_activities` | `student.activities` | 可报名活动、我的报名、志愿摘要 | 报名、取消报名 | 学生本人 |
| 校园 | 志愿服务 | `/student/volunteer/` | `workspace:student_volunteer` | `student.volunteer` | 已认定志愿时长与学分 | 查看 | 学生本人 |
| 校园 | 社团 | `/student/clubs/` | `workspace:student_clubs` | `student.clubs` | 社团名录、我的社团与任职 | 申请加入 | 学生本人 |
| 校园 | 学生组织 | `/student/organizations/` | `workspace:student_organizations` | `student.organizations` | 组织名录、我的组织归属、班级 | 查看 | 学生本人 |
| 消息 | 通知公告 | `/student/notices/` | `workspace:student_notices` | `student.notices` | 面向学生的已发布公告 | 查看 | 学生本人 |
| 消息 | 通知中心（共用） | `/notifications/` | `workspace:notifications` | `common.notifications` | 站内通知 + 公告合并，打开即标记已读 | 查看 | 登录用户 |
| 账号 | 个人中心（共用） | `/profile/` | `workspace:profile` | `common.profile` | 账号、角色、组织关系、可用工作台 | 查看；进入改密 | 登录用户 |

### 教师工作台（13 页）

| 一级菜单 | 页面 | URL | 命名路由 | view | 用途 | 主要操作 | 权限 |
|---|---|---|---|---|---|---|---|
| 教学 | 教学工作台 | `/teacher/` | `workspace:teacher_home` | `teacher.home` | 教学班、学生数、今日课程、待批、通知 | 查看；快捷入口 | 教师 |
| 教学 | 我的课程 | `/teacher/courses/` | `workspace:teacher_courses` | `teacher.courses` | 本人教学班与选课人数 | 查看 | 教师本人 |
| 教学 | 教学班 | `/teacher/sections/` | `workspace:teacher_sections` | `teacher.sections` | 教学班与学生名单 | 查看 | 教师本人教学班 |
| 教学 | 我的课表 | `/teacher/timetable/` | `workspace:teacher_timetable` | `teacher.timetable` | 教师视角周课表 | 查看 | 教师本人 |
| 学生事务 | 考勤管理 | `/teacher/attendance/` | `workspace:teacher_attendance` | `teacher.attendance` | 考勤场次列表与发起 | 发起考勤 | 教师本人教学班班级 |
| 学生事务 | 考勤登记 | `/teacher/attendance/<pk>/` | `workspace:teacher_attendance_detail` | `teacher.attendance_detail` | 逐人登记出勤/迟到/缺勤/请假、结束场次 | 登记、结束 | 场次归属校验 |
| 学生事务 | 学生事务 | `/teacher/students/` | `workspace:teacher_students` | `teacher.students` | 本人教学班学生 | 查看 | 教学班范围 |
| 学生事务 | 学生档案 | `/teacher/students/<pk>/` | `workspace:teacher_student_detail` | `teacher.student_detail` | 学生选课/考勤/请假 | 查看 | 对象级校验 |
| 学生事务 | 审批中心 | `/teacher/approvals/` | `workspace:teacher_approvals` | `teacher.approvals` | 请假、补签、流程待办、场地预约 | 批准/驳回/完成 | 范围内学生与本人待办 |
| 辅导员 | 负责班级 | `/teacher/classes/` | `workspace:teacher_classes` | `teacher.classes` | 负责班级与学生 | 查看 | 仅辅导员 |
| 辅导员 | 负责学生 | `/teacher/counselor/students/` | `workspace:teacher_counselor_students` | `teacher.counselor_students` | 负责范围内学生 | 查看 | 仅辅导员 |
| 辅导员 | 请假审批 | `/teacher/counselor/leaves/` | `workspace:teacher_leave_review` | `teacher.leave_review` | 负责学生请假审批 | 批准/驳回 | 仅辅导员 |
| 消息 | 通知与公告 | `/teacher/notices/` | `workspace:teacher_notices` | `teacher.notices` | 面向教师的公告 | 查看 | 教师 |

### 管理控制台（22 页）

| 一级菜单 | 页面 | URL | 命名路由 | view | 用途 | 主要操作 | 权限 |
|---|---|---|---|---|---|---|---|
| 总览 | 控制台总览 | `/admin/` | `workspace:admin_home` | `admin.home` | 账号/学籍/教学/排课/活动/费用/监控汇总 | 查看；快捷入口 | 管理员 |
| 身份与组织 | 用户账号 | `/admin/users/` | `workspace:admin_users` | `admin.users` | 账号列表、筛选、角色、启停、重置口令、创建 | 创建/授角色/停用/重置 | 超管写；学院管理员只读 |
| 身份与组织 | 角色与权限 | `/admin/roles/` | `workspace:admin_roles` | `admin.roles` | 四个角色与账号数、能力说明 | 查看 | 管理员 |
| 身份与组织 | 组织架构 | `/admin/organizations/` | `workspace:admin_organizations` | `admin.organizations` | 组织单元树与人员归属 | 查看 | 管理员（范围） |
| 学籍与教学 | 学籍管理 | `/admin/records/` | `workspace:admin_records` | `admin.records` | 学籍列表与筛选 | 查看 | 管理员（范围） |
| 学籍与教学 | 学籍档案 | `/admin/records/<no>/` | `workspace:admin_record_detail` | `admin.record_detail` | 学籍详情、选课、编辑表单 | 超管编辑姓名/状态/班级 | 学院管理员只读 |
| 学籍与教学 | 学籍异动 | `/admin/record-changes/` | `workspace:admin_record_changes` | `admin.record_changes` | 转专业与学籍状态变更 | 批准/驳回 | 范围内学生 |
| 学籍与教学 | 学年学期与课程 | `/admin/academics/` | `workspace:admin_academics` | `admin.academics` | 学年/学期/课程列表 + 新建表单 | 超管新建 | 超管写；学院管理员只读 |
| 学籍与教学 | 教学班与选课 | `/admin/sections/` | `workspace:admin_sections` | `admin.sections` | 教学班列表 + 新建 | 超管新建教学班 | 超管写 |
| 学籍与教学 | 教学班名单 | `/admin/sections/<pk>/roster/` | `workspace:admin_section_roster` | `admin.section_roster` | 选课名单与任课教师 | 查看 | 管理员 |
| 排课与资源 | 排课与课表 | `/admin/scheduling/` | `workspace:admin_scheduling` | `admin.scheduling` | 排课运行、冲突、发布状态 | 查看；进入排课求解（专业工具） | 管理员 |
| 排课与资源 | 教室与场地 | `/admin/facilities/` | `workspace:admin_facilities` | `admin.facilities` | 场地台账 + 新增场地 | 超管新增场地 | 超管写 |
| 排课与资源 | 预约审批 | `/admin/booking-approvals/` | `workspace:admin_booking_approvals` | `admin.booking_approvals` | 待批场地预约 | 批准/驳回 | 管理员 |
| 审批与工作流 | 待办与审批 | `/admin/approvals/` | `workspace:admin_approvals` | `admin.approvals` | 待批请假/流程/场地 + 请假状态 | 批准/驳回/完成 | 范围内 |
| 审批与工作流 | 流程定义 | `/admin/workflows/` | `workspace:admin_workflows` | `admin.workflows` | 流程定义与实例 | 查看；进入流程编辑（专业工具） | 管理员 |
| 校园业务 | 活动管理 | `/admin/activities/` | `workspace:admin_activities` | `admin.activities` | 活动列表 + 创建 | 超管创建/发布/结束/生成学分 | 超管写 |
| 校园业务 | 社团与学生组织 | `/admin/clubs/` | `workspace:admin_clubs` | `admin.clubs` | 社团与部门组织 | 查看 | 管理员 |
| 校园业务 | 通知公告 | `/admin/notices/` | `workspace:admin_notices` | `admin.notices` | 公告列表 + 发布 | 超管创建/发布 | 超管写 |
| 数据治理 | 数据导入导出 | `/admin/data-exchange/` | `workspace:admin_data_exchange` | `admin.data_exchange` | 可用数据集清单 | 查看；进入导入向导（专业工具） | 管理员 |
| 运维与安全 | 运行监控 | `/admin/monitoring/` | `workspace:admin_monitoring` | `admin.monitoring` | 请求指标、慢请求、探针、告警 | 查看 | 管理员 |
| 运维与安全 | 安全审计 | `/admin/audit/` | `workspace:admin_audit` | `admin.audit` | 账号操作日志、登录尝试 | 查看 | 管理员 |
| 运维与安全 | 系统配置 | `/admin/settings/` | `workspace:admin_settings` | `admin.settings` | 动作权限、角色账号数、字段策略、密码策略 | 查看 | 仅超管 |
