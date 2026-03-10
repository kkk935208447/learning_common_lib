# 09_self_exception

本目录专门讲清 4 个容易混淆但在企业项目里非常重要的概念：

1. `return JSONResponse`
2. `raise HTTPException`
3. `Pydantic` 请求校验与默认 `422`
4. 合法参数下的运行时异常，如何做生产级统一兜底

建议按下面顺序学习：

- `01_jsonresponse_vs_http_exception.py`
  重点理解“正常返回”和“异常中断”的执行流差异，以及客户端拿到的响应体差异。
- `02_pydantic_validation_422.py`
  重点理解 Pydantic 在路由函数执行前就完成校验，客户端为什么会收到详细的 `422`。
- `03_self_exception_and_global_handler.py`
  重点理解企业项目中的统一异常模型、自定义业务异常、未知异常兜底。

目录中的每个主题都拆成两份文件：

- `xx_name.py`
  服务文件，定义 `APIRouter`，可以独立运行并访问 `/docs`
- `xx_name_test.py`
  测试文件，使用 `aiohttp` 作为客户端请求真实启动的 `uvicorn` 服务，验证客户端视角看到的状态码、响应头和响应体

为了和后面的示例保持一致，本章统一使用 `{"code": ..., "message": "...", "data": ...}`。
有些团队把 `message` 命名为 `msg`，本质完全一样，只是字段名不同。

生产级实践建议：

- 正常成功响应优先返回 Pydantic 模型或字典，让 FastAPI 自动序列化
- 业务错误优先 `raise HTTPException` 或自定义业务异常，便于中断流程
- 只有在需要精细控制响应头、Cookie、非标准结构时，再显式 `return JSONResponse`
- 对 `RequestValidationError` 和未知 `Exception` 做统一封装，避免前端面对多套错误协议
- 业务可控错误抽成 `BusinessException`，未知系统错误交给 `@app.exception_handler(Exception)` 兜底
