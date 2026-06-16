"""技能：昇腾 NPU 工具集"""

import subprocess
import os
from skills import register

_toolkit_path_cache = None


def _get_toolkit_path():
    """查找 Ascend CANN toolkit 路径，结果缓存在进程内。"""
    global _toolkit_path_cache
    if _toolkit_path_cache is not None:
        return _toolkit_path_cache
    try:
        result = subprocess.run(
            "dirname $(find /usr/local/Ascend -name 'ccec' -type f 2>/dev/null | head -1) | xargs dirname",
            shell=True, capture_output=True, text=True, timeout=10,
        )
        _toolkit_path_cache = result.stdout.strip() or ""
    except Exception:
        _toolkit_path_cache = ""
    return _toolkit_path_cache


def npu_info():
    """查询昇腾 NPU 设备信息"""
    try:
        result = subprocess.run(
            "npu-smi info", shell=True, capture_output=True, text=True, timeout=10
        )
        output = result.stdout or ""
        if result.stderr:
            output += "\n" + result.stderr
        if not output.strip():
            return "未检测到 npu-smi 命令，可能未安装昇腾驱动"
        return output
    except subprocess.TimeoutExpired:
        return "npu-smi 执行超时"
    except Exception as err:
        return f"查询失败: {err}"


def ascend_build(project_dir, soc_version="ascend910b2"):
    """编译昇腾算子项目"""
    project_dir = os.path.expanduser(project_dir)
    if not os.path.isdir(project_dir):
        return f"目录不存在: {project_dir}"

    toolkit = _get_toolkit_path()
    if not toolkit:
        return "未找到 Ascend toolkit，请检查 CANN 安装"

    build_dir = os.path.join(project_dir, "build")
    cmake_cmd = (
        f"mkdir -p {build_dir} && cd {build_dir} && "
        f"cmake .. "
        f"-DASCEND_INSTALL_PATH={toolkit} "
        f"-DASCEND_CANN_PACKAGE_PATH={toolkit} "
        f"-DSOC_VERSION={soc_version} "
        f"&& make -j$(nproc)"
    )

    try:
        result = subprocess.run(
            cmake_cmd, shell=True, capture_output=True, text=True, timeout=120
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        output += f"\n[退出码: {result.returncode}]"
        if len(output) > 10000:
            output = output[:10000] + "\n...[截断]"
        return output
    except subprocess.TimeoutExpired:
        return "编译超时（120秒限制）"
    except Exception as err:
        return f"编译失败: {err}"


def ascend_run(executable, args=""):
    """运行昇腾算子可执行文件"""
    executable = os.path.expanduser(executable)
    if not os.path.isfile(executable):
        return f"可执行文件不存在: {executable}"

    env_setup = ""
    toolkit = _get_toolkit_path()
    if toolkit:
        env_setup = f"source {toolkit}/bin/setenv.bash 2>/dev/null; "

    cmd = f"{env_setup}{executable} {args}".strip()

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if not output:
            output = "(无输出)"
        output += f"\n[退出码: {result.returncode}]"
        if len(output) > 10000:
            output = output[:10000] + "\n...[截断]"
        return output
    except subprocess.TimeoutExpired:
        return "执行超时（60秒限制）"
    except Exception as err:
        return f"执行失败: {err}"


register(
    name="npu_info",
    description="查询昇腾 NPU 设备状态（芯片型号、温度、显存等）",
    parameters={"type": "object", "properties": {}, "required": []},
    func=npu_info,
    agent_only=True,
)

register(
    name="ascend_build",
    description="编译昇腾算子项目（自动探测 toolkit 路径，执行 cmake + make）",
    parameters={
        "type": "object",
        "properties": {
            "project_dir": {
                "type": "string",
                "description": "算子项目根目录路径",
            },
            "soc_version": {
                "type": "string",
                "description": "芯片型号，默认 ascend910b2",
            },
        },
        "required": ["project_dir"],
    },
    func=ascend_build,
    agent_only=True,
)

register(
    name="ascend_run",
    description="运行编译好的昇腾算子可执行文件",
    parameters={
        "type": "object",
        "properties": {
            "executable": {
                "type": "string",
                "description": "可执行文件路径",
            },
            "args": {
                "type": "string",
                "description": "运行参数",
            },
        },
        "required": ["executable"],
    },
    func=ascend_run,
    agent_only=True,
)
