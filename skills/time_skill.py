"""技能：获取当前时间"""

from datetime import datetime
from skills import register


def get_current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


register(
    name="get_current_time",
    description="获取当前系统时间",
    parameters={"type": "object", "properties": {}, "required": []},
    func=get_current_time,
)
