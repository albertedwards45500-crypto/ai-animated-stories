# -*- coding: utf-8 -*-
"""真实 Provider 实测脚本（record 模式验证，直接调用 Provider 不走队列）。

谨慎运行：会消耗真实 API 额度。
    python -m app.tools.real_provider_smoke [text|audio|image|video]
"""
from __future__ import annotations

import sys

from app.providers.dashscope import DashScopeAudioProvider, DashScopeImageProvider, DashScopeVideoProvider
from app.providers.real import DeepSeekTextProvider


def main() -> None:
    """按参数实测指定 Provider。"""
    target = sys.argv[1] if len(sys.argv) > 1 else "text"

    if target == "text":
        result = DeepSeekTextProvider().execute({
            "system_prompt": "你只返回 JSON。",
            "user_prompt": '返回 {"ok": true}',
            "temperature": 0.1,
        })
    elif target == "audio":
        result = DashScopeAudioProvider().execute({"text": "你终于来了。", "voice_id": "longxiaochun", "speed": 1.0})
    elif target == "image":
        result = DashScopeImageProvider().execute({"prompt": "雨夜城市街头，动漫风格，一个女孩撑伞回望，冷色调"})
    elif target == "video":
        result = DashScopeVideoProvider().execute({"img_url": sys.argv[2], "prompt": "镜头缓慢推进，人物微微转头"})
    else:
        raise SystemExit(f"未知目标 {target}")

    out = dict(result.output)
    if "local_file" in out:
        out["local_file_size"] = __import__("pathlib").Path(out["local_file"]).stat().st_size if __import__("pathlib").Path(out["local_file"]).exists() else "missing"
    print(f"ok={result.ok} model={result.model} elapsed_ms={result.elapsed_ms}")
    print(f"error={result.error_message}")
    keys = {k: (str(v)[:80]) for k, v in out.items() if k != "script"}
    print(f"output_keys={keys}")
    if "script" in out:
        print(f"script={str(out['script'])[:200]}")


if __name__ == "__main__":
    main()
