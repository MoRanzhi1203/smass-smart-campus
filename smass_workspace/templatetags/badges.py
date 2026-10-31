"""B05 状态徽章：把业务状态映射为统一的徽章类。

用法：``<span class="ws-badge {{ item.status|badge_class }}">``
未收录的状态回落为 ``is-neutral``，不改变既有语义。
"""
from __future__ import annotations

from django import template

register = template.Library()

SUCCESS = {
    'approved', 'active', 'paid', 'published', 'enrolled', 'present',
    'checked_in', 'completed', 'signed', 'open', 'resolved', 'committed',
    'registered', 'passed', 'success',
}
WARNING = {
    'pending', 'submitted', 'reviewed', 'draft', 'waitlisted', 'partial',
    'late', 'scheduled', 'running', 'reviewing', 'in_progress',
}
DANGER = {
    'rejected', 'cancelled', 'canceled', 'absent', 'overdue', 'failed',
    'void', 'withdrawn', 'left', 'banned', 'suspended', 'infeasible',
    'closed', 'expired',
}


@register.filter
def badge_class(status):
    text = str(status or '').strip().lower()
    if text in SUCCESS:
        return 'is-success'
    if text in WARNING:
        return 'is-warning'
    if text in DANGER:
        return 'is-danger'
    return 'is-neutral'
