# UI 改进设计（清除缓存按钮 + 原地修改限制 + 标签下拉）

## 议题1：清除缓存按钮

### 背景
缓存清理逻辑 `clean_expired_cache` 已存在于 `app/wrappers.py`，但无用户入口。

### 交互流程
用户点击"清除缓存"按钮 → 弹确认对话框"是否确认清除缓存？" → 用户点确定 → 调用后端 `clear_cache` API → 执行清除 → 返回结果提示

### 后端改动（`app/bridge.py`）
新增方法：
```python
def clear_cache(self) -> dict[str, Any]:
    """清除合成缓存目录"""
    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
            cache_dir = Path(sys.executable).parent / "cache" / "img_tool_synthesize_cache"
        else:
            cache_dir = Path(tempfile.gettempdir()) / "img_tool_synthesize_cache"

        removed_count = 0
        if cache_dir.exists():
            for item in cache_dir.iterdir():
                try:
                    if item.is_file():
                        item.unlink()
                        removed_count += 1
                    elif item.is_dir():
                        shutil.rmtree(item)
                        removed_count += 1
                except Exception:
                    pass
        return {"ok": True, "removed_count": removed_count}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
```

### 前端改动（`ui/new.html`）
- 合成标注界面（模型状态栏旁）加"清除缓存"按钮
- 点击后弹出确认对话框，用户点确定后调用 `api.clear_cache()`
- 根据返回结果提示成功/失败

---

## 议题2：合成标注原地修改限制

### 背景
合成标注功能不支持原地修改，但当前 UI 未做限制，用户可能误选导致困惑。

### 交互规则
1. 切换到合成标注模块时，强制切为"安全复制"模式
2. 模式选择器中"原地修改"选项对合成标注置灰（disabled）
3. 执行时即使误选原地修改，也强制走另存输出

### 前端改动（`ui/new.html`）
- `renderForm()` 切换到 synthesize 时强制 `state.mode = "safe_copy"`
- 模式 radio 选项中原地修改对 synthesize 禁用

---

## 议题3：合成标注标签下拉框

### 背景
用户填写"合成后标注标签"时为自由文本，缺乏引导。同时应支持自由输入。

### 交互设计
- 标签下拉框选项：`animal`（默认）、`obstacle`
- 同时保留自由输入框，用户可选择预设也可手动输入
- 初始默认选中 `obstacle`

### 前端改动（`ui/new.html`）
- `synthesize.params` 中 `label` 字段由 `type: "text"` 改为 `type: "select"`
- 添加 `options: [{value: "animal", label: "animal"}, {value: "obstacle", label: "obstacle"}]`
- 保留 `placeholder` 供自由输入回退

---

## 实施步骤

1. **后端** `app/bridge.py`：新增 `clear_cache()` API
2. **前端** `ui/new.html`：
   - synthesize 界面加清除缓存按钮（议题1）
   - 切换到 synthesize 时强制 safe_copy（议题2）
   - `label` 参数改为下拉框（议题3）
3. 测试验证
