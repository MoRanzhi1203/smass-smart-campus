"""仿真规模档位与规模计算。"""
from __future__ import annotations

PROFILES = {
    'small': {
        'colleges': 3,
        'majors': 6,
        'grades': 3,
        'classes_per_major_grade': 2,
        'students_per_class': 30,
    },
    'medium': {
        'colleges': 6,
        'majors': 18,
        'grades': 4,
        'classes_per_major_grade': 3,
        'students_per_class': 30,
    },
    'large': {
        'colleges': 10,
        'majors': 35,
        'grades': 4,
        'classes_per_major_grade': 4,
        'students_per_class': 30,
    },
}

COLLEGE_NAMES = [
    '计算机学院', '机械工程学院', '电气工程学院', '经济管理学院',
    '材料科学学院', '外国语学院', '数学与统计学院', '物理与电子学院',
    '化学与化工学院', '土木工程学院', '生命科学学院', '人文与法学院',
]

MAJOR_NAMES = [
    '计算机科学与技术', '软件工程', '人工智能', '数据科学与大数据技术',
    '机械设计制造及其自动化', '车辆工程', '机械电子工程',
    '电气工程及其自动化', '自动化', '电子信息工程',
    '工商管理', '会计学', '国际经济与贸易', '金融学',
    '材料科学与工程', '高分子材料与工程',
    '英语', '日语', '翻译',
    '数学与应用数学', '统计学', '信息与计算科学',
    '应用物理学', '光电信息科学与工程',
    '化学工程与工艺', '应用化学',
    '土木工程', '工程管理', '建筑环境与能源应用工程',
    '生物科学', '生物技术',
    '法学', '汉语言文学', '新闻学',
    '工业设计', '智能制造工程',
]

#: 学生状态分布（按年级）：前三个年级在读，最高年级有少量毕业/休学
STATUS_BY_GRADE = {
    'freshman': {'enrolled': 1.0},
    'sophomore': {'enrolled': 0.98, 'suspended': 0.02},
    'junior': {'enrolled': 0.97, 'suspended': 0.03},
    'senior': {'enrolled': 0.86, 'graduated': 0.11, 'suspended': 0.03},
}


def resolve(profile='medium', overrides=None):
    if profile not in PROFILES:
        raise ValueError('未知档位：{}'.format(profile))
    config = dict(PROFILES[profile])
    config['profile'] = profile
    if overrides:
        for key, value in overrides.items():
            if value is not None:
                config[key] = int(value)
    config['classes'] = (config['majors'] * config['grades']
                         * config['classes_per_major_grade'])
    config['students'] = config['classes'] * config['students_per_class']
    return config


def grade_labels(config):
    """年级标签：按“当前学年 - 年级序号”生成，如 2026/2025/2024/2023。"""
    base_year = 2026
    return [base_year - index for index in range(config['grades'])]
