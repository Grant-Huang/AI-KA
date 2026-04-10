# 应用设置（默认）

当 `app_settings.md` 不存在或解析失败时，系统会回退读取本文件。

```json
{
  "chunk_limit": 40,
  "chunk_strategy": "blank",
  "disable_image_parse": true,
  "llm_settings": {
    "text_provider": "openai_compatible",
    "text_base_url": "https://api.minimaxi.com/v1",
    "text_model": "MiniMax-M2.7",
    "vl_model": "qwen3-vl-plus",
    "vl_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
  },
  "llm_text_api_key": "",
  "llm_vl_api_key": ""
}
```

