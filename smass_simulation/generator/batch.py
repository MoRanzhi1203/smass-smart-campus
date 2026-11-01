"""批次上下文：登记对象、记录阶段进度、批量写对象索引。"""
from __future__ import annotations

from django.db import transaction

from smass_simulation.models import SimulationBatch, SimulationObject


class BatchContext:
    def __init__(self, batch, *, dry_run=False):
        self.batch = batch
        self.dry_run = dry_run
        self._pending = []

    @property
    def code(self):
        return self.batch.code

    def remember(self, model_label, pk):
        if self.dry_run or pk is None:
            return
        self._pending.append((model_label, str(pk)))
        if len(self._pending) >= 1000:
            self.flush()

    def remember_many(self, model_label, pks):
        for pk in pks:
            self.remember(model_label, pk)

    def flush(self):
        if self.dry_run or not self._pending:
            self._pending = []
            return 0
        rows = [SimulationObject(batch=self.batch, model_label=label,
                                 object_pk=pk)
                for label, pk in self._pending]
        SimulationObject.objects.bulk_create(rows, ignore_conflicts=True,
                                             batch_size=500)
        count = len(rows)
        self._pending = []
        return count

    def stage_done(self, stage, counts):
        if self.dry_run:
            return
        with transaction.atomic():
            batch = SimulationBatch.objects.select_for_update().get(
                pk=self.batch.pk)
            stage_done = dict(batch.stage_done or {})
            stage_done[stage] = True
            merged = dict(batch.counts or {})
            merged.update(counts)
            batch.stage_done = stage_done
            batch.counts = merged
            batch.save(update_fields=['stage_done', 'counts', 'updated_at'])
        self.batch.refresh_from_db()


def get_batch(code, profile, seed, *, dry_run=False):
    if dry_run:
        return SimulationBatch(code=code, profile=profile, seed=seed)
    batch, _created = SimulationBatch.objects.get_or_create(
        code=code, defaults={'profile': profile, 'seed': seed,
                             'status': SimulationBatch.STATUS_RUNNING})
    return batch
