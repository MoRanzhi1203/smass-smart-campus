"""V2.1 宿舍视图：宿管工作台与审批动作（产品配置下运行）。"""
from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .. import permissions as perms
from ..services import dormitory as dorm_svc

from .common import forbid


def _ctx(request, **extra):
    base = {'workspace_kind': perms.KIND_ADMIN,
            'is_super': perms.is_system_admin(request.user)}
    base.update(extra)
    return base


def _require_scope(request):
    buildings = dorm_svc.scope_buildings(request.user)
    if not buildings.exists():
        return None
    return buildings


@require_GET
@perms.require_kind(perms.KIND_ADMIN)
def home(request):
    if _require_scope(request) is None:
        return forbid(request, '当前账号没有宿舍管理范围')
    return render(request, 'workspace/dormitory/home.html', _ctx(
        request, **dorm_svc.manager_dashboard(request.user)))


@require_GET
@perms.require_kind(perms.KIND_ADMIN)
def rooms(request):
    buildings = _require_scope(request)
    if buildings is None:
        return forbid(request, '当前账号没有宿舍管理范围')
    building = buildings.filter(pk=request.GET.get('building') or 0).first()
    if building is None:
        building = buildings.first()
    rooms_list = dorm_svc.rooms_in(building, request.GET.get('q', ''))
    return render(request, 'workspace/dormitory/rooms.html', _ctx(
        request, buildings=buildings, building=building, rooms=rooms_list,
        keyword=request.GET.get('q', '')))


@require_POST
@perms.require_kind(perms.KIND_ADMIN)
def change_action(request, pk, action):
    from smass_dormitory import services as dorm_services
    from smass_dormitory.models import DormChangeRequest

    request_obj = DormChangeRequest.objects.filter(pk=pk).first()
    if request_obj is None:
        messages.error(request, '调宿申请不存在')
        return redirect('workspace:dormitory_home')
    building = request_obj.to_bed.room.building if request_obj.to_bed else None
    if building is None or not dorm_services.can_manage_building(
            request.user, building):
        return forbid(request, '该楼栋不在你的管理范围')
    try:
        if action == 'approve':
            dorm_services.approve_change(request_obj, request.user)
            messages.success(request, '调宿已批准并生效')
        elif action == 'reject':
            dorm_services.reject_change(
                request_obj, request.user,
                request.POST.get('reason') or '床位资源不足')
            messages.success(request, '已驳回调宿申请')
        else:
            messages.error(request, '未知操作')
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '操作失败：{}'.format(exc))
    return redirect('workspace:dormitory_home')


@require_POST
@perms.require_kind(perms.KIND_ADMIN)
def checkout_action(request, pk, action):
    from smass_dormitory import services as dorm_services
    from smass_dormitory.models import DormCheckoutRequest

    request_obj = DormCheckoutRequest.objects.filter(pk=pk).first()
    if request_obj is None:
        messages.error(request, '退宿申请不存在')
        return redirect('workspace:dormitory_home')
    assignment = dorm_services.active_assignment(request_obj.student)
    building = assignment.bed.room.building if assignment else None
    if building is None or not dorm_services.can_manage_building(
            request.user, building):
        return forbid(request, '该楼栋不在你的管理范围')
    try:
        if action == 'approve':
            dorm_services.approve_checkout(request_obj, request.user)
            messages.success(request, '退宿已批准，床位已释放')
        else:
            messages.error(request, '未知操作')
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '操作失败：{}'.format(exc))
    return redirect('workspace:dormitory_home')


@require_POST
@perms.require_kind(perms.KIND_ADMIN)
def repair_action(request, pk):
    from smass_dormitory import services as dorm_services
    from smass_dormitory.models import DormRepair

    repair = DormRepair.objects.filter(pk=pk).select_related(
        'room__building').first()
    if repair is None:
        messages.error(request, '报修单不存在')
        return redirect('workspace:dormitory_home')
    if not dorm_services.can_manage_building(request.user, repair.room.building):
        return forbid(request, '该楼栋不在你的管理范围')
    try:
        dorm_services.advance_repair(
            repair, request.user,
            assignee=request.POST.get('assignee') or '')
        messages.success(request, '报修单已推进到：{}'.format(
            repair.get_status_display()))
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '操作失败：{}'.format(exc))
    return redirect('workspace:dormitory_home')


@require_POST
@perms.require_kind(perms.KIND_ADMIN)
def inspection_action(request, pk):
    from smass_dormitory import services as dorm_services
    from smass_dormitory.models import DormInspection

    inspection = DormInspection.objects.filter(pk=pk).select_related(
        'building').first()
    if inspection is None:
        messages.error(request, '巡查记录不存在')
        return redirect('workspace:dormitory_home')
    if not dorm_services.can_manage_building(request.user,
                                             inspection.building):
        return forbid(request, '该楼栋不在你的管理范围')
    try:
        dorm_services.advance_inspection(inspection, request.user)
        messages.success(request, '巡查记录已推进')
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '操作失败：{}'.format(exc))
    return redirect('workspace:dormitory_home')
