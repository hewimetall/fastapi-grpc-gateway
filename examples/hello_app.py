"""Example FastAPI app for manual runs."""

from fastapi import Body, FastAPI
from pydantic import BaseModel

from fastapi_grpc_gateway import GrpcGateway

app = FastAPI(title="fgg-example")


class Item(BaseModel):
    name: str
    price: float = 0


@app.get("/api/hello")
async def hello() -> dict[str, str]:
    return {"message": "hello"}


@app.get("/api/users/{user_id}")
async def get_user(user_id: int) -> dict[str, int | str]:
    return {"user_id": user_id, "name": f"user-{user_id}"}


@app.post("/api/items")
async def create_item(item: Item = Body(...)) -> Item:
    return item


gateway = GrpcGateway(app, port=50051)
app.router.lifespan_context = gateway.lifespan
