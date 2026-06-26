---

### 阶段5：输出与存档（5分钟）

**编排组件**：`executor.phase5_output()` → `executor.phase5_complete()`

```python
output_config = executor.phase5_output()
# 按 output_config 生成 HTML/PDF, 发送到 Discord
executor.phase5_complete()  # 整个研究任务完成
```


1. **生成Markdown** - 最终文章写入output目录
2. **生成HTML** - 使用convert_any_md_to_html.py转换
3. **生成PDF** - 使用browser工具HTML转PDF
4. **发送到Discord** - message send channel=discord
