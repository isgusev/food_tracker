from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app.database import engine
from app import models
# Импортируем наш новый роутер
from app.routers import products, recipes, diary

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Учет продуктов КБЖУ")

# Подключаем роутер в приложение
app.include_router(products.router)
app.include_router(recipes.router)
app.include_router(diary.router)

@app.get("/")
def read_root():
    return JSONResponse(
        content={"message": "Привет! Бэкенд запущен, таблицы базы данных проверены/созданы!"},
        media_type="application/json; charset=utf-8"
    )