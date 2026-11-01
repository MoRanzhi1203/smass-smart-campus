"""确定性随机：同一 seed 产生同一序列；不同阶段用派生 seed 隔离。"""
from __future__ import annotations

import hashlib
import random


def derive(seed, stage):
    digest = hashlib.sha256('{}:{}'.format(seed, stage).encode('utf-8')).digest()
    return int.from_bytes(digest[:8], 'big')


class Rng:
    def __init__(self, seed, stage='base'):
        self.seed = derive(seed, stage)
        self._random = random.Random(self.seed)

    def choice(self, items):
        return self._random.choice(list(items))

    def randint(self, low, high):
        return self._random.randint(low, high)

    def sample(self, items, count):
        items = list(items)
        return self._random.sample(items, min(count, len(items)))

    def weighted(self, mapping):
        """按权重字典抽样，键为结果值。"""
        total = sum(mapping.values())
        if total <= 0:
            raise ValueError('权重之和必须为正')
        point = self._random.random() * total
        upto = 0.0
        for key, weight in mapping.items():
            upto += weight
            if point <= upto:
                return key
        return list(mapping)[-1]

    def shuffle(self, items):
        items = list(items)
        self._random.shuffle(items)
        return items
