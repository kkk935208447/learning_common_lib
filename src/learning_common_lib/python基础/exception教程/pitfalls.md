# 异常处理常见坑与反模式

这份文档只讲"什么会出错、为什么出错"。推荐做法见 [best_practices.md](best_practices.md)。

---

## 1. 吞异常（except: pass）

```python
try:
    process()
except:
    pass  # 异常被完全吞掉，没有日志，没有任何痕迹
```

后果：程序"悄悄失败"，数据不一致但没人知道。生产环境排查时完全没有线索。

至少要 `logger.exception("xxx")` 记录一下。

---

## 2. 字符串拼接 re-raise — 丢失原始 traceback

```python
try:
    db.execute(query)
except DatabaseError as e:
    raise RuntimeError(f"查询失败: {e}")  # 原始 traceback 丢失！
```

这是最常见的错误之一。新异常的 traceback 从 `raise RuntimeError(...)` 这一行开始，原始的数据库错误栈完全丢失。

正确做法：

```python
raise RuntimeError("查询失败") from e
```

---

## 3. 过度捕获（except Exception 包住整个函数）

```python
def process_order(order):
    try:
        validate(order)
        save(order)
        notify(order)
    except Exception as e:
        logger.error(f"处理失败: {e}")
        return None
```

问题：
- `validate` 的参数错误、`save` 的数据库错误、`notify` 的网络错误全部被同一个 except 吞掉
- 返回 `None` 让调用方无法区分"处理成功但结果为空"和"处理失败"
- 应该让不同类型的错误有不同的处理策略

---

## 4. 每一层都 catch + log（日志重复 3 遍）

```python
# Repository
try:
    row = db.fetch(query)
except Exception as e:
    logger.error(f"DB error: {e}")       # 日志 #1
    raise

# Service
try:
    user = repo.get_user(user_id)
except Exception as e:
    logger.error(f"Get user failed: {e}")  # 日志 #2
    raise

# Controller
try:
    result = service.process(user_id)
except Exception as e:
    logger.error(f"Process failed: {e}")   # 日志 #3
    return error_response()
```

同一个数据库错误在日志里出现了 3 次，排查时反而更混乱。日志应该只在异常最终被处理的地方记录一次。

---

## 5. 暴露内部细节给客户端（返回完整 traceback）

```python
@app.exception_handler(Exception)
async def handle_error(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": traceback.format_exc()}  # 暴露了完整调用栈！
    )
```

后果：
- 客户端看到数据库表名、SQL 语句、文件路径、内部函数名
- 安全风险：攻击者可以利用这些信息寻找漏洞

正确做法：返回通用错误信息，完整 traceback 只写入服务端日志。

---

## 6. 用异常做正常控制流

```python
# 错误 — 用异常控制循环
def find_item(items, target):
    try:
        i = 0
        while True:
            if items[i] == target:
                return i
            i += 1
    except IndexError:
        return -1
```

异常应该用于"异常情况"，不是正常的分支逻辑。`StopIteration` 是 Python 迭代器协议的一部分，属于特例。

---

## 7. except BaseException（会捕获 KeyboardInterrupt 和 SystemExit）

```python
try:
    long_running_task()
except BaseException:
    logger.error("出错了")
    # KeyboardInterrupt 和 SystemExit 也被捕获
    # Ctrl+C 无法中断程序，sys.exit() 无法退出
```

应该用 `except Exception`，它不会捕获 `KeyboardInterrupt`、`SystemExit` 和 `GeneratorExit`。

---

## 8. 在 except 块中引发不相关的异常（丢失上下文）

```python
try:
    data = fetch_data()
except ConnectionError:
    config = load_config()  # 这里也可能抛异常！
    # 如果 load_config() 抛出 FileNotFoundError
    # 原始的 ConnectionError 上下文会变成隐式链，容易混淆
```

在 except 块中执行可能失败的操作时，要注意异常链的影响。如果新异常和原始异常无关，考虑用 `raise ... from None` 显式切断链。

---

## 9. 忽略 __exit__ 返回值（上下文管理器意外吞异常）

```python
class MyContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return True  # 这会吞掉所有异常！
```

`__exit__` 返回 `True` 表示"异常已处理，不需要继续传播"。大多数情况下不应该返回 `True`，除非你明确知道要抑制异常。

---

## 10. 异常类不继承正确的基类（直接继承 BaseException）

```python
# 错误 — 直接继承 BaseException
class MyError(BaseException):
    pass

# 后果：except Exception 捕获不到 MyError
try:
    raise MyError("出错了")
except Exception:
    print("捕获到了")  # 不会执行！
```

自定义异常应该继承 `Exception`（或其子类），不要直接继承 `BaseException`。`BaseException` 是留给 `KeyboardInterrupt`、`SystemExit` 等系统级异常的。

---

## 11. 在 finally 中 return（吞掉异常）

```python
def dangerous():
    try:
        raise ValueError("出错了")
    finally:
        return 42  # 异常被静默吞掉，函数返回 42
```

这是 Python 的一个陷阱：`finally` 中的 `return` 会覆盖 `try` 或 `except` 中的异常或返回值。异常就像从未发生过一样消失了。

同理，`finally` 中的 `break` 和 `continue`（在循环中）也会吞掉异常。

---

## 一句话总结

异常处理真正难的地方不是 `try/except`，而是边界设计：在哪里捕获、在哪里转换、在哪里记录、什么信息该暴露给客户端、什么信息该留在服务端日志里。
