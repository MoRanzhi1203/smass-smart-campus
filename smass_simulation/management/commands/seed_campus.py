"""V2.1 仿真数据生成入口。

    python manage.py seed_campus --profile small --seed 20261101 `
        --settings=smass.settings_simulation --stage org,students --dry-run
"""
from __future__ import annotations

import json
import os
import time

from django.core.management.base import BaseCommand, CommandError

from smass_simulation.models import SimulationBatch
from smass_simulation.generator import batch as batch_mod
from smass_simulation.generator import config as sim_config
from smass_simulation.generator import org as org_mod
from smass_simulation.generator import people as people_mod
from smass_simulation.generator import staff as staff_mod

ALL_STAGES = ['org', 'students', 'staff']


class Command(BaseCommand):
    help = '生成 SMASS V2.1 仿真数据（组织与人员，可扩展阶段）'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='small',
                            choices=list(sim_config.PROFILES))
        parser.add_argument('--seed', type=int, default=20261101)
        parser.add_argument('--stage', default='org,students')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--limit', type=int, default=0,
                            help='限制学生总数（调试用）')
        parser.add_argument('--batch-code', default='')
        parser.add_argument('--colleges', type=int, default=None)
        parser.add_argument('--majors', type=int, default=None)
        parser.add_argument('--grades', type=int, default=None)
        parser.add_argument('--classes-per', type=int, default=None)
        parser.add_argument('--students-per', type=int, default=None)

    def handle(self, *args, **options):
        overrides = {
            'colleges': options['colleges'], 'majors': options['majors'],
            'grades': options['grades'],
            'classes_per_major_grade': options['classes_per'],
            'students_per_class': options['students_per'],
        }
        config = sim_config.resolve(options['profile'], overrides)
        batch_code = options['batch_code'] or '{}-{}-{}'.format(
            config['profile'], options['seed'],
            options['stage'].replace(',', '+'))
        stages = [item.strip() for item in options['stage'].split(',')
                  if item.strip()]
        unknown = [item for item in stages if item not in ALL_STAGES]
        if unknown:
            raise CommandError('未知阶段：{}'.format(','.join(unknown)))

        os.environ['SIM_SEED'] = str(options['seed'])
        started = time.time()
        batch = batch_mod.get_batch(
            batch_code, config['profile'], options['seed'],
            dry_run=options['dry_run'])
        ctx = batch_mod.BatchContext(batch, dry_run=options['dry_run'])

        result = {'batch': batch_code, 'profile': config['profile'],
                  'seed': options['seed'], 'dry_run': options['dry_run'],
                  'stages': stages}
        try:
            if 'org' in stages:
                org_result = org_mod.generate(
                    config, ctx, dry_run=options['dry_run'])
                result['org'] = {
                    'colleges': len(org_result['colleges']) or config['colleges'],
                    'majors': len(org_result['majors']) or config['majors'],
                    'grades': len(org_result['grades']) or config['grades'],
                    'classes': len(org_result['classes']) or config['classes'],
                }
            if 'students' in stages:
                limit = options['limit'] or None
                student_result = people_mod.generate_students(
                    config, ctx, limit=limit, dry_run=options['dry_run'],
                    progress=lambda count: self.stdout.write(
                        '  students created: {}'.format(count)))
                result['students'] = student_result
            if 'staff' in stages:
                result['staff'] = staff_mod.generate_staff(
                    config, ctx, dry_run=options['dry_run'])
            ctx.flush()
        except Exception as exc:  # noqa: BLE001
            if not options['dry_run']:
                batch.status = SimulationBatch.STATUS_FAILED
                batch.note = str(exc)[:255]
                batch.save(update_fields=['status', 'note', 'updated_at'])
            raise

        elapsed_ms = int((time.time() - started) * 1000)
        result['elapsed_ms'] = elapsed_ms
        if not options['dry_run']:
            batch.status = SimulationBatch.STATUS_COMPLETED
            batch.duration_ms = elapsed_ms
            batch.counts = dict(batch.counts or {}, **{
                'colleges': config['colleges'], 'majors': config['majors'],
                'classes': config['classes'], 'students': config['students'],
            })
            batch.save(update_fields=['status', 'duration_ms', 'counts',
                                      'updated_at'])
            result['batch_status'] = batch.status
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
