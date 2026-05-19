"""技能：地理位置和天气查询"""

import subprocess
import json
from skills import register


def get_location():
    """获取当前设备的地理位置信息"""
    try:
        result = subprocess.run(
            ["curl", "-s", "https://ipinfo.io/json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            city = data.get("city", "")
            region = data.get("region", "")
            country = data.get("country", "")
            loc = data.get("loc", "")
            timezone = data.get("timezone", "")
            return f"城市: {city}, 地区: {region}, 国家: {country}, 坐标: {loc}, 时区: {timezone}"
        return "无法获取位置信息"
    except Exception as err:
        return f"获取位置失败: {err}"


def get_weather(city=""):
    """获取指定城市的天气信息"""
    try:
        if not city:
            loc_result = subprocess.run(
                ["curl", "-s", "https://ipinfo.io/json"],
                capture_output=True, text=True, timeout=10
            )
            if loc_result.returncode == 0:
                city = json.loads(loc_result.stdout).get("city", "")
        if not city:
            return "无法确定城市"
        result = subprocess.run(
            ["curl", "-s", f"https://wttr.in/{city}?format=%C+%t+%h+%w&lang=zh"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return f"{city}: {result.stdout.strip()}"
        return f"无法获取 {city} 的天气"
    except Exception as err:
        return f"获取天气失败: {err}"


register(
    name="get_location",
    description="获取当前设备的地理位置（城市、地区、国家、时区）",
    parameters={"type": "object", "properties": {}, "required": []},
    func=get_location,
)

register(
    name="get_weather",
    description="获取指定城市的实时天气，不指定城市则自动获取当前位置",
    parameters={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名（英文），留空自动定位",
            }
        },
        "required": [],
    },
    func=get_weather,
)
