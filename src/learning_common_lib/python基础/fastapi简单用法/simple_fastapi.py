import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import fastapi
from fastapi import FastAPI, APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from dataclasses import dataclass,field
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, TypedDict

class ErrorResponse(TypedDict):
    msg: str
    data: Optional[dict] = Field(default_factory=lambda: {})

class TestRequest(BaseModel):
    name: str
    age: int

class TestResponse(BaseModel):
    message: str

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


router_ = APIRouter()

@router_.post("/test", response_model=TestResponse)
async def test_1(request: TestRequest):
    if request.name != "John":
        raise HTTPException(status_code=400, 
                            detail=ErrorResponse(msg="Name must be John", data={"test": "test11111"}))
    # Do something with the request
    return TestResponse(message=f"Hello, {request.name}! You are {request.age} years old.")


if __name__ == "__main__":
    import uvicorn
    app.include_router(router_)
    uvicorn.run(app, host="0.0.0.0", port=8040)
