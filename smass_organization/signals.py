"""A04 双份字段一致性：学籍档案变更时同步学生档案（StudentProfile）。

只同步“姓名/学号”这类两边都存在的身份字段；学号长度超过档案列宽
（``max_length=10``）时跳过，避免截断产生新的不一致。
"""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import StudentRecord

PROFILE_STUDENT_NO_MAX = 10
PROFILE_NAME_MAX = 16


@receiver(post_save, sender=StudentRecord)
def sync_student_profile(sender, instance, **kwargs):
    if not instance.account_id:
        return
    profile = getattr(instance.account, 'student_profile', None)
    if profile is None:
        return

    updates = []
    name = (instance.name or '').strip()
    if name and name != profile.name and len(name) <= PROFILE_NAME_MAX:
        profile.name = name
        updates.append('name')

    student_no = (instance.student_no or '').strip()
    if (student_no and student_no != profile.student_no
            and len(student_no) <= PROFILE_STUDENT_NO_MAX):
        profile.student_no = student_no
        updates.append('student_no')

    if updates:
        profile.save(update_fields=updates)
